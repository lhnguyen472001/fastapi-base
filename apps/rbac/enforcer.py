"""Casbin enforcer factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import casbin
from casbin_async_sqlalchemy_adapter import Adapter
from casbin_redis_watcher import WatcherOptions, new_watcher
from loguru import logger
from opentelemetry import metrics

from apps.settings import app_settings

RBAC_MODEL_PATH = Path(__file__).parent / "casbin" / "rbac_model.conf"

# Module-level slot holding the registered policy-count gauge instrument so
# the OTel SDK does not garbage-collect it after registration. Re-registration
# replaces the slot, which is idempotent because the SDK de-dupes instruments
# by name within a meter.
_POLICY_COUNT_GAUGE: Any = None


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


def register_policy_count_gauge(
    enforcer: casbin.AsyncEnforcer,
    *,
    meter: metrics.Meter | None = None,
) -> Any:
    """Register an observable up-down counter for the in-memory policy size.

    The instrument is named ``rbac_enforcer_policy_count`` (unit
    ``{policies}``). Its callback runs at metric-reader scrape time and
    reports ``len(enforcer.get_policy()) + len(enforcer.get_grouping_policy())``
    as a single integer observation per worker. See
    ``specs/002-code-quality-perf-improvements/contracts/metrics.md``.

    The returned instrument is also held on a module-level slot so the
    SDK does not garbage-collect it after registration. The function is
    idempotent — re-registering against the same meter replaces the
    instrument; the SDK de-dupes by name within a meter scope.

    Args:
        enforcer: The Casbin enforcer to observe.
        meter: Optional injected meter; defaults to the global meter for
            ``apps.rbac``. The parameter exists primarily for tests that
            install an isolated ``MeterProvider`` + ``InMemoryMetricReader``
            (OTel's global meter provider is set-once).

    Returns:
        The registered observable instrument.
    """
    # The module-level slot keeps the instrument alive for the SDK after
    # registration; the global is intentional, not accidental shared state.
    global _POLICY_COUNT_GAUGE  # noqa: PLW0603

    target_meter = meter if meter is not None else metrics.get_meter("apps.rbac")

    def _callback(_options: Any) -> Any:
        try:
            total = len(enforcer.get_policy()) + len(enforcer.get_grouping_policy())
        except Exception as exc:
            logger.warning(
                "register_policy_count_gauge - callback failed; skipping observation: {!r}",
                exc,
            )
            return ()
        return (metrics.Observation(total),)

    _POLICY_COUNT_GAUGE = target_meter.create_observable_up_down_counter(
        name="rbac_enforcer_policy_count",
        callbacks=[_callback],
        unit="{policies}",
        description=(
            "Number of policy rules + grouping rules currently held in the "
            "worker's in-memory Casbin enforcer. Observed at scrape time. "
            "See contracts/metrics.md."
        ),
    )
    return _POLICY_COUNT_GAUGE
