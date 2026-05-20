"""Unit tests for CRITICAL-1: RBAC enforcer heartbeat + watcher PING.

The Casbin pub/sub watcher silently drops events when Redis pub/sub is
partitioned or restarted between subscribe + publish. The heartbeat task
guarantees every worker re-loads the policy table on a bounded cadence
so that a missed event is corrected within
``RBAC_ENFORCER_HEARTBEAT_INTERVAL_SECONDS``. The boot-time PING gives
the operator a fail-fast signal if the watcher URL is unreachable.

These tests cover the new behaviours without spinning up a real Casbin
enforcer or a real Redis — both are mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from apps.rbac.enforcer import (
    _ping_watcher_url,
    rbac_enforcer_heartbeat,
    register_heartbeat_counters,
    start_rbac_enforcer_heartbeat_task,
    stop_rbac_enforcer_heartbeat_task,
)


def _counter_value(reader: InMemoryMetricReader, name: str) -> int | None:
    metrics_data = reader.get_metrics_data()
    if metrics_data is None:
        return None
    latest: int | None = None
    for resource_metric in metrics_data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    latest = int(point.value)
    return latest


@pytest.mark.asyncio
async def test_heartbeat_calls_load_policy_each_tick_and_increments_counter() -> None:
    """One tick → one load_policy call → success counter == 1."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.rbac")
    success, failures = register_heartbeat_counters(meter=meter)

    enforcer = MagicMock()
    enforcer.load_policy = AsyncMock(return_value=None)

    # interval=0 means asyncio.sleep(0) → cooperative yield; we cancel
    # after letting the loop run a couple of ticks.
    task = asyncio.create_task(
        rbac_enforcer_heartbeat(
            enforcer,
            interval_seconds=0,
            success_counter=success,
            failure_counter=failures,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert enforcer.load_policy.await_count >= 1
    success_value = _counter_value(reader, "rbac_enforcer_heartbeat_total")
    assert success_value is not None and success_value >= 1
    # No failures on the happy path.
    assert _counter_value(reader, "rbac_enforcer_heartbeat_failures_total") in (None, 0)


@pytest.mark.asyncio
async def test_heartbeat_records_failure_and_continues_on_exception() -> None:
    """A single failed load_policy increments failures_total but does NOT
    stop the loop — the next tick must still run."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.rbac")
    success, failures = register_heartbeat_counters(meter=meter)

    enforcer = MagicMock()
    # Fail twice, then succeed forever.
    enforcer.load_policy = AsyncMock(
        side_effect=[RuntimeError("db unreachable"), RuntimeError("still unreachable"), None, None]
    )

    task = asyncio.create_task(
        rbac_enforcer_heartbeat(
            enforcer,
            interval_seconds=0,
            success_counter=success,
            failure_counter=failures,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    failure_value = _counter_value(reader, "rbac_enforcer_heartbeat_failures_total")
    assert failure_value is not None and failure_value >= 2
    # Loop kept going after failure — at least one successful tick observed.
    success_value = _counter_value(reader, "rbac_enforcer_heartbeat_total")
    assert success_value is not None and success_value >= 1


@pytest.mark.asyncio
async def test_start_and_stop_helpers_round_trip_cleanly() -> None:
    """Start a heartbeat task, stop it, ensure no warnings or leaked exceptions."""
    enforcer = MagicMock()
    enforcer.load_policy = AsyncMock(return_value=None)

    task = start_rbac_enforcer_heartbeat_task(enforcer, interval_seconds=0)
    await asyncio.sleep(0.01)
    await stop_rbac_enforcer_heartbeat_task(task)
    assert task.done()
    # Cancelling an already-done task is a no-op, not a raise.
    await stop_rbac_enforcer_heartbeat_task(task)


@pytest.mark.asyncio
async def test_ping_watcher_url_raises_runtime_error_on_unreachable_host() -> None:
    """A bogus host inside the PING timeout window must yield RuntimeError
    so the lifespan fails fast instead of silently degrading."""
    with patch("apps.rbac.enforcer.aioredis.from_url") as from_url:
        client = MagicMock()
        client.ping = AsyncMock(side_effect=OSError("ECONNREFUSED"))
        client.aclose = AsyncMock()
        from_url.return_value = client

        with pytest.raises(RuntimeError, match="RBAC watcher PING failed"):
            await _ping_watcher_url("redis://bogus-host:6379/0", timeout_seconds=0.1)
        # Resource cleanup happens via the finally block.
        client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_ping_watcher_url_success_path_returns_silently() -> None:
    with patch("apps.rbac.enforcer.aioredis.from_url") as from_url:
        client = MagicMock()
        client.ping = AsyncMock(return_value=True)
        client.aclose = AsyncMock()
        from_url.return_value = client

        # No exception expected.
        await _ping_watcher_url("redis://ok-host:6379/0", timeout_seconds=0.5)
        client.aclose.assert_awaited_once()
