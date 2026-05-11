"""Unit tests for Phase 2 — OTel logs/metrics wiring.

Covers:
    * ``ObservabilitySettings`` exposes the new opt-in fields.
    * ``enable_otel_log_export`` produces ``LogRecord`` emissions that carry
      the loguru ``request_id`` extra and the loguru level.
    * The OTel sink suppresses ``opentelemetry.*`` records to break the
      export -> log -> export feedback loop.
    * ``configure_observability`` remains a no-op while the master switch
      is off (default for unit tests).
"""

from __future__ import annotations

import pytest
from loguru import logger
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from apps.core.logging import enable_otel_log_export
from apps.core.observability import configure_observability
from apps.settings import ObservabilitySettings, app_settings


@pytest.mark.unit
def test_observability_settings_default_signal_endpoints_fall_back() -> None:
    settings = ObservabilitySettings()
    assert settings.otlp_logs_endpoint is None
    assert settings.otlp_metrics_endpoint is None
    assert settings.logs_export_enabled is True
    assert settings.metrics_export_enabled is True
    assert settings.metric_export_interval_millis == 30_000


@pytest.mark.unit
def test_observability_settings_signal_endpoints_override() -> None:
    settings = ObservabilitySettings(
        otlp_logs_endpoint="http://collector:4317",
        otlp_metrics_endpoint="http://collector:4318",
        logs_export_enabled=False,
        metric_export_interval_millis=5_000,
    )

    assert settings.otlp_logs_endpoint == "http://collector:4317"
    assert settings.otlp_metrics_endpoint == "http://collector:4318"
    assert settings.logs_export_enabled is False
    assert settings.metric_export_interval_millis == 5_000


@pytest.fixture
def in_memory_log_provider():
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


def _records(exporter: InMemoryLogRecordExporter) -> list:
    """Unwrap the ``ReadableLogRecord`` envelopes into raw ``LogRecord``s."""
    return [item.log_record for item in exporter.get_finished_logs()]


@pytest.mark.unit
def test_otel_sink_emits_log_records_with_request_id(in_memory_log_provider) -> None:
    provider, exporter = in_memory_log_provider

    sink_id = enable_otel_log_export(provider, level="DEBUG")
    try:
        with logger.contextualize(request_id="rid-abc-123"):
            logger.info("hello otel")
    finally:
        logger.remove(sink_id)

    finished = _records(exporter)
    assert len(finished) == 1
    record = finished[0]
    assert record.body == "hello otel"
    assert record.severity_number == SeverityNumber.INFO
    assert record.severity_text == "INFO"
    assert record.attributes["request_id"] == "rid-abc-123"
    assert record.attributes["code.namespace"] == __name__


@pytest.mark.unit
def test_otel_sink_omits_request_id_attribute_when_unbound(in_memory_log_provider) -> None:
    """The default ``"-"`` sentinel must not pollute exported attributes."""
    provider, exporter = in_memory_log_provider

    sink_id = enable_otel_log_export(provider, level="DEBUG")
    try:
        logger.info("no context")
    finally:
        logger.remove(sink_id)

    finished = _records(exporter)
    assert len(finished) == 1
    assert "request_id" not in (finished[0].attributes or {})


@pytest.mark.unit
def test_otel_sink_skips_opentelemetry_namespace_records(in_memory_log_provider) -> None:
    """Logs originating from the OTel SDK itself must be dropped to avoid loops."""
    provider, exporter = in_memory_log_provider

    sink_id = enable_otel_log_export(provider, level="DEBUG")
    try:
        forged = logger.patch(lambda r: r.update({"name": "opentelemetry.sdk._logs"}))
        forged.info("would loop")
    finally:
        logger.remove(sink_id)

    assert _records(exporter) == []


@pytest.mark.unit
def test_otel_sink_severity_mapping(in_memory_log_provider) -> None:
    provider, exporter = in_memory_log_provider

    sink_id = enable_otel_log_export(provider, level="TRACE")
    try:
        logger.warning("warn line")
        logger.error("error line")
    finally:
        logger.remove(sink_id)

    severities = [(r.severity_text, r.severity_number) for r in _records(exporter)]
    assert ("WARNING", SeverityNumber.WARN) in severities
    assert ("ERROR", SeverityNumber.ERROR) in severities


@pytest.mark.unit
def test_configure_observability_is_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(app_settings.observability, "enabled", False)

    class _StubApp:
        pass

    configure_observability(_StubApp())  # type: ignore[arg-type]
