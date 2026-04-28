"""Role lifecycle: creation and direct user assignment."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import casbin
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.transactional import transactional
from apps.core.services.base import SQLAlchemyService
from apps.rbac.exceptions import RBACConflictError, RoleNotFoundError
from apps.rbac.models import Role, UserRole
from apps.rbac.services._helpers import role_sub, user_sub

if TYPE_CHECKING:
    from apps.rbac.repositories import RoleRepository, UserRoleRepository


class RoleService(SQLAlchemyService[Role]):
    """Manage roles and direct user↔role assignments.

    Co-locates the two concerns that share the ``Role`` aggregate:

    * :meth:`create_role` — CREATE a hierarchical role.
    * :meth:`assign_role_to_user` — direct user assignment with Casbin sync.

    Group-mediated assignments live in :class:`GroupService`; permission
    granting lives in :class:`PermissionService`.
    """

    def __init__(
        self,
        *,
        repository: RoleRepository,
        user_role_repository: UserRoleRepository,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        super().__init__(repository=repository)
        self.user_role_repository = user_role_repository
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
            role = await self.repository.add(
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
        logger.info("RoleService - create_role - Created role {} ({})", role.id, name)
        return role

    @transactional
    async def assign_role_to_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        role_id: int,
        assigned_by: uuid.UUID | None = None,
    ) -> UserRole:
        role = await self.repository.get_one_by_id(session, item_id=role_id)
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
        logger.info("RoleService - assign_role_to_user - user={} role={}", user_id, role_id)
        return assignment
