"""Workspace-scoped data access for :class:`Post`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import exists, func, select, update as sa_update
from sqlalchemy.orm import selectinload

from apps.blog.enums import PostStatus
from apps.blog.models import Post, PostComment, PostLike, PostTag
from apps.blog.store import PostAutosaveState
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostRepository(BaseSQLAlchemyRepository[Post]):
    """Workspace-scoped data access for :class:`Post`."""

    model_type = Post

    async def find_by_id(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        include_deleted: bool = False,
        load_content: bool = False,
    ) -> Post | None:
        conditions: list[Any] = [
            Post.id == post_id,
            Post.workspace_id == workspace_id,
        ]
        if not include_deleted:
            conditions.append(Post.deleted_at.is_(None))

        stmt = select(Post).where(*conditions)
        stmt = stmt.options(selectinload(Post.category), selectinload(Post.tags))
        if load_content:
            stmt = stmt.options(selectinload(Post.content))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_by_id_any_workspace(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> Post | None:
        """Direct post lookup by id with no workspace filter.

        Intended for RBAC-gated paths (e.g. moderator-delete) where the
        caller knows the post id but not its workspace, and the route
        layer has already enforced the relevant permission. Soft-deleted
        rows are still returned so authorship checks remain stable across
        tombstone transitions.
        """
        stmt = select(Post).where(Post.id == post_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_autosave_state(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> PostAutosaveState | None:
        """Return only ``(workspace_id, status, content_hash)`` for the post.

        ``find_by_id`` would fire 3 SELECTs (Post + selectinload(category)
        + selectinload(tags)) on every keystroke; this hot-path projection
        is a single SELECT of three scalar columns.
        """
        stmt = select(Post.workspace_id, Post.status, Post.content_hash).where(
            Post.id == post_id,
            Post.workspace_id == workspace_id,
            Post.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None
        workspace_id_val, status_val, content_hash_val = row
        return PostAutosaveState(
            workspace_id=workspace_id_val,
            status=status_val,
            content_hash=content_hash_val,
        )

    @staticmethod
    def _published_post_filter_clauses(*, workspace_id: uuid.UUID, slug: str) -> list[Any]:
        """WHERE clauses shared by every ``published-by-slug`` SELECT.

        Centralised so the anonymous and authenticated branches of
        :meth:`find_published_by_slug_with_like_state` cannot drift in
        which rows they accept as "published".
        """
        return [
            Post.workspace_id == workspace_id,
            Post.slug == slug,
            Post.deleted_at.is_(None),
            Post.status == PostStatus.PUBLISHED.value,
        ]

    @staticmethod
    def _published_post_load_options() -> tuple[Any, ...]:
        """Eager-load options used to materialise ``PostDetailResponse``."""
        return (
            selectinload(Post.category),
            selectinload(Post.tags),
            selectinload(Post.content),
        )

    async def find_published_by_slug_with_like_state(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        current_user_id: uuid.UUID | None,
    ) -> tuple[Post, bool | None] | None:
        """Return ``(Post, liked_by_me)`` for a published post by slug.

        When ``current_user_id`` is non-None the SELECT is augmented with
        a correlated ``EXISTS`` against ``post_likes`` so we never make a
        second round-trip to populate ``PostDetailResponse.liked_by_me``
        (research §10). Anonymous callers get ``liked_by_me = None``.

        Returns ``None`` when the post is missing, soft-deleted, or not
        in the ``published`` status.
        """
        clauses = self._published_post_filter_clauses(workspace_id=workspace_id, slug=slug)
        options = self._published_post_load_options()
        if current_user_id is None:
            stmt = select(Post).where(*clauses).options(*options)
            post = (await session.execute(stmt)).scalar_one_or_none()
            return (post, None) if post is not None else None
        liked_subq = (
            exists()
            .where(
                PostLike.post_id == Post.id,
                PostLike.user_id == current_user_id,
            )
            .label("liked_by_me")
        )
        stmt = select(Post, liked_subq).where(*clauses).options(*options)
        row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None
        post, liked = row
        return post, bool(liked)

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        status: PostStatus | None = None,
        exclude_id: uuid.UUID | None = None,
        load_content: bool = False,
    ) -> Post | None:
        conditions: list[Any] = [
            Post.workspace_id == workspace_id,
            Post.slug == slug,
            Post.deleted_at.is_(None),
        ]
        if status is not None:
            conditions.append(Post.status == status.value)
        if exclude_id is not None:
            conditions.append(Post.id != exclude_id)

        stmt = select(Post).where(*conditions)
        stmt = stmt.options(selectinload(Post.category), selectinload(Post.tags))
        if load_content:
            stmt = stmt.options(selectinload(Post.content))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_workspace(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        status: PostStatus | None,
        category_id: uuid.UUID | None,
        tag_id: uuid.UUID | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Post], int]:
        conditions: list[Any] = [
            Post.workspace_id == workspace_id,
            Post.deleted_at.is_(None),
        ]
        if status is not None:
            conditions.append(Post.status == status.value)
        if category_id is not None:
            conditions.append(Post.category_id == category_id)

        base = select(Post).where(*conditions)
        if tag_id is not None:
            base = base.join(PostTag, PostTag.post_id == Post.id).where(PostTag.tag_id == tag_id)
        if search:
            base = base.where(Post.search_vector.op("@@")(func.plainto_tsquery("simple", search)))

        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        # Order: published first by published_at desc, then any post by created_at desc.
        page = (
            base.order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Post.category), selectinload(Post.tags))
        )
        items = list((await session.execute(page)).scalars().unique().all())
        return items, int(total)

    async def find_cached_counters(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> tuple[int, int] | None:
        """Return ``(like_count, comment_count)`` from the ``posts`` row.

        Reads the cached counter columns directly so the result is
        immune to SQLAlchemy identity-map staleness (the PG triggers
        UPDATE the row underneath whatever ORM instance the session
        already holds). Returns ``None`` when the post does not exist.
        """
        stmt = select(Post.like_count, Post.comment_count).where(Post.id == post_id)
        row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return int(row.like_count), int(row.comment_count)

    async def scalar_counts_for_reconcile(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> tuple[int, int]:
        """Return ``(like_count, comment_count)`` from authoritative scalars.

        Used by the reconcile endpoint (FR-026 / research §15):
        ``like_count`` is ``COUNT(*) FROM post_likes``; ``comment_count``
        is the count of rows that satisfy the trigger's contribution
        predicate (``state = 'approved' AND deleted_at IS NULL``).
        """
        like_stmt = select(func.count()).select_from(PostLike).where(PostLike.post_id == post_id)
        comment_stmt = (
            select(func.count())
            .select_from(PostComment)
            .where(
                PostComment.post_id == post_id,
                PostComment.state == "approved",
                PostComment.deleted_at.is_(None),
            )
        )
        like_count = (await session.execute(like_stmt)).scalar_one()
        comment_count = (await session.execute(comment_stmt)).scalar_one()
        return int(like_count), int(comment_count)

    async def update_counters(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        like_count: int,
        comment_count: int,
    ) -> None:
        """Overwrite ``posts.like_count`` + ``posts.comment_count`` in one UPDATE.

        Used only by the operator-callable reconcile path; the trigger is
        the authoritative writer for every normal mutation.
        """
        stmt = sa_update(Post).where(Post.id == post_id).values(like_count=like_count, comment_count=comment_count)
        await session.execute(stmt)
