"""Casbin enforcer factory.

Provides an async enforcer backed by SQLAlchemy. The model is flat RBAC:
*subject* is ``user:<uuid>`` or ``role:<id>``, *object* is either a resource
type (``post``) or a per-instance identifier (``post:<id>``), *action* is a
verb (``read``, ``write``, ``edit``).

ABAC owner-checks and per-object grants are layered on top in
:class:`apps.rbac.services.AccessService`.

Multi-worker deployments
------------------------

Each worker holds its own in-memory enforcer. When worker A writes a policy
via ``add_policy()``, worker B will not see it until B re-reads the policy
table. To keep workers consistent, pass ``watcher_redis_url`` to
:func:`create_enforcer` — it will attach a pub/sub watcher that broadcasts
invalidations across workers.

The ``casbin-redis-watcher`` package is an optional dependency. Install it
with ``uv add casbin-redis-watcher`` before enabling the watcher URL. If the
URL is set but the package is missing, :func:`create_enforcer` logs a warning
and returns an enforcer without a watcher — the app keeps running but is
only safe with ``--workers 1``.
"""

from __future__ import annotations

from pathlib import Path

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from loguru import logger

RBAC_MODEL_PATH = Path(__file__).parent / "casbin" / "rbac_model.conf"


async def create_enforcer(
    database_uri: str,
    *,
    watcher_redis_url: str | None = None,
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
    """Attach a Redis pub/sub watcher if the optional dependency is installed.

    The import is deferred so the ``casbin-redis-watcher`` package only needs
    to be present when a deployment actually enables the watcher URL. A
    missing package logs a warning and keeps the enforcer watcher-less
    (safe for single-worker runs, unsafe for multi-worker).
    """
    try:
        from casbin_redis_watcher import new_watcher  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "create_enforcer - watcher_redis_url is set but "
            "'casbin-redis-watcher' is not installed; running without a "
            "watcher. Install it or unset the URL before running with "
            "--workers >1."
        )
        return

    watcher = new_watcher(redis_url)
    enforcer.set_watcher(watcher)
    logger.info("create_enforcer - Casbin Redis watcher attached at {url}", url=redis_url)
