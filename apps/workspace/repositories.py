"""Workspace module repositories — pure data access."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType
from apps.workspace.enums import WorkspaceRole
from apps.workspace.models import Workspace, WorkspaceMember


class WorkspaceRepository(BaseSQLAlchemyRepository[Workspace]):
    """Concrete repository for :class:`Workspace`."""

    model_type = Workspace

    async def find_by_id(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Workspace | None:
        """Find a workspace by ID, excluding soft-deleted rows by default."""
        conditions: list[Any] = [Workspace.id == workspace_id]
        if not include_deleted:
            conditions.append(Workspace.deleted_at.is_(None))
        return await self.get_one(session, *conditions)

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> Workspace | None:
        """Find a workspace by slug; respects soft-delete unless asked otherwise."""
        conditions: list[Any] = [Workspace.slug == slug]
        if not include_deleted:
            conditions.append(Workspace.deleted_at.is_(None))
        if exclude_id is not None:
            conditions.append(Workspace.id != exclude_id)
        return await self.get_one(session, *conditions)


class WorkspaceMemberRepository(BaseSQLAlchemyRepository[WorkspaceMember]):
    """Concrete repository for :class:`WorkspaceMember`."""

    model_type = WorkspaceMember

    async def find_membership(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkspaceMember | None:
        """Look up a single ``(workspace_id, user_id)`` membership row."""
        return await self.get_one(
            session,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )

    async def list_for_user(
        self,
        session: SessionType,
        *,
        user_id: uuid.UUID,
        role: WorkspaceRole | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Workspace], int]:
        """List workspaces the user belongs to, paginated, with total count.

        Joins :class:`Workspace` so the response is ready to serialize without a
        second query. Filters out soft-deleted workspaces.
        """
        base = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id, Workspace.deleted_at.is_(None))
        )
        if role is not None:
            base = base.where(WorkspaceMember.role == role.value)

        total_stmt = select(func.count()).select_from(base.subquery())
        total = (await session.execute(total_stmt)).scalar_one()

        page_stmt = base.order_by(Workspace.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(page_stmt)
        items = list(result.scalars().all())
        return items, int(total)

    async def count_owners(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
    ) -> int:
        """Count active owner memberships for the workspace."""
        stmt = select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER.value,
        )
        return int((await session.execute(stmt)).scalar_one())

    async def count_members(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
    ) -> int:
        """Count all memberships for the workspace."""
        stmt = select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.workspace_id == workspace_id,
        )
        return int((await session.execute(stmt)).scalar_one())

    async def list_members(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        role: WorkspaceRole | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[WorkspaceMember], int]:
        """List members of a workspace with pagination and an optional role filter.

        Delegates to :meth:`BaseSQLAlchemyRepository.list_and_count` with
        ``using_window_function=True`` so the page and the total fold
        into a single ``SELECT ... COUNT(*) OVER ()`` statement
        (F-PERF-2). Preserves the original ``(rows, total)`` shape.
        """
        conditions: list[Any] = [WorkspaceMember.workspace_id == workspace_id]
        if role is not None:
            conditions.append(WorkspaceMember.role == role.value)

        statement = self.statement.limit(limit).offset(offset)
        rows, total = await self.list_and_count(
            session,
            *conditions,
            statement=statement,
            order_by=(WorkspaceMember.created_at, False),
            using_window_function=True,
        )
        return list(rows), total
