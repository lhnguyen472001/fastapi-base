"""Blog module ORM models — Category, Tag, PostTag, Post, PostContent.

Per the locked plan, :class:`Post` is metadata-only (counters, hashes,
SEO, search vector) while the heavy Tiptap payload lives in the
1:1 :class:`PostContent` row. Counter columns (``view_count``,
``like_count``, ``comment_count``) are populated by Postgres triggers
attached in the Phase 4 / 4.5 migrations.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import BYTEA, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.schema import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.sql.sqltypes import Boolean, Integer, String, Text

from apps.blog.constants import (
    CATEGORY_NAME_MAX_LENGTH,
    CATEGORY_SLUG_MAX_LENGTH,
    EMPTY_TIPTAP_DOC,
    POST_COVER_IMAGE_URL_MAX_LENGTH,
    POST_META_DESCRIPTION_MAX_LENGTH,
    POST_META_TITLE_MAX_LENGTH,
    POST_SLUG_MAX_LENGTH,
    POST_TITLE_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
    TAG_SLUG_MAX_LENGTH,
)
from apps.blog.enums import PostStatus
from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.model.mixins import HasSoftDeletedMixin
from apps.core.database.types import DateTimeUTC

# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------


class Category(UUIDAuditBase, HasSoftDeletedMixin):
    """Per-workspace post taxonomy."""

    # ``CommonTableAttributes`` would auto-pluralize ``Category`` to
    # ``categorys``; pin the proper English plural explicitly.
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_categories_workspace_slug"),
        Index("ix_categories_workspace_id", "workspace_id"),
        Index("ix_categories_deleted_at", "deleted_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(CATEGORY_NAME_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(CATEGORY_SLUG_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Tag (and Post↔Tag join)
# ---------------------------------------------------------------------------


class Tag(UUIDAuditBase):
    """Per-workspace lightweight label attached to posts via :class:`PostTag`."""

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_tags_workspace_slug"),
        Index("ix_tags_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(TAG_NAME_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(TAG_SLUG_MAX_LENGTH), nullable=False)


class PostTag(UUIDAuditBase):
    """Post ↔ Tag many-to-many join row."""

    __table_args__ = (
        UniqueConstraint("post_id", "tag_id", name="uq_post_tags_post_tag"),
        Index("ix_post_tags_tag_id", "tag_id"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Post (hot metadata)
# ---------------------------------------------------------------------------


class Post(UUIDAuditBase, HasSoftDeletedMixin):
    """Workspace-scoped blog post — metadata only.

    Counter columns are mutated by Postgres triggers attached in the
    comments + likes migrations. The 1:1 :class:`PostContent` row holds
    the heavy Tiptap JSONB / sanitized HTML / plaintext.
    """

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_posts_workspace_slug"),
        # Hot path: list published posts for a workspace, newest first.
        Index(
            "ix_posts_workspace_status_published_at",
            "workspace_id",
            "status",
            "published_at",
            postgresql_where=("deleted_at IS NULL"),
        ),
        Index("ix_posts_workspace_id", "workspace_id"),
        Index("ix_posts_author_id", "author_id"),
        Index("ix_posts_category_id", "category_id"),
        Index("ix_posts_search_vector", "search_vector", postgresql_using="gin"),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_posts_published_implies_published_at",
        ),
        CheckConstraint(
            "view_count >= 0 AND like_count >= 0 AND comment_count >= 0",
            name="ck_posts_counters_non_negative",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(POST_TITLE_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(POST_SLUG_MAX_LENGTH), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(
        String(POST_COVER_IMAGE_URL_MAX_LENGTH),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PostStatus.DRAFT.value,
    )
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC(timezone=True),
        nullable=True,
    )

    reading_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Counters maintained by triggers in later phases.
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Featured pull-quote — fixed shape {"text", "author", "source_url"}.
    hero_quote: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # SEO.
    meta_title: Mapped[str | None] = mapped_column(String(POST_META_TITLE_MAX_LENGTH), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(
        String(POST_META_DESCRIPTION_MAX_LENGTH),
        nullable=True,
    )

    # Content fingerprints — used to skip re-render / re-embed when content
    # is unchanged. ``embed_content_hash`` is reserved for the v2 RAG pipeline.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embed_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Maintained by a Postgres trigger over title/excerpt/content_text.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # Every relationship is ``lazy="raise"`` on purpose: implicit lazy-loading
    # in async SQLAlchemy code paths raises at runtime rather than silently
    # firing a synchronous DB call. Callers MUST eager-load via
    # ``selectinload(Post.content)`` / ``selectinload(Post.category)`` /
    # ``selectinload(Post.tags)`` (or ``joinedload`` where appropriate) on the
    # SELECT that builds the Post. See :mod:`apps.blog.repositories` for
    # ready-made loader options.
    content: Mapped[PostContent | None] = relationship(
        "PostContent",
        back_populates="post",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
    category: Mapped[Category | None] = relationship(
        "Category",
        lazy="raise",
    )
    tags: Mapped[list[Tag]] = relationship(
        "Tag",
        secondary="post_tags",
        lazy="raise",
    )
    versions: Mapped[list[PostVersion]] = relationship(
        "PostVersion",
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="raise",
    )


# ---------------------------------------------------------------------------
# PostContent (cold body)
# ---------------------------------------------------------------------------


class PostContent(UUIDAuditBase):
    """Heavy Tiptap payload — 1:1 with :class:`Post`.

    ``content_json`` is the canonical ProseMirror document; the server
    re-renders ``content_html`` from it on every write (sanitized via
    :func:`apps.core.tiptap.sanitize.sanitize_html`) and extracts
    ``content_text`` for the FTS column on :class:`Post`.
    """

    __table_args__ = (UniqueConstraint("post_id", name="uq_post_contents_post_id"),)

    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=lambda: dict(EMPTY_TIPTAP_DOC))
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    post: Mapped[Post] = relationship(
        "Post",
        back_populates="content",
        lazy="raise",
    )


# ---------------------------------------------------------------------------
# PostVersion (immutable historical snapshot — append-only)
# ---------------------------------------------------------------------------


class PostVersion(UUIDAuditBase):
    """Immutable snapshot of a post at one save (autosave flush or explicit).

    Rows are append-only; the application MUST NOT UPDATE them. The
    retention sweeper DELETEs rows that fall outside the per-post cap,
    excluding rows where ``is_published_snapshot`` is true.

    ``status_at_save`` is the post's status at the moment this row was
    written. The save path derives ``is_published_snapshot`` by
    comparing this value against the previous version's
    ``status_at_save``: a transition into "published" marks the row as a
    permanent snapshot (retention-exempt per FR-016).
    """

    __table_args__ = (
        UniqueConstraint("post_id", "version", name="uq_post_versions_post_version"),
        Index(
            "ix_post_versions_post_id_version_desc",
            "post_id",
            "version",
            postgresql_ops={"version": "DESC"},
        ),
        Index(
            "ix_post_versions_post_id_created_at_desc",
            "post_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
        Index(
            "ix_post_versions_workspace_published",
            "workspace_id",
            "is_published_snapshot",
            postgresql_where="is_published_snapshot",
        ),
        Index(
            "ix_post_versions_post_id_published_excl",
            "post_id",
            postgresql_where="NOT is_published_snapshot",
        ),
        CheckConstraint("version >= 1", name="ck_post_versions_version_positive"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_post_versions_content_hash_len"),
        CheckConstraint(
            "NOT (is_published_snapshot AND is_restored)",
            name="ck_post_versions_publish_xor_restore",
        ),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_json_compressed: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_restored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status_at_save: Mapped[str] = mapped_column(String(20), nullable=False)

    post: Mapped[Post] = relationship(
        "Post",
        back_populates="versions",
        lazy="raise",
    )
