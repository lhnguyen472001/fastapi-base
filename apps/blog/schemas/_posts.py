"""Post + Autosave + PostVersion schemas."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from apps.blog.constants import (
    MAX_TAGS_PER_POST,
    POST_COVER_IMAGE_URL_MAX_LENGTH,
    POST_EXCERPT_MAX_LENGTH,
    POST_META_DESCRIPTION_MAX_LENGTH,
    POST_META_TITLE_MAX_LENGTH,
    POST_SLUG_MAX_LENGTH,
    POST_TITLE_MAX_LENGTH,
    POST_VERSION_CHANGE_NOTE_MAX_LENGTH,
)
from apps.blog.enums import PostStatus
from apps.blog.schemas._shared import HeroQuote
from apps.blog.schemas._taxonomy import CategoryResponse, TagResponse
from apps.core.schemas.base import BaseObjectSchema
from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema


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
    # Per-caller engagement indicator (FR-006). Populated when the caller is
    # authenticated; ``None`` for anonymous reads.
    liked_by_me: bool | None = None


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
    reading_minutes: int | None
    updated_at: datetime.datetime
    persisted: bool


class PostVersionAuthor(BaseObjectSchema):
    """Nested author block on version metadata responses."""

    id: uuid.UUID
    username: str
    display_name: str | None = None


class PostVersionResponse(ResponseObjectSchema):
    """Metadata for one row in the version-history list.

    Excludes the full content payload — clients fetch
    :class:`PostVersionDetailResponse` for that.
    """

    post_id: uuid.UUID
    version: int = Field(..., ge=1)
    title: str
    content_hash: str = Field(..., min_length=64, max_length=64)
    change_note: str | None = None
    is_published_snapshot: bool
    is_restored: bool
    status_at_save: str
    created_at: datetime.datetime
    created_by: PostVersionAuthor


class PostVersionDetailResponse(PostVersionResponse):
    """Full snapshot — decompressed ProseMirror document plus plain text."""

    content_json: dict = Field(..., description="Tiptap ProseMirror document at version-save time.")
    content_text: str = Field(..., description="Plain-text body at version-save time.")


class RestoreVersionResult(ResponseObjectSchema):
    """Result envelope for ``POST .../versions/{n}/restore``."""

    post_id: uuid.UUID
    restored_from_version: int = Field(..., ge=1)
    new_version: PostVersionResponse


class CompareVersionsHunk(BaseObjectSchema):
    """One line of a unified diff between two version content_texts."""

    op: str = Field(..., pattern=r"^(added|removed|context)$")
    line: str
    from_line_no: int | None = None
    to_line_no: int | None = None


class CompareVersionsResult(ResponseObjectSchema):
    """Structured diff response for ``GET .../versions/compare``."""

    post_id: uuid.UUID
    from_version: int = Field(..., ge=1)
    to_version: int = Field(..., ge=1)
    title_changed: bool
    from_title: str
    to_title: str
    hunks: list[CompareVersionsHunk]


class ListPostVersionsRequest(OffsetPaginationRequestSchema):
    """Query params for the version-history list endpoint.

    Only pagination at this point; future filters (by author, time
    window, published-only) can be added without changing the route
    signature.
    """


class RestorePostVersionRequest(RequestObjectSchema):
    """Optional body for ``POST .../versions/{n}/restore``."""

    change_note: str | None = Field(
        default=None,
        max_length=POST_VERSION_CHANGE_NOTE_MAX_LENGTH,
        description="Overrides the auto-generated change_note on the new version row.",
    )
