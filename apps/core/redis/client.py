"""Async Redis client with connection pooling and graceful degradation.

The module exposes a thin async wrapper around ``redis.asyncio`` plus a
process-wide singleton accessor. ``get_redis_client()`` returns ``None``
when ``app_settings.redis.enabled`` is false or the connection cannot be
established — callers (e.g. :class:`CacheManager`) treat that as the
no-op signal and short-circuit cleanly.

Transient failures (``ConnectionError`` / ``TimeoutError``) on hot-path
helpers are retried once via :func:`tenacity.retry` so a one-shot
network blip does not translate into a lost request. After the retry
budget is exhausted, ``retry_error_callback`` returns the per-method
safe fallback (``None`` / ``False`` / ``0`` / ``[]`` / ``{}``). Tunables
live in :mod:`apps.core.redis.constants`.

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
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from apps.core.redis.constants import (
    REDIS_TRANSIENT_RETRY_ATTEMPTS,
    REDIS_TRANSIENT_RETRY_DELAY_SECONDS,
)
from apps.settings import app_settings

# Transient errors that warrant a single retry. Programmer errors
# (``ResponseError``, ``DataError``) are NOT in this tuple — retrying a
# malformed command just doubles the wasted work.
_TRANSIENT_REDIS_ERRORS = (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError)


def _transient_retry[T](
    *,
    fallback: T,
    retry_on: type[BaseException] | tuple[type[BaseException], ...] = _TRANSIENT_REDIS_ERRORS,
):
    """Build a :func:`tenacity.retry` decorator with per-method safe fallback.

    The returned decorator runs the wrapped coroutine up to
    ``REDIS_TRANSIENT_RETRY_ATTEMPTS`` times, sleeping
    ``REDIS_TRANSIENT_RETRY_DELAY_SECONDS`` between attempts on any
    exception in ``retry_on``. After the budget is exhausted,
    ``retry_error_callback`` logs a WARNING and returns ``fallback``
    instead of re-raising — preserving the historical "degraded mode
    still serves traffic" contract.

    Args:
        fallback: Value returned to the caller after the retry budget
            is exhausted. Must match the wrapped method's return type.
        retry_on: Exception (or tuple of exceptions) that triggers a
            retry. Defaults to connection/timeout errors only;
            ``ping`` widens this to the full ``RedisError`` family to
            preserve its historical broad-catch behaviour.
    """

    def _fallback_callback(retry_state: RetryCallState) -> T:
        exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
        logger.warning(
            "{method} - failed after {n} attempts: {!r}",
            exc,
            method=retry_state.fn.__qualname__ if retry_state.fn else "<unknown>",
            n=retry_state.attempt_number,
        )
        return fallback

    return retry(
        stop=stop_after_attempt(REDIS_TRANSIENT_RETRY_ATTEMPTS),
        wait=wait_fixed(REDIS_TRANSIENT_RETRY_DELAY_SECONDS),
        retry=retry_if_exception_type(retry_on),
        retry_error_callback=_fallback_callback,
    )


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

    @_transient_retry(fallback=False, retry_on=redis_exceptions.RedisError)
    async def ping(self) -> bool:
        """Check Redis connection health."""
        return bool(await self._client.ping())

    @_transient_retry(fallback=None)
    async def get(self, key: str) -> str | None:
        """Get value by key. Returns ``None`` on connection failure."""
        return await self._client.get(key)

    @_transient_retry(fallback=False)
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
        return bool(await self._client.set(key, value, ex=ex, px=px, nx=nx, xx=xx))

    @_transient_retry(fallback=0)
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns count deleted (0 on failure)."""
        if not keys:
            return 0
        return await self._client.delete(*keys)

    @_transient_retry(fallback=0)
    async def exists(self, *keys: str) -> int:
        """Return the number of keys in ``keys`` that exist."""
        if not keys:
            return 0
        return await self._client.exists(*keys)

    @_transient_retry(fallback=False)
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time (seconds) for ``key``."""
        return bool(await self._client.expire(key, seconds))

    @_transient_retry(fallback=-2)
    async def ttl(self, key: str) -> int:
        """Remaining TTL (seconds). ``-1`` no expiry, ``-2`` missing key, ``-2`` on failure."""
        return await self._client.ttl(key)

    async def scan_iter(self, match: str, count: int = 100) -> AsyncIterator[str]:
        """Iterate keys matching ``match`` via SCAN (production-safe vs KEYS).

        Yields keys in chunks of ``count`` per cursor step. Bails silently
        on connection error so callers don't deadlock during incidents.

        Note: async generators don't compose cleanly with ``tenacity.retry``
        (the decorator targets coroutines, not async generators); a
        transient blip mid-scan terminates the iteration and the caller
        is expected to re-issue if it cares.
        """
        try:
            async for key in self._client.scan_iter(match=match, count=count):
                yield key
        except _TRANSIENT_REDIS_ERRORS:
            logger.warning("RedisClient - scan_iter - connection failed", pattern=match)
            return

    # Hash operations -------------------------------------------------------
    @_transient_retry(fallback=None)
    async def hget(self, name: str, key: str) -> str | None:
        return await self._client.hget(name, key)

    @_transient_retry(fallback=0)
    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        return await self._client.hset(name, key, value, mapping=mapping)

    @_transient_retry(fallback=0)
    async def hdel(self, name: str, *keys: str) -> int:
        if not keys:
            return 0
        return await self._client.hdel(name, *keys)

    @_transient_retry(fallback={})
    async def hgetall(self, name: str) -> dict[str, str]:
        return await self._client.hgetall(name)

    # List operations -------------------------------------------------------
    @_transient_retry(fallback=0)
    async def lpush(self, name: str, *values: str) -> int:
        if not values:
            return 0
        return await self._client.lpush(name, *values)

    @_transient_retry(fallback=0)
    async def rpush(self, name: str, *values: str) -> int:
        if not values:
            return 0
        return await self._client.rpush(name, *values)

    @_transient_retry(fallback=[])
    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        return await self._client.lrange(name, start, end)

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
