import logging
import sys
from typing import Any, Final

from loguru import logger
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.trace import INVALID_SPAN, INVALID_SPAN_CONTEXT, get_current_span

_LOGURU_TO_OTEL_SEVERITY: Final[dict[str, SeverityNumber]] = {
    "TRACE": SeverityNumber.TRACE,
    "DEBUG": SeverityNumber.DEBUG,
    "INFO": SeverityNumber.INFO,
    "SUCCESS": SeverityNumber.INFO,
    "WARNING": SeverityNumber.WARN,
    "ERROR": SeverityNumber.ERROR,
    "CRITICAL": SeverityNumber.FATAL,
}

_OTEL_LOGGER_NAME: Final[str] = "fastapi-base.app"


class InterceptHandler(logging.Handler):
    """Intercept handler for logging."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        """Propagate logs to loguru."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def record_formatter(record: dict[str, Any]) -> str:  # pragma: no cover
    """
    Formats the record.

    This function formats message
    by adding extra trace information to the record.

    :param record: record information.
    :return: format string.
    """
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        "| <level>{level: <8}</level> "
        "| <yellow>request_id={extra[request_id]}</yellow> "
        "| <magenta>trace_id={extra[trace_id]}</magenta> "
        "| <blue>span_id={extra[span_id]}</blue> "
        "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "- <level>{message}</level>\n"
    )

    record["extra"].setdefault("request_id", "-")
    span = get_current_span()
    record["extra"]["span_id"] = 0
    record["extra"]["trace_id"] = 0
    if span != INVALID_SPAN:
        span_context = span.get_span_context()
        if span_context != INVALID_SPAN_CONTEXT:
            record["extra"]["span_id"] = format(span_context.span_id, "016x")
            record["extra"]["trace_id"] = format(span_context.trace_id, "032x")

    if record["exception"]:
        log_format = f"{log_format}{{'{{'}}exception{{'}}'}}"

    return log_format


def configure_logging() -> None:  # pragma: no cover
    """Configures logging."""
    intercept_handler = InterceptHandler()

    logging.basicConfig(handlers=[intercept_handler], level=logging.NOTSET)

    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("uvicorn."):
            logging.getLogger(logger_name).handlers = []

    # change handler for default uvicorn logger
    logging.getLogger("uvicorn").handlers = [intercept_handler]
    logging.getLogger("uvicorn.access").handlers = [intercept_handler]

    # set logs output, level and format
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format=record_formatter,  # type: ignore
    )


def enable_otel_log_export(provider: LoggerProvider, *, level: str = "INFO") -> int:
    """Register a loguru sink that emits OTel ``LogRecord``s.

    Args:
        provider: The :class:`opentelemetry.sdk._logs.LoggerProvider` returned
            by :func:`apps.core.observability._configure_logger_provider`.
        level: Loguru level threshold for the sink.

    Returns:
        The loguru sink ID — pass it to ``logger.remove(sink_id)`` to detach
        (used by tests; production keeps it for the process lifetime).
    """
    otel_logger = provider.get_logger(_OTEL_LOGGER_NAME)

    def _sink(message: Any) -> None:
        record = message.record
        # Skip OTel SDK's own logs to avoid an export -> log -> export
        # feedback loop when the collector is unreachable.
        if record["name"].startswith("opentelemetry"):
            return

        attributes: dict[str, Any] = {
            "code.namespace": record["name"],
            "code.function": record["function"],
            "code.lineno": record["line"],
        }
        request_id = record["extra"].get("request_id")
        if request_id and request_id != "-":
            attributes["request_id"] = request_id

        severity_number = _LOGURU_TO_OTEL_SEVERITY.get(
            record["level"].name,
            SeverityNumber.UNSPECIFIED,
        )

        otel_logger.emit(
            severity_number=severity_number,
            severity_text=record["level"].name,
            body=record["message"],
            timestamp=int(record["time"].timestamp() * 1_000_000_000),
            attributes=attributes,
        )

    return logger.add(_sink, level=level, format="{message}")
