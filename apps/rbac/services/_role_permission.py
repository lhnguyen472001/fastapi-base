"""Role and permission management + role-permission / user-role links."""

from __future__ import annotations


from loguru import logger
from sqlalchemy.exc import IntegrityError

from apps.core.database.transactional import transactional
from apps.rbac.exceptions import (
    PermissionNotFoundError,
    RBACConflictError,
    RoleNotFoundError,
)
from apps.rbac.services._helpers import role_sub, user_sub

import uuid

import casbin
from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac.models import Permission, Role, RolePermission, UserRole
from apps.rbac.services._repositories import RBACRepositories


class RolePermissionService:
    """Create roles/permissions and wire them up.

    Responsibilities:

    * :meth:`create_role` — CREATE a role.
    * :meth:`create_permission` — CREATE a (resource, action) capability.
    * :meth:`grant_permission_to_role` — link role↔permission + Casbin.
    * :meth:`assign_role_to_user` — link user↔role + Casbin.

    All mutating methods mirror the relational write into the Casbin
    enforcer inside the same ``@transactional`` block (see the service
    package docstring for the rationale).
    """

    def __init__(
        self,
        *,
        repositories: RBACRepositories,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        self.role_repository = repositories.role
        self.permission_repository = repositories.permission
        self.role_permission_repository = repositories.role_permission
        self.user_role_repository = repositories.user_role
        self.enforcer = enforcer

    @transactional
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
        try:
            role = await self.role_repository.add(
                session,
                data={
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "parent_id": parent_id,
                    "level": level,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message=f"Role '{name}' already exists.") from exc
        logger.info(
            "RolePermissionService - create_role - Created role {} ({})",
            role.id,
            name,
        )
        return role

    @transactional
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
        try:
            perm = await self.permission_repository.add(
                session,
                data={
                    "name": name,
                    "display_name": display_name,
                    "resource": resource,
                    "action": action,
                    "description": description,
                    "category": category,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message=f"Permission '{name}' already exists.") from exc
        logger.info(
            "RolePermissionService - create_permission - Created permission {} ({})",
            perm.id,
            name,
        )
        return perm

    @transactional
    async def grant_permission_to_role(
        self,
        session: AsyncSession,
        *,
        role_id: int,
        permission_id: int,
        granted_by: uuid.UUID | None = None,
    ) -> RolePermission:
        role = await self.role_repository.get_one_by_id(session, item_id=role_id)
        if role is None:
            raise RoleNotFoundError(message=f"Role {role_id} not found.")
        perm = await self.permission_repository.get_one_by_id(session, item_id=permission_id)
        if perm is None:
            raise PermissionNotFoundError(message=f"Permission {permission_id} not found.")

        try:
            link = await self.role_permission_repository.add(
                session,
                data={
                    "role_id": role_id,
                    "permission_id": permission_id,
                    "granted_by": granted_by,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message="Permission already granted to role.") from exc

        await self.enforcer.add_policy(role_sub(role_id), perm.resource, perm.action)
        await self.enforcer.save_policy()
        logger.info(
            "RolePermissionService - grant_permission_to_role - role={} perm={}",
            role_id,
            permission_id,
        )
        return link

    @transactional
    async def assign_role_to_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserRole:
        role = await self.role_repository.get_one_by_id(session, item_id=role_id)
        if role is None:
            raise RoleNotFoundError(message=f"Role {role_id} not found.")

        try:
            assignment = await self.user_role_repository.add(
                session,
                data={
                    "user_id": user_id,
                    "role_id": role_id,
                    "assigned_by": assigned_by,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(message="User already assigned to this role.") from exc

        await self.enforcer.add_grouping_policy(user_sub(user_id), role_sub(role_id))
        await self.enforcer.save_policy()
        logger.info(
            "RolePermissionService - assign_role_to_user - user={} role={}",
            user_id,
            role_id,
        )
        return assignment
