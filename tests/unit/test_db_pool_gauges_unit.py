"""Unit tests for MED-1: SQLAlchemy connection-pool OTel gauges.

``register_db_pool_gauges`` exports three observable instruments
(``db_pool_checkedout`` / ``db_pool_size`` / ``db_pool_overflow``) each
attributed by ``engine_type``. The reader gauge is registered only when
its engine URL differs from the writer's so single-DB deployments don't
double-count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from apps.core.database.engine import register_db_pool_gauges


def _fake_engine(url: str, *, checkedout: int = 0, size: int = 0, overflow: int = 0) -> MagicMock:
    engine = MagicMock(name=f"Engine({url})")
    engine.url = url
    engine.pool = MagicMock()
    engine.pool.checkedout = MagicMock(return_value=checkedout)
    engine.pool.size = MagicMock(return_value=size)
    engine.pool.overflow = MagicMock(return_value=overflow)
    return engine


def _gather_metrics(reader: InMemoryMetricReader) -> dict[str, list[tuple[dict, int]]]:
    """Return ``{metric_name: [(attributes, value), ...]}`` from one collect."""
    out: dict[str, list[tuple[dict, int]]] = {}
    data = reader.get_metrics_data()
    if data is None:
        return out
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points = []
                for point in metric.data.data_points:
                    attrs = dict(point.attributes) if point.attributes else {}
                    points.append((attrs, int(point.value)))
                out[metric.name] = points
    return out


def test_three_gauges_registered_writer_only() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.core.database")

    writer = _fake_engine("postgresql://writer/db", checkedout=3, size=10, overflow=1)
    instruments = register_db_pool_gauges(writer, None, meter=meter)
    assert len(instruments) == 3

    metrics = _gather_metrics(reader)
    assert "db_pool_checkedout" in metrics
    assert "db_pool_size" in metrics
    assert "db_pool_overflow" in metrics

    # Exactly one observation per metric (only the writer).
    for name in ("db_pool_checkedout", "db_pool_size", "db_pool_overflow"):
        assert len(metrics[name]) == 1
        attrs, _value = metrics[name][0]
        assert attrs == {"engine_type": "writer"}

    assert metrics["db_pool_checkedout"][0][1] == 3
    assert metrics["db_pool_size"][0][1] == 10
    assert metrics["db_pool_overflow"][0][1] == 1


def test_reader_observed_when_url_differs_from_writer() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.core.database")

    writer = _fake_engine("postgresql://writer/db", checkedout=5)
    replica = _fake_engine("postgresql://replica/db", checkedout=2)
    register_db_pool_gauges(writer, replica, meter=meter)

    metrics = _gather_metrics(reader)
    checkedout = {tuple(sorted(attrs.items())): v for attrs, v in metrics["db_pool_checkedout"]}
    assert checkedout == {
        (("engine_type", "reader"),): 2,
        (("engine_type", "writer"),): 5,
    }


def test_reader_skipped_when_url_matches_writer() -> None:
    """Single-DB deployments pass reader_engine==writer_engine. The gauge
    must avoid double-counting by emitting only the writer observation."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.core.database")

    writer = _fake_engine("postgresql://same/db", checkedout=7)
    aliased_reader = _fake_engine("postgresql://same/db", checkedout=7)
    register_db_pool_gauges(writer, aliased_reader, meter=meter)

    metrics = _gather_metrics(reader)
    # Only one observation per metric, attributed to writer.
    for name in ("db_pool_checkedout", "db_pool_size", "db_pool_overflow"):
        assert len(metrics[name]) == 1
        assert metrics[name][0][0] == {"engine_type": "writer"}


def test_extractor_exception_is_skipped_not_propagated() -> None:
    """A pool helper that raises (e.g. engine disposed mid-scrape) must
    not blow up the gauge callback; the observation is simply omitted."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("apps.core.database")

    writer = _fake_engine("postgresql://writer/db", checkedout=3)
    writer.pool.checkedout = MagicMock(side_effect=RuntimeError("pool disposed"))
    register_db_pool_gauges(writer, None, meter=meter)

    metrics = _gather_metrics(reader)
    # checkedout omitted; size and overflow still produced.
    assert "db_pool_size" in metrics
    assert "db_pool_overflow" in metrics
    assert metrics.get("db_pool_checkedout", []) == []
