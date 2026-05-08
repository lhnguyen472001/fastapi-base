"""JSON-serialized cache layer on top of :class:`RedisClient`.

:class:`CacheManager` is the entry point for application-level caching.
It serializes values via ``json.dumps(default=str)`` so common non-native
types (UUID, datetime) survive the round trip, and short-circuits to
no-op behavior whenever the underlying :class:`RedisClient` is ``None``
(i.e. Redis is disabled or unreachable).

Pattern invalidation uses ``SCAN`` (never ``KEYS``) and batches deletes
in chunks of 500 keys to keep per-pipeline latency bounded.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from loguru import logger

from .client import RedisClient
from .constants import INVALIDATE_BATCH_SIZE

P = ParamSpec("P")
R = TypeVar("R")


class CacheManager:
    """JSON cache wrapper with a decorator for memoizing async functions.

    Example:
        ```python
        cache = CacheManager(get_redis_client())


        @cache.cached(ttl=300, key_prefix="user")
        async def get_user_data(user_id: UUID) -> dict: ...


        await cache.set("explicit:key", {"data": "value"}, ttl=600)
        data = await cache.get("explicit:key")
        ```
    """

    def __init__(self, redis_client: RedisClient | None) -> None:
        """Initialize cache manager.

        Args:
            redis_client: Underlying client. Pass ``None`` to disable
                caching entirely (every method becomes a no-op).
        """
        self.redis = redis_client

    async def get(self, key: str) -> Any:
        """Return cached value or ``None`` (also returned on Redis failure)."""
        if not self.redis:
            return None

        value = await self.redis.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.warning("CacheManager - get - non-JSON value, treating as miss", key=key)
            return None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Serialize ``value`` to JSON and store with the given TTL.

        ``ttl`` is required (in seconds, must be positive). Caching
        without expiry leaks Redis memory; a positive TTL is enforced
        project-wide.
        """
        if not self.redis:
            return False
        if ttl <= 0:
            msg = f"CacheManager.set requires a positive TTL; got {ttl}."
            raise ValueError(msg)

        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError):
            logger.exception("CacheManager - set - failed to serialize value", key=key)
            return False

        return await self.redis.set(key, serialized, ex=ttl)

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        if not self.redis or not keys:
            return 0
        return await self.redis.delete(*keys)

    async def exists(self, *keys: str) -> bool:
        """Return True iff *all* ``keys`` exist."""
        if not self.redis or not keys:
            return False
        count = await self.redis.exists(*keys)
        return count == len(keys)

    async def incr(self, key: str) -> int:
        """Atomically increment the integer at ``key``; return the new value.

        Returns ``0`` when Redis is disabled, so callers using the result
        as a versioned key suffix get a stable initial value rather than
        a crash.
        """
        if not self.redis:
            return 0
        return int(await self.redis.client.incr(key))

    async def get_int(self, key: str) -> int:
        """Return the integer at ``key`` or ``0`` (also when missing / Redis off)."""
        if not self.redis:
            return 0
        raw = await self.redis.get(key)
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("CacheManager - get_int - non-int value, treating as 0", key=key)
            return 0

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete every key matching ``pattern`` (e.g. ``"user:*"``).

        Uses Redis ``SCAN`` (production-safe; ``KEYS`` is forbidden) and
        batches deletes so a wide pattern doesn't pin a single command
        for too long. Returns the number of keys actually deleted.
        """
        if not self.redis:
            return 0

        deleted = 0
        batch: list[str] = []
        async for key in self.redis.scan_iter(match=pattern):
            batch.append(key)
            if len(batch) >= INVALIDATE_BATCH_SIZE:
                deleted += await self.redis.delete(*batch)
                batch.clear()
        if batch:
            deleted += await self.redis.delete(*batch)

        logger.debug(
            "CacheManager - invalidate_pattern - swept",
            pattern=pattern,
            deleted=deleted,
        )
        return deleted

    def cached(
        self,
        ttl: int = 300,
        key_prefix: str = "",
        key_builder: Callable[..., str] | None = None,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Decorator that memoizes async function results in Redis.

        Args:
            ttl: Time-to-live in seconds. Defaults to 5 minutes.
            key_prefix: Optional namespace prefix for cache keys.
            key_builder: Optional override for key generation. Receives
                the same ``(*args, **kwargs)`` as the wrapped function and
                must return a stable string.

        Returns:
            Decorator that wraps an async function.

        Raises:
            TypeError: If applied to a non-async function.

        Example:
            ```python
            @cache.cached(ttl=600, key_prefix="user")
            async def get_user_data(user_id: UUID) -> dict: ...
            ```
        """

        def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            if not asyncio.iscoroutinefunction(func):
                msg = f"CacheManager.cached only wraps async functions; got {func!r}"
                raise TypeError(msg)

            @functools.wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                cache_key = (
                    key_builder(*args, **kwargs)
                    if key_builder
                    else self._build_cache_key(func, args, kwargs, key_prefix)
                )

                cached_value = await self.get(cache_key)
                if cached_value is not None:
                    logger.debug("CacheManager - cached - hit", key=cache_key)
                    return cached_value

                logger.debug("CacheManager - cached - miss", key=cache_key)
                result = await func(*args, **kwargs)
                await self.set(cache_key, result, ttl=ttl)
                return result

            return wrapper

        return decorator

    @staticmethod
    def _build_cache_key(
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        prefix: str = "",
    ) -> str:
        """Build a deterministic cache key from a function and its arguments.

        UUIDs, datetimes, and other non-JSON-native types are coerced via
        ``default=str``. Anything that ``default=str`` cannot serialize
        raises :class:`TypeError` here rather than silently falling back
        to ``repr()`` — two unrelated objects with identical ``repr``
        otherwise collide on the same cache key.
        """
        func_name = f"{func.__module__}.{func.__name__}"

        args_str = json.dumps(
            {"args": args, "kwargs": kwargs},
            sort_keys=True,
            default=str,
        )

        hash_bytes = hashlib.sha256(args_str.encode()).digest()
        args_hash = base64.b32encode(hash_bytes).decode().rstrip("=").lower()[:16]

        parts = [prefix, func_name, args_hash] if prefix else [func_name, args_hash]
        return ":".join(parts)
