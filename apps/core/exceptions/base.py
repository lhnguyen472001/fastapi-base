from typing import Any

from starlette.background import BackgroundTask

from apps.core.schemas.response import JsonResponseStatuses


class BackendError(Exception):
    """Base exception for all backend errors.

    Attributes:
        code: Business error code string (e.g. "API001", "USER001").
            Each module defines its own error codes as a StrEnum.
        status_code: HTTP status code for the transport layer.
    """

    code: str
    status_code: int

    def __init__(
        self,
        *,
        data: dict[str, Any] | None = None,
        status: JsonResponseStatuses = JsonResponseStatuses.FAIL,
        message: str = "",
        background_task: BackgroundTask | None = None,
    ) -> None:
        """Initializer for BackendError.

        Keyword Args:
            data: Any detail or data for this exception.
            status: Status for response.
            message: Message for this exception.
            background_task: Background tasks to run after response.
        """
        self.data = data
        self.status = status
        self.message = message
        self.background_task = background_task

    def __repr__(self) -> str:
        """Representation for BackendError."""
        return (
            f"{self.__class__.__name__}("
            f"{self.data=}, {self.status=}, {self.message=}, "
            f"code={self.code!r}, status_code={self.status_code!r}, "
            f"{self.background_task=})"
        )

    def __str__(self) -> str:
        """String representation for BackendError."""
        return self.__repr__()

    def to_dict(self) -> dict[str, Any]:
        """Convert BackendError to dict for response wrapping."""
        return {
            "code": self.code,
            "status_code": self.status_code,
            "data": self.data,
            "status": self.status,
            "message": self.message,
        }
