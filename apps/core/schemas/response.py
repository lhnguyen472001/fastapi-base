import enum
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .base import BaseObjectSchema


class JsonResponseStatuses(enum.StrEnum):
    """Statuses for JSON responses."""

    SUCCESS = "success"  # 2xx response codes
    FAIL = "fail"  # 4xx client errors
    ERROR = "error"  # 5xx server errors


class ResponseCodes(enum.StrEnum):
    """Generic API-level error codes.

    Module-specific codes should be defined in each module's exceptions.py
    as their own StrEnum (e.g., UserErrorCodes, AuthErrorCodes).
    """

    API000 = "API000"  # Success
    API001 = "API001"  # Bad request (400)
    API002 = "API002"  # Validation error (422)
    API003 = "API003"  # Internal server error (500)
    API004 = "API004"  # Unauthorized (401)
    API005 = "API005"  # Forbidden (403)
    API006 = "API006"  # Not found (404)
    API007 = "API007"  # Conflict (409)
    API008 = "API008"  # Too many requests (429)


class ResponseObjectSchema(BaseObjectSchema):
    """Base schema for all response objects."""

    model_config = ConfigDict(
        strict=False,
        defer_build=True,
        from_attributes=True,
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=True,
    )


ResponseObjectT = TypeVar("ResponseObjectT", bound="ResponseObjectSchema")


class APIResponse[ResponseObjectT: "ResponseObjectSchema"](BaseModel):
    """Base schema for all JSON response objects."""

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        populate_by_name=True,
    )

    code: str = Field(..., description="Business error code (e.g. API001, USER001)")
    data: ResponseObjectT | None = Field(default=None, description="Response data")
    status: JsonResponseStatuses = Field(default=JsonResponseStatuses.SUCCESS, description="Response status")
    message: str = Field(..., description="Response message")

    @classmethod
    def success(
        cls,
        *,
        data: ResponseObjectT | None = None,
        message: str = "Success",
        code: str = ResponseCodes.API000,
    ) -> "APIResponse[ResponseObjectT]":
        """Build the canonical SUCCESS-status envelope.

        Replaces the boilerplate ``APIResponse[T](code=API000, data=..., status=SUCCESS, message=...)``
        construction at every route. The route's ``response_model=APIResponse[T]``
        still pins the wire-format type at the FastAPI boundary.
        """
        return cls(code=code, data=data, status=JsonResponseStatuses.SUCCESS, message=message)


class PaginatedResponse[ResponseObjectT: "ResponseObjectSchema"](ResponseObjectSchema):
    """Pagination schema for offset-based pagination."""

    items: Sequence[ResponseObjectT] = Field(default_factory=list, description="Items on current page")
    total: int = Field(default=0, ge=0, description="Total number of items")
    limit: int = Field(default=20, ge=1, le=1000, description="Number of items per page")
    offset: int = Field(default=0, ge=0, description="Offset of current page")
