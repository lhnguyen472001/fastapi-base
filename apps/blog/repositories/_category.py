"""Workspace-scoped data access for :class:`Category`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from apps.blog.models import Category
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


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
