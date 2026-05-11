"""OpenTelemetry tracing / logging / metrics wiring.

Configures global :class:`TracerProvider`, :class:`LoggerProvider`, and
:class:`MeterProvider`, then registers the FastAPI, SQLAlchemy, and Redis
instrumentors so spans / trace IDs flow through to the configured OTLP
collector. Loguru records pick up the active ``trace_id`` / ``span_id``
via :func:`apps.core.logging.record_formatter` and are also forwarded to
the OTLP log pipeline by :func:`apps.core.logging.enable_otel_log_export`.

When ``OBSERVABILITY_ENABLED`` is ``false`` (the default) this module is
a no-op: dev and unit-test runs do not need an OTel collector. When
``OBSERVABILITY_OTLP_ENDPOINT`` is unset the tracer provider is still
installed (so log lines carry trace IDs) but no exporter is attached.

Idempotent — safe to call twice (e.g. on test reloads).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from apps.core.logging import enable_otel_log_export
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

    _configure_tracer_provider(resource, settings.otlp_endpoint)

    logs_endpoint = settings.otlp_logs_endpoint or settings.otlp_endpoint
    if settings.logs_export_enabled and logs_endpoint:
        provider = _configure_logger_provider(resource, logs_endpoint)
        enable_otel_log_export(provider)

    metrics_endpoint = settings.otlp_metrics_endpoint or settings.otlp_endpoint
    if settings.metrics_export_enabled and metrics_endpoint:
        _configure_meter_provider(
            resource,
            metrics_endpoint,
            interval_millis=settings.metric_export_interval_millis,
        )

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
        "observability - configured service={} traces={} logs={} metrics={}",
        settings.service_name,
        settings.otlp_endpoint or "<none>",
        logs_endpoint or "<disabled>",
        metrics_endpoint or "<disabled>",
    )


def _configure_tracer_provider(resource: Resource, endpoint: str | None) -> TracerProvider:
    provider = TracerProvider(resource=resource)
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    return provider


def _configure_logger_provider(resource: Resource, endpoint: str) -> LoggerProvider:
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint)))
    set_logger_provider(provider)
    return provider


def _configure_meter_provider(
    resource: Resource,
    endpoint: str,
    *,
    interval_millis: int,
) -> MeterProvider:
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint),
        export_interval_millis=interval_millis,
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def _instrument_fastapi(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app)


def _instrument_sqlalchemy(engine: AsyncEngine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def _instrument_redis() -> None:
    RedisInstrumentor().instrument()
