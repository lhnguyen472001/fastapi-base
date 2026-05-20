"""Repositories for RBAC entities."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.rbac.models import (
    Group,
    GroupRole,
    ObjectPermission,
    Permission,
    Role,
    RolePermission,
    UserGroup,
    UserRole,
)


class RoleRepository(BaseSQLAlchemyRepository[Role]):
    model_type = Role

    async def find_by_name(self, session: AsyncSession, *, name: str) -> Role | None:
        # F-PERF-3: route through ``get_one`` so the base soft-delete
        # filter applies uniformly. ``Role`` itself has no ``deleted_at``
        # column today; the refactor is for consistency with every
        # other lookup on a ``BaseSQLAlchemyRepository``.
        return await self.get_one(session, Role.name == name)


class PermissionRepository(BaseSQLAlchemyRepository[Permission]):
    model_type = Permission

    async def find_by_name(self, session: AsyncSession, *, name: str) -> Permission | None:
        # F-PERF-3: ``Permission`` carries ``HasSoftDeletedMixin`` — going
        # through ``get_one`` means soft-deleted rows are excluded
        # automatically rather than leaking through name lookups.
        return await self.get_one(session, Permission.name == name)


class GroupRepository(BaseSQLAlchemyRepository[Group]):
    model_type = Group


class RolePermissionRepository(BaseSQLAlchemyRepository[RolePermission]):
    model_type = RolePermission

    async def list_for_role(self, session: AsyncSession, *, role_id: int) -> list[RolePermission]:
        result = await session.execute(select(RolePermission).where(RolePermission.role_id == role_id))
        return list(result.scalars().all())


class UserRoleRepository(BaseSQLAlchemyRepository[UserRole]):
    model_type = UserRole

    async def list_for_user(self, session: AsyncSession, *, user_id: uuid.UUID) -> list[UserRole]:
        result = await session.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
        )
        return list(result.scalars().all())


class UserGroupRepository(BaseSQLAlchemyRepository[UserGroup]):
    model_type = UserGroup

    async def list_for_user(self, session: AsyncSession, *, user_id: uuid.UUID) -> list[UserGroup]:
        result = await session.execute(
            select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def list_active_user_ids(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[uuid.UUID]:
        """Return ``user_id`` values for every active member of a group.

        Projects the column directly so callers (e.g.
        :meth:`GroupService.assign_role_to_group`) avoid hydrating full
        ``UserGroup`` rows when only the user IDs are needed.

        Pagination is opt-in: pass ``limit`` (and optionally ``offset``)
        to bound the result set. Service-layer fan-out flows MUST paginate
        — an unbounded ``.all()`` against a 100k-member group would pin a
        large list in worker memory and risk OOM. The default (``limit
        is None``) preserves the historical fetch-all behaviour for
        callers that explicitly cannot tolerate paging.
        """
        stmt = (
            select(UserGroup.user_id)
            .where(
                UserGroup.group_id == group_id,
                UserGroup.is_active.is_(True),
            )
            .order_by(UserGroup.user_id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ObjectPermissionRepository(BaseSQLAlchemyRepository[ObjectPermission]):
    model_type = ObjectPermission

    async def find_active(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
    ) -> ObjectPermission | None:
        result = await session.execute(
            select(ObjectPermission).where(
                ObjectPermission.user_id == user_id,
                ObjectPermission.resource == resource,
                ObjectPermission.object_id == object_id,
                ObjectPermission.action == action,
                ObjectPermission.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()


class GroupRoleRepository(BaseSQLAlchemyRepository[GroupRole]):
    model_type = GroupRole

    async def list_for_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        active_only: bool = True,
    ) -> list[GroupRole]:
        stmt = select(GroupRole).where(GroupRole.group_id == group_id)
        if active_only:
            stmt = stmt.where(GroupRole.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())
