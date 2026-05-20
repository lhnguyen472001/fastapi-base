"""Data access for :class:`PostComment` (author surface)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import delete, exists, func, select, update as sa_update

from apps.blog.models import PostComment
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostCommentRepository(BaseSQLAlchemyRepository[PostComment]):
    """Data access for :class:`PostComment` from the comment-author surface.

    Mutations route through :meth:`insert` (auth + anon); reads go through
    :meth:`list_top_level_approved` + :meth:`count_replies` +
    :meth:`fetch_author_usernames` (all batched, no N+1). Moderator-only
    queries live on :class:`PostCommentModerationRepository`.
    """

    model_type = PostComment

    async def insert(
        self,
        session: SessionType,
        *,
        data: dict[str, Any],
    ) -> PostComment:
        """Insert a comment row with the given column dict.

        Returns the persisted instance. The caller supplies all required
        columns; this method never assigns ``state`` or ``deleted_at`` —
        defaults come from the model and are populated by the flush that
        :meth:`BaseSQLAlchemyRepository.add` performs internally.

        ``expunge=False`` so the returned instance stays session-managed
        for the caller's downstream reads.
        """
        return await self.add(session, data, expunge=False)

    async def list_top_level_approved(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[PostComment], int]:
        """Paginated newest-first list of approved top-level comments.

        Uses the ``ix_post_comments_post_top_level_recent`` partial
        index; returns the page + the total count for the same filter.
        """
        base_predicate = (
            (PostComment.post_id == post_id)
            & (PostComment.state == "approved")
            & PostComment.deleted_at.is_(None)
            & PostComment.parent_comment_id.is_(None)
        )

        total = (
            await session.execute(
                select(func.count()).select_from(PostComment).where(base_predicate),
            )
        ).scalar_one()

        page_stmt = (
            select(PostComment)
            .where(base_predicate)
            .order_by(PostComment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, int(total)

    async def count_replies(
        self,
        session: SessionType,
        *,
        parent_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Batched ``COUNT(*)`` of approved replies grouped by parent.

        Returns ``{parent_id: count}`` covering only those parents that
        have at least one approved live reply; absent keys mean zero.
        """
        if not parent_ids:
            return {}
        stmt = (
            select(PostComment.parent_comment_id, func.count())
            .where(
                PostComment.parent_comment_id.in_(parent_ids),
                PostComment.state == "approved",
                PostComment.deleted_at.is_(None),
            )
            .group_by(PostComment.parent_comment_id)
        )
        rows = (await session.execute(stmt)).all()
        return {row[0]: int(row[1]) for row in rows}

    async def fetch_author_usernames(
        self,
        session: SessionType,
        *,
        user_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        """Fetch ``{user_id: username}`` for a page of authenticated authors.

        One ``IN (...)`` SELECT instead of an N+1 navigation; absent ids
        mean the user row is gone (sentinel retarget already fired).
        """
        if not user_ids:
            return {}
        from apps.user.models import User  # noqa: PLC0415 — runtime FK target

        stmt = select(User.id, User.username).where(User.id.in_(user_ids))
        rows = (await session.execute(stmt)).all()
        return {row[0]: row[1] for row in rows}

    async def find_parent_metadata(
        self,
        session: SessionType,
        *,
        parent_id: uuid.UUID,
    ) -> tuple[uuid.UUID, uuid.UUID | None, str, datetime.datetime | None] | None:
        """Probe a comment for reply-target validation.

        Returns ``(post_id, parent_comment_id, state, deleted_at)`` in a
        single SELECT (research §9). Caller decides on rejection so the
        repository stays storage-only.
        """
        stmt = select(
            PostComment.post_id,
            PostComment.parent_comment_id,
            PostComment.state,
            PostComment.deleted_at,
        ).where(PostComment.id == parent_id)
        row = (await session.execute(stmt)).first()
        if row is None:
            return None
        return row.post_id, row.parent_comment_id, row.state, row.deleted_at

    async def find_by_id(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
    ) -> PostComment | None:
        """Fetch a comment row by id including soft-deleted rows.

        Self-edit / self-delete decisions need to inspect ``deleted_at``
        and ``is_tombstoned`` before deciding what to surface, so this
        helper deliberately does NOT filter on the soft-delete predicate.
        """
        stmt = select(PostComment).where(PostComment.id == comment_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_body(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        body: str,
        edited_at: datetime.datetime,
    ) -> PostComment:
        """Update body + edited_at on an existing comment row.

        Returns the post-update row in a single round-trip via ``RETURNING``.
        Trigger fires on the state column only, so editing the body never
        moves the counter — by design.
        """
        stmt = (
            sa_update(PostComment)
            .where(PostComment.id == comment_id)
            .values(body=body, edited_at=edited_at)
            .returning(PostComment)
        )
        return (await session.execute(stmt)).scalar_one()

    async def has_approved_replies(
        self,
        session: SessionType,
        *,
        parent_id: uuid.UUID,
    ) -> bool:
        """Whether the comment has at least one approved + live reply.

        Drives the tombstone-vs-hard-delete decision in :meth:`delete_own`:
        approved replies must remain readable to preserve the thread, so
        the parent is tombstoned rather than removed.
        """
        stmt = select(
            exists().where(
                (PostComment.parent_comment_id == parent_id)
                & (PostComment.state == "approved")
                & PostComment.deleted_at.is_(None),
            ),
        )
        return bool((await session.execute(stmt)).scalar_one())

    async def tombstone(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        deleted_at: datetime.datetime,
    ) -> PostComment:
        """Soft-delete by clearing the body and stamping deleted_at + tombstone flag.

        The PG trigger on UPDATE drops ``posts.comment_count`` by 1
        because the row's ``state = approved`` no longer satisfies the
        ``deleted_at IS NULL`` half of the contribution predicate.
        """
        stmt = (
            sa_update(PostComment)
            .where(PostComment.id == comment_id)
            .values(
                deleted_at=deleted_at,
                is_tombstoned=True,
                body="[deleted]",
            )
            .returning(PostComment)
        )
        return (await session.execute(stmt)).scalar_one()

    async def hard_delete(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
    ) -> None:
        """Hard-delete the comment row.

        FK cascade removes any reply rows (including pending ones); the
        DELETE trigger drops ``posts.comment_count`` by 1 iff the row was
        contributing at delete-time.
        """
        await session.execute(delete(PostComment).where(PostComment.id == comment_id))

    async def list_replies_approved(
        self,
        session: SessionType,
        *,
        parent_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[PostComment], int]:
        """Paginated oldest-first list of approved live replies.

        Oldest-first so the reply chain reads as a conversation; uses the
        partial parent_comment_id index for O(log n) regardless of total
        comment volume on the post.
        """
        base_predicate = (
            (PostComment.parent_comment_id == parent_id)
            & (PostComment.state == "approved")
            & PostComment.deleted_at.is_(None)
        )

        total = (
            await session.execute(
                select(func.count()).select_from(PostComment).where(base_predicate),
            )
        ).scalar_one()

        page_stmt = (
            select(PostComment).where(base_predicate).order_by(PostComment.created_at.asc()).limit(limit).offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, int(total)

    async def delete_stale_pending(
        self,
        session: SessionType,
        *,
        cutoff: datetime.datetime,
        limit: int,
    ) -> int:
        """Hard-delete up to ``limit`` ``state='pending'`` rows older than ``cutoff``.

        Implements FR-010e (anonymous-comment moderation queue retention) per
        research §11. The bounded subquery prevents an unbounded DELETE from
        holding a long lock; ``ix_post_comments_workspace_pending`` (partial
        index on pending rows) keeps the scan cheap.

        Counter implication: zero. ``pending`` rows never contributed to
        ``posts.comment_count``, so the DELETE trigger is also a no-op.
        """
        target_ids_subq = (
            select(PostComment.id)
            .where(PostComment.state == "pending", PostComment.created_at < cutoff)
            .limit(limit)
            .scalar_subquery()
        )
        stmt = delete(PostComment).where(PostComment.id.in_(target_ids_subq)).returning(PostComment.id)
        result = await session.execute(stmt)
        return len(result.scalars().all())
