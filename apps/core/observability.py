"""OpenTelemetry tracing wiring.

Configures a global :class:`TracerProvider` and registers the FastAPI,
SQLAlchemy, and Redis instrumentors so spans / trace IDs flow through to
the configured OTLP collector. Loguru records pick up the active
``trace_id`` / ``span_id`` via ``apps.core.logging.record_formatter``.

When ``OBSERVABILITY_ENABLED`` is ``false`` (the default) this module is
a no-op: dev and unit-test runs do not need an OTel collector. When
``OBSERVABILITY_OTLP_ENDPOINT`` is unset the tracer provider is still
installed (so log lines carry trace IDs) but no exporter is attached.

Idempotent — safe to call twice (e.g. on test reloads).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from apps.settings import app_settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

_CONFIGURED = False


def configure_observability(
    app: FastAPI,
    *,
    writer_engine: AsyncEngine | None = None,
    reader_engine: AsyncEngine | None = None,
) -> None:
    """Configure OTel tracer provider + instrument FastAPI / SQLAlchemy / Redis.

    Args:
        app: FastAPI application — used by ``FastAPIInstrumentor`` to wrap
            request handling in spans.
        writer_engine: Primary (writer) async engine; ``SQLAlchemyInstrumentor``
            attaches to its ``sync_engine``.
        reader_engine: Optional read-replica engine; instrumented when
            distinct from ``writer_engine``.
    """
    global _CONFIGURED  # noqa: PLW0603 — module-scoped idempotency guard
    settings = app_settings.observability

    if not settings.enabled:
        logger.info("observability - disabled (OBSERVABILITY_ENABLED=false)")
        return
    if _CONFIGURED:
        logger.debug("observability - already configured; skipping re-init")
        return

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": app_settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otlp_endpoint:
        _attach_otlp_exporter(provider, settings.otlp_endpoint)

    trace.set_tracer_provider(provider)

    _instrument_fastapi(app)

    # De-duplicate by URL: in single-DB deployments the reader and writer
    # are distinct engine objects bound to the same URL, and instrumenting
    # the same connection twice doubles every span.
    seen_urls: set[str] = set()
    for engine in (writer_engine, reader_engine):
        if engine is None:
            continue
        url = str(engine.url)
        if url in seen_urls:
            continue
        _instrument_sqlalchemy(engine)
        seen_urls.add(url)

    if app_settings.redis.enabled:
        _instrument_redis()

    _CONFIGURED = True
    logger.info(
        "observability - configured service={} otlp={}",
        settings.service_name,
        settings.otlp_endpoint or "<none>",
    )


def _attach_otlp_exporter(provider: TracerProvider, endpoint: str) -> None:
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))


def _instrument_fastapi(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app)


def _instrument_sqlalchemy(engine: AsyncEngine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def _instrument_redis() -> None:
    RedisInstrumentor().instrument()
