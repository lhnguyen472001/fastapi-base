"""Async Redis client with connection pooling and graceful degradation.

The module exposes a thin async wrapper around ``redis.asyncio`` plus a
process-wide singleton accessor. ``get_redis_client()`` returns ``None``
when ``app_settings.redis.enabled`` is false or the connection cannot be
established — callers (e.g. :class:`CacheManager`) treat that as the
no-op signal and short-circuit cleanly.

Lifecycle:
    The singleton is created lazily on first call and torn down via
    :func:`close_redis_client` from the FastAPI lifespan. We deliberately
    do *not* cache the failure case so a transient init error doesn't
    poison the rest of the process.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from loguru import logger
from redis import exceptions as redis_exceptions

from apps.settings import app_settings


class RedisClient:
    """Async Redis client with connection pooling.

    Provides high-performance async Redis operations with automatic
    connection pooling, narrow error handling, and graceful degradation
    for connection-level errors (which return safe fallbacks). Programmer
    errors (wrong types, malformed commands) are propagated as
    :class:`redis.exceptions.RedisError` subclasses.
    """

    def __init__(self, pool: aioredis.ConnectionPool) -> None:
        """Initialize Redis client with a pre-built connection pool."""
        self._pool = pool
        self._client: aioredis.Redis = aioredis.Redis(connection_pool=pool)

    @property
    def client(self) -> aioredis.Redis:
        """Expose the underlying ``aioredis.Redis`` for advanced operations.

        Use this only when no wrapper method exists (pipelines, scripts,
        pubsub). Prefer the explicit methods on :class:`RedisClient` so
        error handling stays consistent.
        """
        return self._client

    async def ping(self) -> bool:
        """Check Redis connection health."""
        try:
            return bool(await self._client.ping())
        except redis_exceptions.RedisError:
            logger.exception("RedisClient - ping - failed")
            return False

    async def get(self, key: str) -> str | None:
        """Get value by key. Returns ``None`` on connection failure."""
        try:
            return await self._client.get(key)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - get - connection failed", key=key)
            return None

    async def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
        px: int | None = None,
        *,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """Set key-value pair with optional expiration.

        Args:
            key: Redis key.
            value: Value to store.
            ex: Expiration in seconds.
            px: Expiration in milliseconds.
            nx: Only set if key does not exist.
            xx: Only set if key exists.

        Returns:
            True if set succeeded, False on connection failure or NX/XX miss.
        """
        try:
            result = await self._client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
            return bool(result)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - set - connection failed", key=key)
            return False

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns count deleted (0 on failure)."""
        if not keys:
            return 0
        try:
            return await self._client.delete(*keys)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - delete - connection failed", keys=keys)
            return 0

    async def exists(self, *keys: str) -> int:
        """Return the number of keys in ``keys`` that exist."""
        if not keys:
            return 0
        try:
            return await self._client.exists(*keys)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - exists - connection failed", keys=keys)
            return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time (seconds) for ``key``."""
        try:
            return bool(await self._client.expire(key, seconds))
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - expire - connection failed", key=key)
            return False

    async def ttl(self, key: str) -> int:
        """Remaining TTL (seconds). ``-1`` no expiry, ``-2`` missing key, ``-2`` on failure."""
        try:
            return await self._client.ttl(key)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - ttl - connection failed", key=key)
            return -2

    async def scan_iter(self, match: str, count: int = 100) -> AsyncIterator[str]:
        """Iterate keys matching ``match`` via SCAN (production-safe vs KEYS).

        Yields keys in chunks of ``count`` per cursor step. Bails silently
        on connection error so callers don't deadlock during incidents.
        """
        try:
            async for key in self._client.scan_iter(match=match, count=count):
                yield key
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - scan_iter - connection failed", pattern=match)
            return

    # Hash operations -------------------------------------------------------
    async def hget(self, name: str, key: str) -> str | None:
        try:
            return await self._client.hget(name, key)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - hget - connection failed", name=name, key=key)
            return None

    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        try:
            return await self._client.hset(name, key, value, mapping=mapping)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - hset - connection failed", name=name)
            return 0

    async def hdel(self, name: str, *keys: str) -> int:
        if not keys:
            return 0
        try:
            return await self._client.hdel(name, *keys)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - hdel - connection failed", name=name)
            return 0

    async def hgetall(self, name: str) -> dict[str, str]:
        try:
            return await self._client.hgetall(name)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - hgetall - connection failed", name=name)
            return {}

    # List operations -------------------------------------------------------
    async def lpush(self, name: str, *values: str) -> int:
        if not values:
            return 0
        try:
            return await self._client.lpush(name, *values)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - lpush - connection failed", name=name)
            return 0

    async def rpush(self, name: str, *values: str) -> int:
        if not values:
            return 0
        try:
            return await self._client.rpush(name, *values)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - rpush - connection failed", name=name)
            return 0

    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        try:
            return await self._client.lrange(name, start, end)
        except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
            logger.warning("RedisClient - lrange - connection failed", name=name)
            return []

    async def close(self) -> None:
        """Close client and connection pool."""
        try:
            await self._client.close()
            await self._pool.disconnect(inuse_connections=True)
            logger.info("RedisClient - close - connection closed")
        except redis_exceptions.RedisError:
            logger.exception("RedisClient - close - failed to close cleanly")


_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient | None:
    """Return the process-wide :class:`RedisClient` singleton.

    Returns ``None`` when ``app_settings.redis.enabled`` is false or the
    connection pool cannot be created. Failures are *not* memoized — a
    later call retries, so a transient init error during boot doesn't
    permanently degrade the cache layer.
    """
    global _redis_client  # noqa: PLW0603 — process-wide singleton

    if _redis_client is not None:
        return _redis_client

    settings = app_settings.redis
    if not settings.enabled:
        return None

    try:
        password = settings.password.get_secret_value() if settings.password else None
        pool = aioredis.ConnectionPool.from_url(
            f"redis://{settings.host}:{settings.port}/{settings.database}",
            password=password,
            max_connections=settings.max_connections,
            socket_timeout=settings.socket_timeout,
            socket_connect_timeout=settings.socket_connect_timeout,
            decode_responses=settings.decode_responses,
        )
        _redis_client = RedisClient(pool)
        logger.info(
            "RedisClient - init - connected",
            host=settings.host,
            port=settings.port,
            database=settings.database,
        )
    except (redis_exceptions.RedisError, OSError):
        logger.exception("RedisClient - init - failed to initialize")
        return None
    return _redis_client


async def close_redis_client() -> None:
    """Tear down the singleton; safe to call when never initialized."""
    global _redis_client  # noqa: PLW0603 — process-wide singleton
    if _redis_client is None:
        return
    await _redis_client.close()
    _redis_client = None
