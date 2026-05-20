from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.core.schemas.response import JsonResponseStatuses, ResponseCodes
from apps.settings import app_settings

from .base import BackendError

# Status-code → business error-code map. Codes outside this table fall back
# to the generic 4xx / 5xx buckets so the envelope contract holds for any
# HTTPException the framework or app code may raise.
_HTTP_STATUS_TO_RESPONSE_CODE: dict[int, ResponseCodes] = {
    400: ResponseCodes.API001,
    401: ResponseCodes.API004,
    403: ResponseCodes.API005,
    404: ResponseCodes.API006,
    409: ResponseCodes.API007,
    422: ResponseCodes.API002,
    429: ResponseCodes.API008,
}


def unhandled_exception_handler(_: Request, exc: Exception) -> ORJSONResponse:
    """Catch-all handler for exceptions not covered by specific handlers.

    Prevents raw tracebacks from leaking in production responses.

    Args:
        _: FastAPI Request instance.
        exc: The unhandled exception.

    Returns:
        ORJSONResponse with a generic 500 error body.
    """
    if app_settings.environment.lower() == "production":
        # Production logs ship to third-party indices; a full traceback
        # leaks source paths and variable names. ``repr`` keeps the type
        # and message but drops the stack.
        logger.error("Unhandled exception: {!r}", exc)
    else:
        logger.exception("Unhandled exception: {}", exc)
    return ORJSONResponse(
        status_code=500,
        content={
            "code": ResponseCodes.API003,
            "data": None,
            "status": JsonResponseStatuses.ERROR,
            "message": "Internal server error.",
        },
    )


def backend_exception_handler(_: Request, exc: BackendError) -> ORJSONResponse:
    """Handler for BackendError.

    Args:
        _: FastAPI Request instance.
        exc: Error that backend raises.

    Returns:
        ORJSONResponse with business error code in body and HTTP status code.
    """
    return ORJSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "data": exc.data,
            "status": exc.status,
            "message": exc.message,
        },
        background=exc.background_task,
    )


def http_exception_handler(_: Request, exc: StarletteHTTPException) -> ORJSONResponse:
    """Wrap framework-raised ``HTTPException`` in the standard ``APIResponse`` envelope.

    Covers the cases that bypass :func:`backend_exception_handler`:

    * Unknown routes (Starlette raises ``HTTPException(404)``).
    * Disallowed methods on a known route (``HTTPException(405)``).
    * Any code that raises ``fastapi.HTTPException`` / ``starlette.exceptions.HTTPException``
      directly instead of a :class:`BackendError` subclass.

    Without this handler the response body is the framework default
    ``{"detail": "..."}`` shape, breaking the documented ``{code, data,
    status, message}`` contract that every client parses.

    Args:
        _: FastAPI Request instance.
        exc: The HTTPException raised by the framework or application.

    Returns:
        ORJSONResponse with APIResponse-shaped body and the original HTTP status.
    """
    code = _HTTP_STATUS_TO_RESPONSE_CODE.get(exc.status_code)
    if code is None:
        code = ResponseCodes.API003 if exc.status_code >= 500 else ResponseCodes.API001

    status = JsonResponseStatuses.ERROR if exc.status_code >= 500 else JsonResponseStatuses.FAIL
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

    return ORJSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "data": None,
            "status": status,
            "message": message,
        },
        headers=getattr(exc, "headers", None),
    )


def validation_exception_handler(_: Request, exc: RequestValidationError) -> ORJSONResponse:
    """Handler for RequestValidationError.

    Args:
        _: FastAPI Request instance.
        exc: Error that Pydantic raises on validation failure.

    Returns:
        ORJSONResponse with validation error details.
    """
    details = exc.errors()
    logger.error(f"[Validation Error] Details: {details}")
    modified_details = [
        {
            "location": error["loc"],
            "message": error["msg"].capitalize() + ".",
            "type": error["type"],
        }
        for error in details
    ]

    return ORJSONResponse(
        status_code=422,
        content={
            "code": ResponseCodes.API002,
            "data": modified_details,
            "status": JsonResponseStatuses.FAIL,
            "message": "Validation error occurred.",
        },
    )
