"""Blog module repositories — pure data access, all queries workspace-scoped."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, delete, exists, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
        liked_subq = (
            exists()
            .where(
                PostLike.post_id == Post.id,
                PostLike.user_id == current_user_id,
            )
            .label("liked_by_me")
            if current_user_id is not None
            else None
        )

        if liked_subq is not None:
            stmt = (
                select(Post, liked_subq)
                .where(
                    Post.workspace_id == workspace_id,
                    Post.slug == slug,
                    Post.deleted_at.is_(None),
                    Post.status == PostStatus.PUBLISHED.value,
                )
                .options(
                    selectinload(Post.category),
                    selectinload(Post.tags),
                    selectinload(Post.content),
                )
            )
            row = (await session.execute(stmt)).one_or_none()
            if row is None:
                return None
            post, liked = row
            return post, bool(liked)

        stmt = (
            select(Post)
            .where(
                Post.workspace_id == workspace_id,
                Post.slug == slug,
                Post.deleted_at.is_(None),
                Post.status == PostStatus.PUBLISHED.value,
            )
            .options(
                selectinload(Post.category),
                selectinload(Post.tags),
                selectinload(Post.content),
            )
        )
        post = (await session.execute(stmt)).scalar_one_or_none()
        return (post, None) if post is not None else None

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


# ---------------------------------------------------------------------------
# Engagement (post likes + post comments)
# ---------------------------------------------------------------------------


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
        defaults come from the model.
        """
        row = PostComment(**data)
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

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
            select(PostComment)
            .where(base_predicate)
            .order_by(PostComment.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, int(total)


class PostCommentModerationRepository(BaseSQLAlchemyRepository[PostComment]):
    """Data access for :class:`PostComment` from the moderator surface.

    Distinct from :class:`PostCommentRepository` so the moderator-only
    queries (pending list, transition_state, mark_moderator_deleted)
    live next to each other. Method bodies land in Phase 7 of
    specs/003-post-likes-comments.
    """

    model_type = PostComment
