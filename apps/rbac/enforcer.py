"""Casbin enforcer factory."""

from __future__ import annotations

from pathlib import Path

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from casbin_redis_watcher import new_watcher
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
    watcher = new_watcher(redis_url)
    enforcer.set_watcher(watcher)
    logger.info("enforcer_factory - Casbin Redis watcher attached at {url}", url=redis_url)
