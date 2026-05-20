"""Category + Tag schemas (request validation + response serialization)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from apps.blog.constants import (
    CATEGORY_DESCRIPTION_MAX_LENGTH,
    CATEGORY_NAME_MAX_LENGTH,
    CATEGORY_SLUG_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
    TAG_SLUG_MAX_LENGTH,
)
from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema


class CreateCategoryRequest(RequestObjectSchema):
    """Schema for creating a category in the active workspace."""

    name: str = Field(..., min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=CATEGORY_SLUG_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=CATEGORY_DESCRIPTION_MAX_LENGTH)
    display_order: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)


class UpdateCategoryRequest(RequestObjectSchema):
    """Schema for partially updating a category."""

    name: str | None = Field(default=None, min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=CATEGORY_SLUG_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=CATEGORY_DESCRIPTION_MAX_LENGTH)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = Field(default=None)


class ListCategoriesRequest(OffsetPaginationRequestSchema):
    """Query params for listing categories in a workspace."""

    is_active: bool | None = Field(default=None)


class CategoryResponse(ResponseObjectSchema):
    """Serialized category."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    display_order: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CreateTagRequest(RequestObjectSchema):
    """Schema for creating a tag in the active workspace."""

    name: str = Field(..., min_length=1, max_length=TAG_NAME_MAX_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=TAG_SLUG_MAX_LENGTH)


class UpdateTagRequest(RequestObjectSchema):
    """Schema for partially updating a tag."""

    name: str | None = Field(default=None, min_length=1, max_length=TAG_NAME_MAX_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=TAG_SLUG_MAX_LENGTH)


class ListTagsRequest(OffsetPaginationRequestSchema):
    """Query params for listing tags in a workspace."""


class TagResponse(ResponseObjectSchema):
    """Serialized tag."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
