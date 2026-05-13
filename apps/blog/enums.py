"""Blog module enums — post lifecycle status + comment lifecycle / authorship."""

from __future__ import annotations

import enum


class PostStatus(enum.StrEnum):
    """Post lifecycle states.

    * ``DRAFT`` — author work-in-progress; not visible to public read.
    * ``PUBLISHED`` — visible at the public read-by-slug endpoint.
      ``published_at`` is set when the transition happens; clearing it on
      unpublish flips the status back to ``DRAFT``.
    * ``ARCHIVED`` — was published, now hidden, but kept for permalink
      consistency / audit. Public read returns 404.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CommentState(enum.StrEnum):
    """Moderation lifecycle for :class:`apps.blog.models.PostComment`.

    Orthogonal to soft-delete (``deleted_at``); see data-model.md §3.

    * ``PENDING`` — born here for anonymous comments. NOT returned by any
      public list endpoint; only moderator endpoints see it.
    * ``APPROVED`` — visible to public readers. Authenticated comments
      are born here directly; anonymous comments reach this state only
      via moderator approval.
    * ``REJECTED`` — terminal moderation rejection. Never visible to
      public readers; retained for audit and to keep the moderator queue
      idempotent against double-clicks.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CommentAuthorKind(enum.StrEnum):
    """Derived discriminator surfaced on comment response schemas.

    Computed at read time from the row's author shape (whether
    ``author_user_id`` or ``author_display_name`` is set). NOT stored as
    a column — the XOR ``CHECK`` constraint on ``post_comments`` is the
    source of truth.
    """

    AUTHENTICATED = "authenticated"
    ANONYMOUS = "anonymous"
