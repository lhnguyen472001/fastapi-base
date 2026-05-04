"""Blog module repositories — pure data access, all queries workspace-scoped."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from apps.blog.enums import PostStatus
from apps.blog.models import Category, Post, PostContent, PostTag, Tag
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
        """Hard-replace the tag set on a post."""
        existing = list(
            (await session.execute(select(PostTag).where(PostTag.post_id == post_id))).scalars().all(),
        )
        target = set(tag_ids)
        keep = {row.tag_id for row in existing if row.tag_id in target}

        # Delete rows not in the target set.
        for row in existing:
            if row.tag_id not in target:
                await session.delete(row)

        # Insert rows in the target set that aren't already present.
        for tag_id in target - keep:
            session.add(PostTag(post_id=post_id, tag_id=tag_id))

        await session.flush()
