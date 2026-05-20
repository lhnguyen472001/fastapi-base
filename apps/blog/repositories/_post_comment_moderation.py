"""Data access for :class:`PostComment` (moderator surface)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import func, select, update as sa_update

from apps.blog.models import PostComment
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostCommentModerationRepository(BaseSQLAlchemyRepository[PostComment]):
    """Data access for :class:`PostComment` from the moderator surface.

    Distinct from :class:`PostCommentRepository` so the moderator-only
    queries (pending list, transition_state, mark_moderator_deleted)
    live next to each other.
    """

    model_type = PostComment

    async def list_pending(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PostComment], int]:
        """Paginated oldest-first list of ``state = 'pending'`` rows.

        Uses ``ix_post_comments_workspace_pending``. ``post_id`` narrows
        the scope to one post; ``None`` returns the whole workspace queue.
        Soft-deleted rows are excluded — a moderator never sees a
        pending-then-purged-by-sweeper row.
        """
        conditions: list[Any] = [
            PostComment.workspace_id == workspace_id,
            PostComment.state == "pending",
            PostComment.deleted_at.is_(None),
        ]
        if post_id is not None:
            conditions.append(PostComment.post_id == post_id)

        base = select(PostComment).where(*conditions)
        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        page_stmt = base.order_by(PostComment.created_at.asc()).limit(limit).offset(offset)
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, int(total)

    async def find_by_id(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
    ) -> PostComment | None:
        """Fetch a comment row by id (including soft-deleted rows).

        Moderator endpoints inspect ``state``, ``deleted_at``, and the
        attribution columns so the soft-delete predicate is deliberately
        NOT applied here.
        """
        stmt = select(PostComment).where(PostComment.id == comment_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def transition_state(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        new_state: str,
        moderator_id: uuid.UUID,
        moderated_at: datetime.datetime,
        reason: str | None,
    ) -> PostComment:
        """Update ``state`` + moderator-attribution columns in one UPDATE.

        Returns the post-update row via ``RETURNING``. The
        ``trg_post_comments_count_upd`` trigger fires on the state change
        and adjusts ``posts.comment_count`` accordingly (research §13 /
        data-model §4): ``pending -> approved`` ticks +1; ``approved ->
        rejected`` ticks -1; ``pending -> rejected`` is a no-op.
        """
        stmt = (
            sa_update(PostComment)
            .where(PostComment.id == comment_id)
            .values(
                state=new_state,
                moderated_by_user_id=moderator_id,
                moderated_at=moderated_at,
                moderation_reason=reason,
            )
            .returning(PostComment)
        )
        return (await session.execute(stmt)).scalar_one()

    async def mark_moderator_deleted(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        moderator_id: uuid.UUID,
        moderated_at: datetime.datetime,
        reason: str | None,
    ) -> PostComment:
        """Soft-delete via moderator action.

        Sets ``deleted_at`` + the attribution triple in a single UPDATE.
        ``is_tombstoned`` is NOT set — moderator deletes are authoritative
        removals, not author tombstones (data-model §3). The UPDATE
        trigger drops ``posts.comment_count`` by 1 iff the row was
        contributing (``state = 'approved' AND deleted_at IS NULL``)
        before this UPDATE.
        """
        stmt = (
            sa_update(PostComment)
            .where(PostComment.id == comment_id)
            .values(
                deleted_at=moderated_at,
                moderated_by_user_id=moderator_id,
                moderated_at=moderated_at,
                moderation_reason=reason,
            )
            .returning(PostComment)
        )
        return (await session.execute(stmt)).scalar_one()
