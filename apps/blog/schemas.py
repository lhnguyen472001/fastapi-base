"""Blog module Pydantic schemas — request validation and response serialization."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field, HttpUrl, field_validator

from apps.blog.constants import (
    CATEGORY_DESCRIPTION_MAX_LENGTH,
    CATEGORY_NAME_MAX_LENGTH,
    CATEGORY_SLUG_MAX_LENGTH,
    HERO_QUOTE_AUTHOR_MAX_LENGTH,
    HERO_QUOTE_SOURCE_URL_MAX_LENGTH,
    HERO_QUOTE_TEXT_MAX_LENGTH,
    MAX_TAGS_PER_POST,
    POST_COVER_IMAGE_URL_MAX_LENGTH,
    POST_EXCERPT_MAX_LENGTH,
    POST_META_DESCRIPTION_MAX_LENGTH,
    POST_META_TITLE_MAX_LENGTH,
    POST_SLUG_MAX_LENGTH,
    POST_TITLE_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
    TAG_SLUG_MAX_LENGTH,
)
from apps.blog.enums import PostStatus
from apps.core.schemas.base import BaseObjectSchema
from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema

# ---------------------------------------------------------------------------
# Hero quote — fixed JSONB shape
# ---------------------------------------------------------------------------


class HeroQuote(BaseObjectSchema):
    """Pull-quote attached to a post (optional).

    Round-trips cleanly through the JSONB column on
    :class:`apps.blog.models.Post`.
    """

    text: str = Field(..., min_length=1, max_length=HERO_QUOTE_TEXT_MAX_LENGTH)
    author: str | None = Field(default=None, max_length=HERO_QUOTE_AUTHOR_MAX_LENGTH)
    source_url: HttpUrl | None = Field(default=None)

    @field_validator("source_url")
    @classmethod
    def _check_source_url_length(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and len(str(value)) > HERO_QUOTE_SOURCE_URL_MAX_LENGTH:
            msg = f"source_url length must not exceed {HERO_QUOTE_SOURCE_URL_MAX_LENGTH} characters."
            raise ValueError(msg)
        return value


# ---------------------------------------------------------------------------
# Category schemas
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tag schemas
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Post schemas
# ---------------------------------------------------------------------------


class CreatePostRequest(RequestObjectSchema):
    """Schema for creating a post in the active workspace.

    ``content_json`` is the canonical Tiptap document. The server derives
    ``content_html`` and ``content_text`` from it; clients should not
    submit them.
    """

    title: str = Field(..., min_length=1, max_length=POST_TITLE_MAX_LENGTH)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=POST_SLUG_MAX_LENGTH,
        description="Optional; derived from ``title`` when omitted.",
    )
    excerpt: str | None = Field(default=None, max_length=POST_EXCERPT_MAX_LENGTH)
    cover_image_url: str | None = Field(default=None, max_length=POST_COVER_IMAGE_URL_MAX_LENGTH)
    category_id: uuid.UUID | None = Field(default=None)
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_TAGS_PER_POST)
    hero_quote: HeroQuote | None = Field(default=None)
    meta_title: str | None = Field(default=None, max_length=POST_META_TITLE_MAX_LENGTH)
    meta_description: str | None = Field(default=None, max_length=POST_META_DESCRIPTION_MAX_LENGTH)
    content_json: dict = Field(
        default_factory=lambda: {"type": "doc", "content": []},
        description="Tiptap ProseMirror document.",
    )


class UpdatePostRequest(RequestObjectSchema):
    """Schema for partially updating a post.

    Status transitions are handled by dedicated ``/publish`` /
    ``/unpublish`` / ``/archive`` endpoints, not by this schema.
    """

    title: str | None = Field(default=None, min_length=1, max_length=POST_TITLE_MAX_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=POST_SLUG_MAX_LENGTH)
    excerpt: str | None = Field(default=None, max_length=POST_EXCERPT_MAX_LENGTH)
    cover_image_url: str | None = Field(default=None, max_length=POST_COVER_IMAGE_URL_MAX_LENGTH)
    category_id: uuid.UUID | None = Field(default=None)
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_TAGS_PER_POST)
    hero_quote: HeroQuote | None = Field(default=None)
    meta_title: str | None = Field(default=None, max_length=POST_META_TITLE_MAX_LENGTH)
    meta_description: str | None = Field(default=None, max_length=POST_META_DESCRIPTION_MAX_LENGTH)
    content_json: dict | None = Field(default=None)


class ListPostsRequest(OffsetPaginationRequestSchema):
    """Query params for listing posts in a workspace.

    Used by both admin and public routes; the public router pins
    ``status=PUBLISHED`` itself before passing the params downstream.
    """

    status: PostStatus | None = Field(default=None)
    category_id: uuid.UUID | None = Field(default=None)
    tag_id: uuid.UUID | None = Field(default=None)
    search: str | None = Field(default=None, max_length=255)


class PostResponse(ResponseObjectSchema):
    """Serialized post — metadata only.

    ``content_*`` fields are exposed via :class:`PostDetailResponse` so
    list endpoints don't pay the JSONB cost.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    author_id: uuid.UUID
    category_id: uuid.UUID | None
    title: str
    slug: str
    excerpt: str | None
    cover_image_url: str | None
    status: PostStatus
    published_at: datetime.datetime | None
    reading_minutes: int | None
    word_count: int | None
    view_count: int
    like_count: int
    comment_count: int
    hero_quote: HeroQuote | None
    meta_title: str | None
    meta_description: str | None
    content_hash: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class PostDetailResponse(PostResponse):
    """Post + Tiptap body. Used by detail endpoints (admin + public read-by-slug)."""

    content_json: dict
    content_html: str
    content_text: str
    category: CategoryResponse | None = None
    tags: list[TagResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Autosave schemas
# ---------------------------------------------------------------------------


class AutosavePostRequest(RequestObjectSchema):
    """Request body for the lightweight autosave endpoint.

    Only ``content_json`` is accepted; all other post fields are managed
    via the full ``PATCH`` endpoint. The server persists this to Redis
    (write-behind) and lazily flushes it to Postgres.
    """

    content_json: dict = Field(..., description="Tiptap ProseMirror document.")


class AutosaveResponse(ResponseObjectSchema):
    """Response for an autosave request.

    ``persisted`` is True iff the same content was already in Postgres at
    request time (i.e. the autosave was a no-op short-circuit). When
    False, the body lives in Redis only and a future flush will write it
    through.
    """

    post_id: uuid.UUID
    content_hash: str
    word_count: int
    reading_minutes: int
    updated_at: datetime.datetime
    persisted: bool
