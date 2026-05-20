"""Data access for :class:`PostLike` (engagement — likes)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import joinedload

from apps.blog.models import PostLike
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostLikeRepository(BaseSQLAlchemyRepository[PostLike]):
    """Data access for :class:`PostLike`.

    All writes go through :meth:`add_idempotent` (FR-002 — unique
    ``(post_id, user_id)`` resolved via ``ON CONFLICT DO NOTHING``); all
    reads are by ``post_id`` (likers list, exists probe, counter
    reconciliation).
    """

    model_type = PostLike

    async def add_idempotent(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        """Insert a like row idempotently for ``(post_id, user_id)``.

        Returns ``True`` iff a new row was inserted (counter ticked +1
        via the PG trigger); ``False`` iff the like already existed.
        """
        stmt = (
            pg_insert(PostLike)
            .values(post_id=post_id, user_id=user_id, workspace_id=workspace_id)
            .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
            .returning(PostLike.id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def remove(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete the like row for ``(post_id, user_id)`` if present.

        Returns ``True`` iff a row was removed (counter ticked -1 via
        the PG trigger); ``False`` iff no such row existed (no-op).
        """
        stmt = delete(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == user_id).returning(PostLike.id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def exists_for_user(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Return whether the given user has liked ``post_id``."""
        stmt = select(
            exists().where(
                PostLike.post_id == post_id,
                PostLike.user_id == user_id,
            ),
        )
        return bool((await session.execute(stmt)).scalar_one())

    async def count_for_post(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> int:
        """Return the authoritative like count for ``post_id`` (FR-026)."""
        stmt = select(func.count()).select_from(PostLike).where(PostLike.post_id == post_id)
        return int((await session.execute(stmt)).scalar_one())

    async def list_likers(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[PostLike], int]:
        """Return ``(rows, total)`` for the "Liked by" list (US6 / FR-009).

        Page rows are ordered newest-first by ``created_at`` (uses the
        partial DESC index ``ix_post_likes_post_id_created_at_desc``).
        ``PostLike.user`` is eager-loaded via :func:`joinedload` so the
        downstream response builder can read ``user.username`` without
        triggering a per-row SELECT (data-model §1 / no N+1).
        """
        page_stmt = (
            select(PostLike)
            .options(joinedload(PostLike.user))
            .where(PostLike.post_id == post_id)
            .order_by(PostLike.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().unique().all())
        total_stmt = select(func.count()).select_from(PostLike).where(PostLike.post_id == post_id)
        total = int((await session.execute(total_stmt)).scalar_one())
        return rows, total
