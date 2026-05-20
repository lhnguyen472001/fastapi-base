"""Workspace-scoped data access for :class:`Tag`."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select

from apps.blog.models import Tag
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


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
