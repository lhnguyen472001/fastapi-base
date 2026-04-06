from typing import Any

from fastapi import status as http_status
from starlette.background import BackgroundTask

from libs.schemas.response import JsonResponseStatuses, ResponseCodes

from .base import BackendError


class BadRequestError(BackendError):
    """Bad Request Error."""

    code: str = ResponseCodes.API001
    status_code: int = http_status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API001,
        data: dict[str, Any] | None = None,
        message: str = "Bad Request.",
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)


class ConflictError(BackendError):
    """Conflict Error."""

    code: str = ResponseCodes.API001
    status_code: int = http_status.HTTP_409_CONFLICT

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API001,
        data: dict[str, Any] | None = None,
        message: str = "Conflict.",
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)


class UnauthorizedError(BackendError):
    """Unauthorized Error."""

    code: str = ResponseCodes.API001
    status_code: int = http_status.HTTP_401_UNAUTHORIZED

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API001,
        data: dict[str, Any] | None = None,
        message: str = "Unauthorized.",
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)


class NotFoundError(BackendError):
    """Not Found Error."""

    code: str = ResponseCodes.API001
    status_code: int = http_status.HTTP_404_NOT_FOUND

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API001,
        data: dict[str, Any] | None = None,
        message: str = "Not Found.",
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)


class ForbiddenError(BackendError):
    """Forbidden Error."""

    code: str = ResponseCodes.API001
    status_code: int = http_status.HTTP_403_FORBIDDEN

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API001,
        data: dict[str, Any] | None = None,
        message: str = "Forbidden.",
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)


class InternalServerError(BackendError):
    """Internal Server Error."""

    code: str = ResponseCodes.API003
    status_code: int = http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(
        self,
        *,
        code: str = ResponseCodes.API003,
        data: dict[str, Any] | None = None,
        message: str = "Internal Server Error.",
        status: JsonResponseStatuses = JsonResponseStatuses.ERROR,
        background_task: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(status=status, data=data, message=message, background_task=background_task)
