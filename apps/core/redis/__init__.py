"""Redis client + JSON cache layer.

Public entry points:
    - :class:`RedisClient` — async wrapper over ``redis.asyncio``.
    - :class:`CacheManager` — JSON cache + decorator built on RedisClient.
    - :func:`get_redis_client` — lazy process-wide singleton.
    - :func:`close_redis_client` — lifespan teardown hook.
"""

from .cache import CacheManager
from .client import RedisClient, close_redis_client, get_redis_client

__all__ = [
    "CacheManager",
    "RedisClient",
    "close_redis_client",
    "get_redis_client",
]
