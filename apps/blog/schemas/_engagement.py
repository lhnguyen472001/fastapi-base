"""Engagement schemas — likes + comments + moderation + reconcile."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field, field_validator

from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema


class LikeState(ResponseObjectSchema):
    """Per-post like state returned by the like / unlike endpoints (US1).

    Always emits ``post_id`` + the current authoritative ``like_count`` +
    the caller-specific ``liked_by_me`` flag (FR-006). Used by both
    ``POST /like`` and ``DELETE /like`` so the client never needs a
    follow-up read to refresh its local engagement state.
    """

    post_id: uuid.UUID
    like_count: int = Field(..., ge=0)
    liked_by_me: bool


class LikerResponse(ResponseObjectSchema):
    """Single entry in the ``GET /posts/{id}/likers`` list (US6).

    Public display fields only — no email, no internal flags. Distinct
    from the wider :class:`apps.user.schemas.UserResponse` so the surface
    is intentionally small.
    """

    user_id: uuid.UUID
    username: str
    liked_at: datetime.datetime


class ListLikersRequest(OffsetPaginationRequestSchema):
    """Query params for the likers list."""


class CreateAuthenticatedCommentRequest(RequestObjectSchema):
    """Body shape for an authenticated comment submission (FR-010 auth path)."""

    body: str = Field(..., min_length=1, max_length=4_000)

    @field_validator("body")
    @classmethod
    def _strip_and_require_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Comment body must not be empty after trimming whitespace."
            raise ValueError(msg)
        return stripped


class UpdateCommentRequest(RequestObjectSchema):
    """Body shape for the self-edit endpoint (FR-019).

    Same validator set as the authenticated create path so the edit
    surface can't smuggle in a longer body or a whitespace-only string.
    """

    body: str = Field(..., min_length=1, max_length=4_000)

    @field_validator("body")
    @classmethod
    def _strip_and_require_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Comment body must not be empty after trimming whitespace."
            raise ValueError(msg)
        return stripped


class CreateAnonymousCommentRequest(RequestObjectSchema):
    """Body shape for an anonymous comment submission (FR-010a)."""

    body: str = Field(..., min_length=1, max_length=4_000)
    author_display_name: str = Field(..., min_length=1, max_length=80)
    author_email: str | None = Field(default=None, max_length=254)

    @field_validator("body")
    @classmethod
    def _strip_and_require_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Comment body must not be empty after trimming whitespace."
            raise ValueError(msg)
        return stripped

    @field_validator("author_display_name")
    @classmethod
    def _strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Display name must not be empty after trimming whitespace."
            raise ValueError(msg)
        return stripped

    @field_validator("author_email")
    @classmethod
    def _validate_email_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip()
        if not v:
            return None
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            msg = "author_email is not a syntactically valid email."
            raise ValueError(msg)
        return v


class PostCommentAuthor(ResponseObjectSchema):
    """Public-safe author summary on a comment response.

    ``user_id`` and ``username`` are populated for authenticated authorship;
    ``display_name`` is populated for both (derived from the joined user
    record OR from the anonymous row's ``author_display_name``). Never
    includes ``author_email``.
    """

    display_name: str
    user_id: uuid.UUID | None = None
    username: str | None = None


class PostCommentResponse(ResponseObjectSchema):
    """Public-safe comment representation (FR-017 + tombstone semantics).

    ``body`` is omitted when ``is_tombstoned`` is true — the row is kept
    for thread structure but its content is hidden from public listings.
    """

    id: uuid.UUID
    post_id: uuid.UUID
    parent_comment_id: uuid.UUID | None
    author_kind: str  # apps.blog.enums.CommentAuthorKind value
    author: PostCommentAuthor
    body: str | None
    edited_at: datetime.datetime | None
    created_at: datetime.datetime
    is_tombstoned: bool
    reply_count: int = 0


class ListCommentsRequest(OffsetPaginationRequestSchema):
    """Query params for the top-level comment list."""


class ListPendingCommentsRequest(OffsetPaginationRequestSchema):
    """Query params for the moderator pending-comment queue (US5).

    Oldest-first by ``created_at`` so the moderator drains the queue in
    submit order. Optional ``post_id`` narrows to one post; absent means
    the whole workspace queue.
    """

    post_id: uuid.UUID | None = Field(default=None)


class ModerationActionRequest(RequestObjectSchema):
    """Body for moderator approve / reject / moderator-delete endpoints (US5).

    ``moderation_reason`` is free-form and may be empty; the service
    persists it verbatim to ``post_comments.moderation_reason`` for audit.
    """

    moderation_reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("moderation_reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ModeratorPostCommentResponse(PostCommentResponse):
    """Moderator-visible projection of :class:`PostCommentResponse` (US5).

    Carries the private fields that public schemas deliberately omit:
    ``state``, ``author_email``, ``author_ip``, and the moderator-attribution
    triple. Body is returned regardless of tombstone state so the moderator
    can review the actual content.
    """

    state: str  # apps.blog.enums.CommentState value
    body: str | None  # override base to allow non-tombstoned reads
    author_email: str | None = None
    author_ip: str | None = None
    moderation_reason: str | None = None
    moderated_by_user_id: uuid.UUID | None = None
    moderated_at: datetime.datetime | None = None
    deleted_at: datetime.datetime | None = None


class EngagementCounters(ResponseObjectSchema):
    """Pair of counts surfaced by the reconcile endpoint."""

    like_count: int = Field(..., ge=0)
    comment_count: int = Field(..., ge=0)


class ReconcileEngagementCountersResponse(ResponseObjectSchema):
    """Result envelope for ``POST .../posts/{id}/reconcile-engagement-counters`` (US5).

    ``before`` reflects the cached counters at request entry; ``after``
    reflects the authoritative scalar counts; ``drift_corrected`` is True
    iff any value moved.
    """

    post_id: uuid.UUID
    before: EngagementCounters
    after: EngagementCounters
    drift_corrected: bool
