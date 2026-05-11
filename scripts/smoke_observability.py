"""End-to-end smoke test for the local observability stack.

Sends one span, one counter increment, and one log line via OTLP gRPC to
``localhost:4317`` and force-flushes the providers before exiting so the
collector -> {Tempo, Prometheus, Loki} pipeline can be queried right after
the script returns.

Run with:
    uv run python scripts/smoke_observability.py

Then query backends:
    curl -sG http://localhost:3100/loki/api/v1/query --data-urlencode 'query={service_name="smoke-test"}'
    curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq '.data[]' | grep smoke
    curl -s 'http://localhost:3200/api/search?tags=service.name%3Dsmoke-test'
"""

from __future__ import annotations

import time
import uuid

from opentelemetry import metrics, trace
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ENDPOINT = "localhost:4317"
SERVICE_NAME = "smoke-test"


def main() -> None:
    resource = Resource.create({"service.name": SERVICE_NAME})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT, insecure=True)))
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=ENDPOINT, insecure=True)))
    set_logger_provider(logger_provider)

    meter_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=ENDPOINT, insecure=True),
        export_interval_millis=1000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[meter_reader])
    metrics.set_meter_provider(meter_provider)

    correlation_id = uuid.uuid4().hex
    print(f"smoke correlation_id={correlation_id}")

    tracer = trace.get_tracer("smoke")
    with tracer.start_as_current_span("smoke-span") as span:
        span.set_attribute("smoke.correlation_id", correlation_id)
        ctx = span.get_span_context()
        print(f"trace_id={format(ctx.trace_id, '032x')} span_id={format(ctx.span_id, '016x')}")

        meter = metrics.get_meter("smoke")
        counter = meter.create_counter("smoke_test_events_total")
        counter.add(1, {"correlation_id": correlation_id})

        otel_logger = logger_provider.get_logger("smoke")
        otel_logger.emit(
            severity_number=SeverityNumber.INFO,
            severity_text="INFO",
            body=f"smoke log correlation_id={correlation_id}",
            timestamp=int(time.time() * 1_000_000_000),
            attributes={"correlation_id": correlation_id},
        )

    tracer_provider.shutdown()
    logger_provider.shutdown()
    meter_provider.shutdown()
    print("flushed; sleep 3s for batch processors to drain")
    time.sleep(3)


if __name__ == "__main__":
    main()
