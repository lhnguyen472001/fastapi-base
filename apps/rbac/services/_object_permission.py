"""Per-object ABAC grants."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import casbin
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.transactional import transactional
from apps.core.services.base import SQLAlchemyService
from apps.rbac.exceptions import RBACConflictError, RBACPolicySyncError
from apps.rbac.models import ObjectPermission
from apps.rbac.services._helpers import instance_obj, user_sub

if TYPE_CHECKING:
    from apps.rbac.repositories import ObjectPermissionRepository


class ObjectPermissionService(SQLAlchemyService[ObjectPermission]):
    """Grant and revoke per-object ABAC permissions.

    Each grant becomes a Casbin policy of the shape
    ``p, user:<id>, <resource>:<object_id>, <action>`` so
    :meth:`AccessService.check_object` can evaluate it as an instance
    override before falling back to type-level RBAC.

    Mutations follow the *commit-then-policy-sync* pattern: the relational
    write commits first, then Casbin is updated. On Casbin failure the
    relational row is compensated in a fresh transaction. See
    :mod:`apps.rbac.services` module docstring for the full rationale.
    """

    def __init__(
        self,
        *,
        repository: ObjectPermissionRepository,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        super().__init__(repository=repository)
        self.enforcer = enforcer

    async def grant(
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
        """Grant ``user_id`` the right to ``action`` on ``resource:object_id``.

        Idempotent: re-granting an already-active row simply returns it.
        """
        grant, was_existing = await self._db_grant(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
            granted_by=granted_by,
            expires_at=expires_at,
        )
        if was_existing:
            return grant

        try:
            await self.enforcer.add_policy(user_sub(user_id), instance_obj(resource, object_id), action)
        except Exception as sync_exc:
            await self._compensate_object_permission_drift(
                session,
                grant_id=grant.id,
                operation="grant",
                sync_exc=sync_exc,
            )

        logger.info(
            "ObjectPermissionService - grant - user={} {}:{}/{}",
            user_id,
            resource,
            object_id,
            action,
        )
        return grant

    async def revoke(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
    ) -> bool:
        """Revoke a previously granted object permission.

        Returns ``True`` when a row was found and revoked, ``False`` otherwise.
        """
        revoked_grant_id = await self._db_revoke(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
        if revoked_grant_id is None:
            return False

        try:
            await self.enforcer.remove_policy(user_sub(user_id), instance_obj(resource, object_id), action)
        except Exception as sync_exc:
            # Compensation for revoke would mean re-creating the grant row,
            # but losing the original ``id`` / ``granted_by`` makes that a
            # poor round-trip. Surface the drift loudly instead — the
            # relational row is gone, the policy is still in place.
            logger.error(
                "ObjectPermissionService - revoke - DRIFT: relational grant deleted "
                "but Casbin remove_policy failed user={} {}:{}/{}: {!r}",
                user_id,
                resource,
                object_id,
                action,
                sync_exc,
            )
            msg = (
                f"DRIFT: relational object grant {revoked_grant_id} deleted but Casbin remove_policy failed: {sync_exc}"
            )
            raise RBACPolicySyncError(message=msg) from sync_exc

        logger.info(
            "ObjectPermissionService - revoke - user={} {}:{}/{}",
            user_id,
            resource,
            object_id,
            action,
        )
        return True

    @transactional
    async def _db_grant(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
        granted_by: uuid.UUID | None,
        expires_at: datetime | None,
    ) -> tuple[ObjectPermission, bool]:
        """Commit the relational grant; return (grant, was_existing).

        ``was_existing=True`` means the active grant was already there and
        no Casbin write is needed (idempotent re-grant).
        """
        existing = await self.repository.find_active(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
        if existing is not None:
            return existing, True

        try:
            grant = await self.repository.add(
                session,
                data={
                    "user_id": user_id,
                    "resource": resource,
                    "object_id": object_id,
                    "action": action,
                    "granted_by": granted_by,
                    "expires_at": expires_at,
                },
            )
        except IntegrityError as exc:
            raise RBACConflictError(
                message=f"Object grant for user {user_id} on {resource}:{object_id}/{action} already exists."
            ) from exc

        return grant, False

    @transactional
    async def _db_revoke(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        resource: str,
        object_id: str,
        action: str,
    ) -> int | None:
        """Commit the relational revoke; return the deleted row id, or None."""
        existing = await self.repository.find_active(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
        if existing is None:
            return None

        await self.repository.delete(session, item_id=existing.id)
        return existing.id

    async def _compensate_object_permission_drift(
        self,
        session: AsyncSession,
        *,
        grant_id: int,
        operation: str,
        sync_exc: BaseException,
    ) -> None:
        """Best-effort compensation for a committed grant whose Casbin sync failed.

        Always raises :class:`RBACPolicySyncError`.
        """
        logger.error(
            "ObjectPermissionService - {} - Casbin sync failed; compensating grant={}: {!r}",
            operation,
            grant_id,
            sync_exc,
        )
        drift = False
        try:
            await self._delete_object_permission(session, grant_id=grant_id)
        except Exception as comp_exc:
            drift = True
            logger.error(
                "ObjectPermissionService - {} - DRIFT: compensation failed grant={}: {!r}",
                operation,
                grant_id,
                comp_exc,
            )

        msg = (
            f"DRIFT: object grant {grant_id} committed but Casbin sync and compensation both failed: {sync_exc}"
            if drift
            else f"Casbin sync failed (object grant {grant_id} compensated): {sync_exc}"
        )
        raise RBACPolicySyncError(message=msg) from sync_exc

    @transactional
    async def _delete_object_permission(self, session: AsyncSession, *, grant_id: int) -> None:
        await self.repository.delete(session, item_id=grant_id)
