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
    RBACPolicySyncError,
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

    Owns the ``Permission`` aggregate plus the role-permission bridge.
    Mutations follow the *commit-then-policy-sync* pattern: the relational
    write commits first, then Casbin is updated. On Casbin failure the
    relational row is compensated in a fresh transaction. See
    :mod:`apps.rbac.services` module docstring for the full rationale.
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

    async def grant_permission_to_role(
        self,
        session: AsyncSession,
        *,
        role_id: int,
        permission_id: int,
        granted_by: uuid.UUID | None = None,
    ) -> RolePermission:
        link, perm = await self._db_grant_permission_to_role(
            session,
            role_id=role_id,
            permission_id=permission_id,
            granted_by=granted_by,
        )

        try:
            await self.enforcer.add_policy(role_sub(role_id), perm.resource, perm.action)
        except Exception as sync_exc:
            await self._compensate_role_permission_drift(
                session,
                link_id=link.id,
                operation="grant_permission_to_role",
                sync_exc=sync_exc,
            )

        logger.info(
            "PermissionService - grant_permission_to_role - role={} perm={}",
            role_id,
            permission_id,
        )
        return link

    @transactional
    async def _db_grant_permission_to_role(
        self,
        session: AsyncSession,
        *,
        role_id: int,
        permission_id: int,
        granted_by: uuid.UUID | None,
    ) -> tuple[RolePermission, Permission]:
        """Commit the relational role↔permission link; return (link, perm).

        Permissions are looked up here (not in the public method) so the
        ``perm.resource`` / ``perm.action`` values used for the Casbin
        policy come from the same transaction that wrote the link row.
        """
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

        return link, perm

    async def _compensate_role_permission_drift(
        self,
        session: AsyncSession,
        *,
        link_id: int,
        operation: str,
        sync_exc: BaseException,
    ) -> None:
        """Best-effort compensation for a committed link whose Casbin sync failed.

        Always raises :class:`RBACPolicySyncError`. The message records
        whether the compensation succeeded so DRIFT can be alerted on.
        """
        logger.error(
            "PermissionService - {} - Casbin sync failed; compensating link={}: {!r}",
            operation,
            link_id,
            sync_exc,
        )
        drift = False
        try:
            await self._delete_role_permission(session, link_id=link_id)
        except Exception as comp_exc:
            drift = True
            logger.error(
                "PermissionService - {} - DRIFT: compensation failed link={}: {!r}",
                operation,
                link_id,
                comp_exc,
            )

        msg = (
            f"DRIFT: relational link {link_id} committed but Casbin sync and compensation both failed: {sync_exc}"
            if drift
            else f"Casbin sync failed (relational link {link_id} compensated): {sync_exc}"
        )
        raise RBACPolicySyncError(message=msg) from sync_exc

    @transactional
    async def _delete_role_permission(self, session: AsyncSession, *, link_id: int) -> None:
        await self.role_permission_repository.delete(session, item_id=link_id)
