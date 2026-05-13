"""Real-DB integration test for the RBAC policy-count gauge (F-SCALE-1, SC-003).

Asserts that ``register_policy_count_gauge(enforcer)`` registers an
observable up-down counter named ``rbac_enforcer_policy_count`` whose
callback reads ``len(enforcer.get_policy()) + len(enforcer.get_grouping_policy())``
at scrape time. Adding policies between two scrapes increases the
reported value.

The test injects its own ``MeterProvider`` + ``InMemoryMetricReader`` to
avoid colliding with OTel's set-once global meter provider.
"""

from __future__ import annotations

import pytest_asyncio
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from apps.rbac.enforcer import enforcer_factory, register_policy_count_gauge
from apps.settings import app_settings


@pytest_asyncio.fixture
async def enforcer():
    url = app_settings.db.database_uri.render_as_string(hide_password=False)
    return await enforcer_factory(url)


def _read_gauge_value(reader: InMemoryMetricReader, name: str) -> int | None:
    """Force a collection and return the latest value for ``name``, or None."""
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


async def test_policy_count_gauge_reflects_enforcer_size(enforcer) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.rbac")

    # Register the gauge against the isolated meter. Hold the returned
    # instrument so it isn't garbage-collected before the next scrape.
    gauge = register_policy_count_gauge(enforcer, meter=meter)
    assert gauge is not None

    n0_total = len(enforcer.get_policy()) + len(enforcer.get_grouping_policy())
    n0 = _read_gauge_value(reader, "rbac_enforcer_policy_count")
    assert n0 == n0_total, f"initial gauge {n0} != enforcer total {n0_total}"

    # Add 3 policies via the enforcer directly; the callback should pick
    # them up at the next scrape.
    await enforcer.add_policy("role:gauge_test_1", "res_gauge", "read")
    await enforcer.add_policy("role:gauge_test_2", "res_gauge", "edit")
    await enforcer.add_policy("role:gauge_test_3", "res_gauge", "delete")

    try:
        n1_total = len(enforcer.get_policy()) + len(enforcer.get_grouping_policy())
        n1 = _read_gauge_value(reader, "rbac_enforcer_policy_count")
        assert n1 == n1_total
        assert n1 == n0_total + 3
    finally:
        # Cleanup so the shared DB stays tidy.
        await enforcer.remove_policy("role:gauge_test_1", "res_gauge", "read")
        await enforcer.remove_policy("role:gauge_test_2", "res_gauge", "edit")
        await enforcer.remove_policy("role:gauge_test_3", "res_gauge", "delete")
