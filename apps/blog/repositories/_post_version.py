"""Data access for :class:`PostVersion` (immutable version history)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError

from apps.blog.constants import POST_VERSION_INSERT_RETRY_LIMIT
from apps.blog.exceptions import PostVersionConflictError
from apps.blog.models import PostVersion
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostVersionRepository(BaseSQLAlchemyRepository[PostVersion]):
    """Data access for :class:`PostVersion`.

    The table is append-only from the application's perspective: rows
    are inserted by the autosave flush path and deleted only by the
    retention sweeper. No UPDATE path exists.
    """

    model_type = PostVersion

    async def find_latest_for_post(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> PostVersion | None:
        """Return the most recent version row for ``post_id``, or ``None``."""
        stmt = select(PostVersion).where(PostVersion.post_id == post_id).order_by(PostVersion.version.desc()).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_by_post_and_version(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        version: int,
    ) -> PostVersion | None:
        """Return the row for ``(post_id, version)`` or ``None``."""
        return await self.get_one(
            session,
            PostVersion.post_id == post_id,
            PostVersion.version == version,
        )

    async def list_for_post(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[PostVersion], int]:
        """Paginated newest-first list of versions for ``post_id``."""
        total_stmt = select(func.count()).select_from(PostVersion).where(PostVersion.post_id == post_id)
        total = (await session.execute(total_stmt)).scalar_one()

        page_stmt = (
            select(PostVersion)
            .where(PostVersion.post_id == post_id)
            .order_by(PostVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, int(total)

    async def find_pair_for_compare(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        versions: tuple[int, int],
    ) -> dict[int, PostVersion]:
        """Fetch exactly two version rows by ``(post_id, version IN versions)``.

        Returns a ``{version_number: PostVersion}`` map. Callers MUST
        verify both keys are present before calling diff; a missing
        version raises 404 at the service layer.
        """
        stmt = select(PostVersion).where(
            PostVersion.post_id == post_id,
            PostVersion.version.in_(versions),
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {row.version: row for row in rows}

    async def add_with_retry(
        self,
        session: SessionType,
        *,
        data: dict[str, Any],
    ) -> PostVersion:
        """Insert a version row, resolving ``version`` under contention.

        The caller supplies ``data`` without a ``version`` key; this method
        computes ``MAX(version)+1`` for ``data["post_id"]`` and retries
        on ``UNIQUE(post_id, version)`` violations up to
        :data:`POST_VERSION_INSERT_RETRY_LIMIT` times.

        Implementation note — this method intentionally bypasses
        :meth:`BaseSQLAlchemyRepository.add`. The base method flushes
        once and propagates any ``IntegrityError`` to the caller;
        here we need per-attempt ``rollback()`` + ``continue`` so two
        concurrent versioning writes converge to ``MAX(version)+2``
        instead of both losing on the first conflict. The
        ``session.add`` + ``session.flush`` calls are deliberate, not
        rule rot. See CLAUDE.md "Mutate-then-persist".
        """
        if "version" in data:
            msg = "PostVersionRepository.add_with_retry assigns 'version' itself; do not pass it in."
            raise ValueError(msg)
        post_id = data["post_id"]

        for attempt in range(POST_VERSION_INSERT_RETRY_LIMIT):
            next_version_stmt = select(func.coalesce(func.max(PostVersion.version), 0) + 1).where(
                PostVersion.post_id == post_id
            )
            next_version = (await session.execute(next_version_stmt)).scalar_one()

            row = PostVersion(**data, version=int(next_version))
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                if attempt == POST_VERSION_INSERT_RETRY_LIMIT - 1:
                    raise PostVersionConflictError(
                        message=(
                            f"Could not assign unique version for post {post_id} "
                            f"after {POST_VERSION_INSERT_RETRY_LIMIT} attempts."
                        ),
                    ) from exc
                continue
            session.expunge(row)
            return row

        raise PostVersionConflictError(
            message=f"PostVersion insert exhausted retries for post {post_id}.",
        )

    async def find_posts_over_retention(
        self,
        session: SessionType,
        *,
        retention_limit: int,
        slack: int,
        batch_size: int,
    ) -> list[uuid.UUID]:
        """Return up to ``batch_size`` post ids whose non-published version
        count exceeds ``retention_limit + slack``.

        Driven by ``GROUP BY post_id HAVING count(*) > limit+slack``;
        published-snapshot rows are excluded from the count, matching the
        retention policy.
        """
        non_published_count = func.count(PostVersion.id)
        stmt = (
            select(PostVersion.post_id)
            .where(PostVersion.is_published_snapshot.is_(False))
            .group_by(PostVersion.post_id)
            .having(non_published_count > (retention_limit + slack))
            .limit(batch_size)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def purge_eligible(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        keep_versions: list[int],
    ) -> int:
        """DELETE non-published versions for ``post_id`` not in ``keep_versions``.

        Returns the number of rows deleted.
        """
        stmt = delete(PostVersion).where(
            and_(
                PostVersion.post_id == post_id,
                PostVersion.is_published_snapshot.is_(False),
                PostVersion.version.notin_(keep_versions) if keep_versions else PostVersion.version.is_not(None),
            ),
        )
        result = await session.execute(stmt)
        return result.rowcount or 0

    async def list_non_published_version_numbers(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        newest_first: bool = True,
    ) -> list[int]:
        """Return the non-published version numbers for ``post_id``.

        Used by the retention sweeper to compute "the top-N to keep".
        """
        order = PostVersion.version.desc() if newest_first else PostVersion.version.asc()
        stmt = (
            select(PostVersion.version)
            .where(
                PostVersion.post_id == post_id,
                PostVersion.is_published_snapshot.is_(False),
            )
            .order_by(order)
        )
        return list((await session.execute(stmt)).scalars().all())
