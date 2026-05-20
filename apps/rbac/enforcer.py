"""Casbin enforcer factory."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import casbin
import redis.asyncio as aioredis
from casbin_async_sqlalchemy_adapter import Adapter
from casbin_redis_watcher import WatcherOptions, new_watcher
from loguru import logger
from opentelemetry import metrics
from redis import exceptions as redis_exceptions

from apps.rbac.constants import (
    RBAC_ENFORCER_HEARTBEAT_INTERVAL_SECONDS,
    RBAC_ENFORCER_WATCHER_PING_TIMEOUT_SECONDS,
)
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
            before scaling beyond a single uvicorn worker. The factory PINGs
            the URL first so a misconfigured watcher fails fast at boot
            instead of silently degrading to stale policy at runtime.

    Returns:
        Loaded :class:`casbin.AsyncEnforcer` ready for ``enforce`` calls.

    Raises:
        RuntimeError: When ``watcher_redis_url`` is set but the URL is
            unreachable within ``RBAC_ENFORCER_WATCHER_PING_TIMEOUT_SECONDS``.
    """
    adapter = Adapter(database_uri)
    await adapter.create_table()
    enforcer = casbin.AsyncEnforcer(str(RBAC_MODEL_PATH), adapter)
    await enforcer.load_policy()

    if watcher_redis_url:
        await _ping_watcher_url(
            watcher_redis_url,
            timeout_seconds=RBAC_ENFORCER_WATCHER_PING_TIMEOUT_SECONDS,
        )
        _attach_redis_watcher(enforcer, watcher_redis_url)

    return enforcer


async def _ping_watcher_url(redis_url: str, *, timeout_seconds: float) -> None:
    """PING the watcher Redis URL; raise ``RuntimeError`` if unreachable.

    Boot-time check that catches the most common watcher misconfiguration
    (typo, wrong host, missing TLS) before the worker starts serving
    traffic on stale policy. Times out at ``timeout_seconds`` so a
    completely unreachable host can't hang the lifespan indefinitely.
    """
    client = aioredis.from_url(
        redis_url,
        socket_timeout=timeout_seconds,
        socket_connect_timeout=timeout_seconds,
    )
    try:
        await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
    except (redis_exceptions.RedisError, OSError, TimeoutError) as exc:
        msg = (
            f"RBAC watcher PING failed for {redis_url!r}: {exc!r}. "
            "Multi-worker policy coherence depends on this connection; refusing to boot."
        )
        raise RuntimeError(msg) from exc
    finally:
        await client.aclose()


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


# Module-level slots for heartbeat-related counters so the SDK does not
# garbage-collect them after registration. Re-registration replaces the
# slots; the SDK de-dupes instruments by name within a meter scope.
_HEARTBEAT_TOTAL_COUNTER: Any = None
_HEARTBEAT_FAILURE_COUNTER: Any = None


def register_heartbeat_counters(
    *,
    meter: metrics.Meter | None = None,
) -> tuple[Any, Any]:
    """Register OTel counters for heartbeat success / failure.

    The pair is observed by :func:`rbac_enforcer_heartbeat` on every tick
    (success increments ``rbac_enforcer_heartbeat_total``; an exception
    during ``load_policy`` increments ``rbac_enforcer_heartbeat_failures_total``
    so dashboards can alert on watcher silent-failure mode).

    Args:
        meter: Optional injected meter; defaults to the global meter for
            ``apps.rbac``. The parameter exists for tests that install an
            isolated ``MeterProvider`` + ``InMemoryMetricReader``.

    Returns:
        ``(heartbeat_total, heartbeat_failures)`` counters.
    """
    global _HEARTBEAT_TOTAL_COUNTER, _HEARTBEAT_FAILURE_COUNTER  # noqa: PLW0603

    target_meter = meter if meter is not None else metrics.get_meter("apps.rbac")

    _HEARTBEAT_TOTAL_COUNTER = target_meter.create_counter(
        name="rbac_enforcer_heartbeat_total",
        unit="{loads}",
        description=(
            "Successful periodic ``enforcer.load_policy()`` fallbacks. Each "
            "tick guarantees per-worker policy convergence even when the "
            "Redis pub/sub watcher silently drops events."
        ),
    )
    _HEARTBEAT_FAILURE_COUNTER = target_meter.create_counter(
        name="rbac_enforcer_heartbeat_failures_total",
        unit="{loads}",
        description=(
            "Failed heartbeat ``load_policy()`` attempts. A sustained "
            "non-zero rate indicates the policy DB is unreachable; alert "
            "on it because the watcher path may also be broken."
        ),
    )
    return _HEARTBEAT_TOTAL_COUNTER, _HEARTBEAT_FAILURE_COUNTER


async def rbac_enforcer_heartbeat(
    enforcer: casbin.AsyncEnforcer,
    *,
    interval_seconds: int = RBAC_ENFORCER_HEARTBEAT_INTERVAL_SECONDS,
    success_counter: Any = None,
    failure_counter: Any = None,
) -> None:
    """Periodically reload policies as a safety net for the Redis watcher.

    Even with a healthy ``casbin_redis_watcher``, pub/sub messages can be
    lost during a Redis restart or a transient network partition. This
    coroutine wakes every ``interval_seconds`` and calls
    ``enforcer.load_policy()`` so every worker re-converges to the
    canonical state stored in ``casbin_rule`` — no matter what the
    watcher missed.

    Runs forever; cancel the task to stop. Exceptions during a single
    tick are logged and counted but do NOT stop the loop, because the
    next interval should be tried regardless.

    Args:
        enforcer: The Casbin enforcer to refresh.
        interval_seconds: Tick cadence. Defaults to the module constant.
        success_counter: Optional OTel counter incremented on each
            successful load_policy.
        failure_counter: Optional OTel counter incremented when load_policy
            raises (the loop logs and sleeps to the next interval).
    """
    logger.info(
        "rbac_enforcer_heartbeat - started; interval={interval}s",
        interval=interval_seconds,
    )
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await enforcer.load_policy()
            if success_counter is not None:
                success_counter.add(1)
            logger.debug("rbac_enforcer_heartbeat - reloaded policies")
        except asyncio.CancelledError:
            logger.info("rbac_enforcer_heartbeat - cancelled; exiting")
            raise
        except Exception as exc:
            if failure_counter is not None:
                failure_counter.add(1)
            logger.warning(
                "rbac_enforcer_heartbeat - load_policy failed; will retry next tick: {!r}",
                exc,
            )


def start_rbac_enforcer_heartbeat_task(
    enforcer: casbin.AsyncEnforcer,
    *,
    interval_seconds: int = RBAC_ENFORCER_HEARTBEAT_INTERVAL_SECONDS,
    success_counter: Any = None,
    failure_counter: Any = None,
) -> asyncio.Task[None]:
    """Spawn :func:`rbac_enforcer_heartbeat` as a managed asyncio task."""
    coro = rbac_enforcer_heartbeat(
        enforcer,
        interval_seconds=interval_seconds,
        success_counter=success_counter,
        failure_counter=failure_counter,
    )
    return asyncio.create_task(coro, name="rbac_enforcer_heartbeat")


async def stop_rbac_enforcer_heartbeat_task(task: asyncio.Task[None]) -> None:
    """Cancel the heartbeat task and await its exit; safe on already-done tasks."""
    if task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
