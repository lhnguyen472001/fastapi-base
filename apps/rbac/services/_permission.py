"""Permission lifecycle and role↔permission grants."""

from __future__ import annotations

import uuid

import casbin
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.transactional import transactional
from apps.core.services.base import SQLAlchemyService
from apps.rbac.exceptions import (
    PermissionNotFoundError,
    RBACConflictError,
    RoleNotFoundError,
)
from apps.rbac.models import Permission, RolePermission
from apps.rbac.repositories import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)
from apps.rbac.services._helpers import role_sub


class PermissionService(SQLAlchemyService[Permission]):
    """Manage permissions and role↔permission grants.

    Owns the ``Permission`` aggregate plus the role-permission bridge so a
    single transaction inserts the bridge row and the matching Casbin
    policy. Direct user↔role assignments live in :class:`RoleService`.
    """

    def __init__(
        self,
        *,
        repository: PermissionRepository,
        role_repository: RoleRepository,
        role_permission_repository: RolePermissionRepository,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        super().__init__(repository=repository)
        self.role_repository = role_repository
        self.role_permission_repository = role_permission_repository
        self.enforcer = enforcer

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
            perm = await self.repository.add(
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
        logger.info("PermissionService - create_permission - Created permission {} ({})", perm.id, name)
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
        perm = await self._get_or_raise(
            session,
            item_id=permission_id,
            error_cls=PermissionNotFoundError,
            message=f"Permission {permission_id} not found.",
        )

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
        logger.info(
            "PermissionService - grant_permission_to_role - role={} perm={}",
            role_id,
            permission_id,
        )
        return link
