import datetime
import uuid

from pydantic import EmailStr, Field

from libs.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from libs.schemas.response import ResponseObjectSchema


class CreateUserRequest(RequestObjectSchema):
    """Schema for creating a new user."""

    email: EmailStr = Field(..., description="User email address")
    username: str = Field(..., min_length=3, max_length=150, description="Username")
    password: str = Field(..., min_length=8, max_length=128, description="Plain text password")


class UpdateUserRequest(RequestObjectSchema):
    """Schema for updating an existing user."""

    email: EmailStr | None = Field(default=None, description="User email address")
    username: str | None = Field(default=None, min_length=3, max_length=150, description="Username")
    password: str | None = Field(default=None, min_length=8, max_length=128, description="New password")
    is_active: bool | None = Field(default=None, description="Whether user is active")


class ListUsersRequest(OffsetPaginationRequestSchema):
    """Schema for listing users with pagination."""

    is_active: bool | None = Field(default=None, description="Filter by active status")


class UserResponse(ResponseObjectSchema):
    """Schema for user response (excludes sensitive fields)."""

    id: uuid.UUID
    email: str
    username: str
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
