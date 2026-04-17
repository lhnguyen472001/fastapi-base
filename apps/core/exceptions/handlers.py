from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from loguru import logger

from apps.core.schemas.response import JsonResponseStatuses, ResponseCodes

from .base import BackendError


def unhandled_exception_handler(_: Request, exc: Exception) -> ORJSONResponse:
    """Catch-all handler for exceptions not covered by specific handlers.

    Prevents raw tracebacks from leaking in production responses.

    Args:
        _: FastAPI Request instance.
        exc: The unhandled exception.

    Returns:
        ORJSONResponse with a generic 500 error body.
    """
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
