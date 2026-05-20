"""Lazy SQLAlchemy async engine factory.

Engines are NOT instantiated at import time — `engine_factory()` builds them
on first call and caches via `lru_cache`. This makes the module safe to import
in test environments that swap out settings or run without a database.

Read/write split: when ``DB_READER_HOST`` is set in the environment, the
:class:`DatabaseSettings` validator populates ``reader_uri`` and the reader
engine connects to that replica. Otherwise the reader engine reuses the
writer URI (single-DB deployment); ``RoutingSession`` still caches reader
and writer as distinct engine instances so the routing logic itself works
the same in both topologies.
"""

import enum
import functools
from typing import Any

from loguru import logger
from opentelemetry import metrics
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.settings import app_settings


class SQLAlchemyEngineTypes(enum.StrEnum):
    """SQLAlchemy engine types."""

    READER = "reader"
    WRITER = "writer"


# Module-level slot holding the registered pool-stat gauges so the OTel
# SDK does not garbage-collect them after registration. Re-registration
# replaces the slot; the SDK de-dupes instruments by name within a meter.
_POOL_STAT_GAUGES: tuple[Any, Any, Any] | None = None


def _build_engine(database_uri: URL, *, engine_type: SQLAlchemyEngineTypes) -> AsyncEngine:
    """Construct an AsyncEngine for ``database_uri`` using the configured pool sizing.

    Also emits the effective pool configuration at INFO so prod incident
    triage can confirm the deployed sizing without re-reading env vars
    out of the container.
    """
    db = app_settings.db
    engine = create_async_engine(
        database_uri,
        pool_pre_ping=db.pool_pre_ping,
        pool_recycle=db.pool_recycle,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
    )
    logger.info(
        "engine_factory - {engine_type} pool: size={pool_size} max_overflow={max_overflow} "
        "timeout={pool_timeout}s recycle={pool_recycle}s pre_ping={pool_pre_ping}",
        engine_type=engine_type.value,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
        pool_recycle=db.pool_recycle,
        pool_pre_ping=db.pool_pre_ping,
    )
    return engine


@functools.cache
def engine_factory(
    engine_type: SQLAlchemyEngineTypes = SQLAlchemyEngineTypes.READER,
) -> AsyncEngine:
    """Return the cached AsyncEngine for the given engine type, building it lazily."""
    db = app_settings.db
    return _build_engine(db.database_uri, engine_type=engine_type)


def register_db_pool_gauges(
    writer_engine: AsyncEngine,
    reader_engine: AsyncEngine | None = None,
    *,
    meter: metrics.Meter | None = None,
) -> tuple[Any, Any, Any]:
    """Register OTel observable gauges for the SQLAlchemy connection pool.

    Three gauges are exported per registration, each carrying an
    ``engine_type`` attribute (``writer`` or ``reader``) so dashboards
    can split by role:

    * ``db_pool_checkedout`` — connections currently lent to callers.
      Sustained values at or above ``pool_size + max_overflow`` indicate
      pool starvation; ``pool_timeout`` waits become user-visible latency.
    * ``db_pool_size`` — configured base pool size.
    * ``db_pool_overflow`` — overflow slots currently in use (additional
      connections beyond ``pool_size``).

    The reader gauge is registered only when its engine is distinct from
    the writer's, mirroring the de-duplication in
    :func:`apps.core.observability.configure_observability`.

    Args:
        writer_engine: Primary engine; always observed.
        reader_engine: Optional read-replica; observed only when distinct.
        meter: Optional injected meter; defaults to the global
            ``apps.core.database`` meter. The parameter exists for tests
            that install an isolated ``MeterProvider``.

    Returns:
        ``(checkedout, size, overflow)`` observable gauge instruments.
    """
    global _POOL_STAT_GAUGES  # noqa: PLW0603 — module-scoped slot

    target_meter = meter if meter is not None else metrics.get_meter("apps.core.database")

    targets: list[tuple[str, AsyncEngine]] = [(SQLAlchemyEngineTypes.WRITER.value, writer_engine)]
    seen_urls: set[str] = {str(writer_engine.url)}
    if reader_engine is not None and str(reader_engine.url) not in seen_urls:
        targets.append((SQLAlchemyEngineTypes.READER.value, reader_engine))

    def _observe(extractor):
        def _callback(_options: Any):
            observations = []
            for engine_type_value, engine in targets:
                try:
                    value = extractor(engine)
                except Exception as exc:
                    logger.warning(
                        "register_db_pool_gauges - extractor failed for {et}: {!r}",
                        exc,
                        et=engine_type_value,
                    )
                    continue
                observations.append(metrics.Observation(value, attributes={"engine_type": engine_type_value}))
            return observations

        return _callback

    checkedout = target_meter.create_observable_up_down_counter(
        name="db_pool_checkedout",
        callbacks=[_observe(lambda e: e.pool.checkedout())],
        unit="{connections}",
        description=(
            "SQLAlchemy connections currently checked out from the async pool. "
            "Sustained values at or above (pool_size + max_overflow) indicate "
            "pool starvation; pool_timeout waits become user-visible latency."
        ),
    )
    size = target_meter.create_observable_gauge(
        name="db_pool_size",
        callbacks=[_observe(lambda e: e.pool.size())],
        unit="{connections}",
        description="Configured base pool size for the SQLAlchemy async pool.",
    )
    overflow = target_meter.create_observable_up_down_counter(
        name="db_pool_overflow",
        callbacks=[_observe(lambda e: e.pool.overflow())],
        unit="{connections}",
        description="Overflow connections in use beyond the base pool_size.",
    )

    _POOL_STAT_GAUGES = (checkedout, size, overflow)
    return _POOL_STAT_GAUGES
