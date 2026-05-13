"""Blog module repositories — pure data access, all queries workspace-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from apps.blog.constants import POST_VERSION_INSERT_RETRY_LIMIT
from apps.blog.enums import PostStatus
from apps.blog.exceptions import PostVersionConflictError
from apps.blog.models import (
    Category,
    Post,
    PostComment,
    PostContent,
    PostLike,
    PostTag,
    PostVersion,
    Tag,
)
from apps.blog.store import PostAutosaveState
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType

# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------


class CategoryRepository(BaseSQLAlchemyRepository[Category]):
    """Workspace-scoped data access for :class:`Category`."""

    model_type = Category

    async def find_by_id(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Category | None:
        conditions: list[Any] = [
            Category.id == category_id,
            Category.workspace_id == workspace_id,
        ]
        if not include_deleted:
            conditions.append(Category.deleted_at.is_(None))
        return await self.get_one(session, *conditions)

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> Category | None:
        conditions: list[Any] = [
            Category.workspace_id == workspace_id,
            Category.slug == slug,
            Category.deleted_at.is_(None),
        ]
        if exclude_id is not None:
            conditions.append(Category.id != exclude_id)
        return await self.get_one(session, *conditions)

    async def list_for_workspace(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Category], int]:
        conditions: list[Any] = [
            Category.workspace_id == workspace_id,
            Category.deleted_at.is_(None),
        ]
        if is_active is not None:
            conditions.append(Category.is_active == is_active)

        base = select(Category).where(*conditions)
        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(Category.display_order.asc(), Category.created_at.desc()).limit(limit).offset(offset)
        items = list((await session.execute(page)).scalars().all())
        return items, int(total)


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------


class TagRepository(BaseSQLAlchemyRepository[Tag]):
    """Workspace-scoped data access for :class:`Tag`."""

    model_type = Tag

    async def find_by_id(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> Tag | None:
        return await self.get_one(
            session,
            Tag.id == tag_id,
            Tag.workspace_id == workspace_id,
        )

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> Tag | None:
        conditions: list[Any] = [Tag.workspace_id == workspace_id, Tag.slug == slug]
        if exclude_id is not None:
            conditions.append(Tag.id != exclude_id)
        return await self.get_one(session, *conditions)

    async def list_for_workspace(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Tag], int]:
        base = select(Tag).where(Tag.workspace_id == workspace_id)
        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(Tag.name.asc()).limit(limit).offset(offset)
        items = list((await session.execute(page)).scalars().all())
        return items, int(total)

    async def list_by_ids(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_ids: Iterable[uuid.UUID],
    ) -> list[Tag]:
        ids = list(tag_ids)
        if not ids:
            return []
        stmt = select(Tag).where(Tag.workspace_id == workspace_id, Tag.id.in_(ids))
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Post / PostContent / PostTag
# ---------------------------------------------------------------------------


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


class PostContentRepository(BaseSQLAlchemyRepository[PostContent]):
    """Data access for the 1:1 :class:`PostContent` body."""

    model_type = PostContent

    async def find_by_post_id(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> PostContent | None:
        return await self.get_one(session, PostContent.post_id == post_id)


class PostTagRepository(BaseSQLAlchemyRepository[PostTag]):
    """Data access for the post↔tag join."""

    model_type = PostTag

    async def replace_post_tags(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        tag_ids: Iterable[uuid.UUID],
    ) -> None:
        """Hard-replace the tag set on a post.

        Issues at most three statements regardless of tag count: a SELECT
        of existing tag ids, one bulk DELETE for tags being dropped, and
        one executemany INSERT for tags being added. The previous loop
        produced one DELETE per dropped tag plus one INSERT per added tag,
        which under bulk re-tagging compounded into N+1 round-trips.
        """
        target = set(tag_ids)

        existing_rows = (
            (await session.execute(select(PostTag.tag_id).where(PostTag.post_id == post_id))).scalars().all()
        )
        existing = set(existing_rows)

        to_remove = existing - target
        if to_remove:
            await session.execute(
                delete(PostTag).where(PostTag.post_id == post_id, PostTag.tag_id.in_(to_remove)),
            )

        to_add = target - existing
        if to_add:
            await session.execute(
                insert(PostTag),
                [{"post_id": post_id, "tag_id": tag_id} for tag_id in to_add],
            )


# ---------------------------------------------------------------------------
# PostVersion (immutable version history)
# ---------------------------------------------------------------------------


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
        stmt = (
            select(PostVersion)
            .where(PostVersion.post_id == post_id)
            .order_by(PostVersion.version.desc())
            .limit(1)
        )
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
        """
        if "version" in data:
            msg = "PostVersionRepository.add_with_retry assigns 'version' itself; do not pass it in."
            raise ValueError(msg)
        post_id = data["post_id"]

        for attempt in range(POST_VERSION_INSERT_RETRY_LIMIT):
            next_version_stmt = (
                select(func.coalesce(func.max(PostVersion.version), 0) + 1)
                .where(PostVersion.post_id == post_id)
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


# ---------------------------------------------------------------------------
# Engagement (post likes + post comments)
# ---------------------------------------------------------------------------


class PostLikeRepository(BaseSQLAlchemyRepository[PostLike]):
    """Data access for :class:`PostLike`.

    Method bodies land in Phase 3 (US1) of specs/003-post-likes-comments.
    Phase 2 ships an empty subclass so the container can wire it.
    """

    model_type = PostLike


class PostCommentRepository(BaseSQLAlchemyRepository[PostComment]):
    """Data access for :class:`PostComment` from the comment-author surface.

    Method bodies for create / list / replies / edit / self-delete land
    in Phases 4-6 of specs/003-post-likes-comments. Phase 2 ships an
    empty subclass so the container can wire it.
    """

    model_type = PostComment


class PostCommentModerationRepository(BaseSQLAlchemyRepository[PostComment]):
    """Data access for :class:`PostComment` from the moderator surface.

    Distinct from :class:`PostCommentRepository` so the moderator-only
    queries (pending list, transition_state, mark_moderator_deleted)
    live next to each other. Method bodies land in Phase 7 of
    specs/003-post-likes-comments.
    """

    model_type = PostComment
