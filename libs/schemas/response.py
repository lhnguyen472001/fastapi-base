import enum
from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .base import BaseObjectSchema


class JsonResponseStatuses(enum.StrEnum):
    """Statuses for JSON responses."""

    SUCCESS = "success"  # 2** response codes
    ERROR = "error"  # 4** response codes
    FAIL = "fail"  # 5** response codes


class ResponseCodes(enum.StrEnum):
    """Generic API-level error codes.

    Module-specific codes should be defined in each module's exceptions.py
    as their own StrEnum (e.g., UserErrorCodes, AuthErrorCodes).
    """

    API000 = "API000"  # Success
    API001 = "API001"  # Bad request
    API002 = "API002"  # Validation error
    API003 = "API003"  # Internal server error


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


class APIResponse(BaseModel, Generic[ResponseObjectT]):
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


class PaginatedResponse(ResponseObjectSchema, Generic[ResponseObjectT]):
    """Pagination schema for offset-based pagination."""

    items: Sequence[ResponseObjectT] = Field(default_factory=list, description="Items on current page")
    total: int = Field(default=0, ge=0, description="Total number of items")
    limit: int = Field(default=20, ge=1, le=1000, description="Number of items per page")
    offset: int = Field(default=0, ge=0, description="Offset of current page")
