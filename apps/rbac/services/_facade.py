"""RBACService facade — composes the three focused write services."""

from __future__ import annotations


import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

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
from apps.rbac.services._group import GroupService
from apps.rbac.services._object_permission import ObjectPermissionService
from apps.rbac.services._role_permission import RolePermissionService


class RBACService:
    """Write-side facade that delegates to the focused sub-services.

    The facade exists so existing routes and tests that depend on a single
    ``RBACService`` keep working after the 3.3 split. New code should prefer
    injecting the relevant sub-service directly
    (:class:`RolePermissionService`, :class:`GroupService`,
    :class:`ObjectPermissionService`).
    """

    def __init__(
        self,
        *,
        role_permission_service: RolePermissionService,
        group_service: GroupService,
        object_permission_service: ObjectPermissionService,
    ) -> None:
        self.role_permission_service = role_permission_service
        self.group_service = group_service
        self.object_permission_service = object_permission_service

    # ----- Roles / Permissions (RolePermissionService) ----------------------

    async def create_role(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        description: str | None = None,
        parent_id: int | None = None,
        level: int = 0,
    ) -> Role:
        return await self.role_permission_service.create_role(
            session,
            name=name,
            display_name=display_name,
            description=description,
            parent_id=parent_id,
            level=level,
        )

    async def create_permission(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        resource: str,
        action: str,
        description: str | None = None,
        category: str | None = None,
    ) -> Permission:
        return await self.role_permission_service.create_permission(
            session,
            name=name,
            display_name=display_name,
            resource=resource,
            action=action,
            description=description,
            category=category,
        )

    async def grant_permission_to_role(
        self,
        session: AsyncSession,
        *,
        role_id: int,
        permission_id: int,
        granted_by: uuid.UUID | None = None,
    ) -> RolePermission:
        return await self.role_permission_service.grant_permission_to_role(
            session, role_id=role_id, permission_id=permission_id, granted_by=granted_by
        )

    async def assign_role_to_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserRole:
        return await self.role_permission_service.assign_role_to_user(
            session, user_id=user_id, role_id=role_id, assigned_by=assigned_by
        )

    # ----- Groups (GroupService) -------------------------------------------

    async def create_group(
        self,
        session: AsyncSession,
        *,
        name: str,
        display_name: str,
        description: str | None = None,
        parent_id: int | None = None,
        level: int = 0,
    ) -> Group:
        return await self.group_service.create_group(
            session,
            name=name,
            display_name=display_name,
            description=description,
            parent_id=parent_id,
            level=level,
        )

    async def add_user_to_group(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        group_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserGroup:
        return await self.group_service.add_user_to_group(
            session, user_id=user_id, group_id=group_id, assigned_by=assigned_by
        )

    async def assign_role_to_group(
        self,
        session: AsyncSession,
        *,
        group_id: int,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> GroupRole:
        return await self.group_service.assign_role_to_group(
            session, group_id=group_id, role_id=role_id, assigned_by=assigned_by
        )

    # ----- Object-level grants (ObjectPermissionService) -------------------

    async def grant_object_permission(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
        granted_by: uuid.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> ObjectPermission:
        return await self.object_permission_service.grant(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
            granted_by=granted_by,
            expires_at=expires_at,
        )

    async def revoke_object_permission(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
    ) -> bool:
        return await self.object_permission_service.revoke(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
