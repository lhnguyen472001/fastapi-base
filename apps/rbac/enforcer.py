"""Casbin enforcer factory."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from casbin_redis_watcher import WatcherOptions, new_watcher
from loguru import logger

from apps.settings import app_settings

RBAC_MODEL_PATH = Path(__file__).parent / "casbin" / "rbac_model.conf"


async def enforcer_factory(
    database_uri: str = app_settings.db.database_uri.render_as_string(hide_password=False),
    *,
    watcher_redis_url: str | None = app_settings.rbac.watcher_redis_url,
) -> casbin.AsyncEnforcer:
    """Build and load an async Casbin enforcer.

    Args:
        database_uri: SQLAlchemy URL for policy storage. The adapter creates
            its own ``casbin_rule`` table on first use.
        watcher_redis_url: Optional Redis URL. When provided, the enforcer is
            wired to a Redis pub/sub watcher so policy mutations on one worker
            invalidate the in-memory enforcer on every other worker. Required
            before scaling beyond a single uvicorn worker.

    Returns:
        Loaded :class:`casbin.AsyncEnforcer` ready for ``enforce`` calls.
    """
    adapter = Adapter(database_uri)
    await adapter.create_table()
    enforcer = casbin.AsyncEnforcer(str(RBAC_MODEL_PATH), adapter)
    await enforcer.load_policy()

    if watcher_redis_url:
        _attach_redis_watcher(enforcer, watcher_redis_url)

    return enforcer


def _attach_redis_watcher(enforcer: casbin.AsyncEnforcer, redis_url: str) -> None:
    """Attach a Redis pub/sub watcher to broadcast policy mutations.

    Each worker holds an independent in-memory enforcer; the watcher
    invalidates every other worker's enforcer on policy mutation, so
    role / permission changes converge in real time.
    """
    options = _build_watcher_options(redis_url)
    watcher = new_watcher(options)
    enforcer.set_watcher(watcher)
    logger.info("enforcer_factory - Casbin Redis watcher attached at {url}", url=redis_url)


def _build_watcher_options(redis_url: str) -> WatcherOptions:
    """Translate ``redis://[:password@]host[:port][/db]`` into ``WatcherOptions``.

    ``casbin_redis_watcher.new_watcher`` requires a :class:`WatcherOptions`
    instance; it builds the underlying ``redis.Redis`` client from
    ``host`` / ``port`` / ``password`` / ``ssl`` and rejects a URL string.
    The ``/db`` path segment is irrelevant — Redis pub/sub channels are not
    scoped by db — so it is parsed for validation only and not propagated.
    """
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        msg = f"RBAC watcher URL must use redis:// or rediss:// — got {redis_url!r}"
        raise ValueError(msg)

    options = WatcherOptions()
    options.host = parsed.hostname or "localhost"
    options.port = parsed.port or 6379
    options.password = parsed.password
    options.ssl = parsed.scheme == "rediss"
    return options
