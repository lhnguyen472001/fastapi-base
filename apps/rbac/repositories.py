"""Repositories for RBAC entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

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

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class RoleRepository(BaseSQLAlchemyRepository[Role]):
    model_type = Role

    async def find_by_name(self, session: AsyncSession, *, name: str) -> Role | None:
        result = await session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()


class PermissionRepository(BaseSQLAlchemyRepository[Permission]):
    model_type = Permission

    async def find_by_name(self, session: AsyncSession, *, name: str) -> Permission | None:
        result = await session.execute(select(Permission).where(Permission.name == name))
        return result.scalar_one_or_none()


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
