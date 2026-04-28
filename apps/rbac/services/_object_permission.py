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
from apps.rbac.exceptions import RBACConflictError
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
    """

    def __init__(
        self,
        *,
        repository: ObjectPermissionRepository,
        enforcer: casbin.AsyncEnforcer,
    ) -> None:
        super().__init__(repository=repository)
        self.enforcer = enforcer

    @transactional
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
        existing = await self.repository.find_active(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
        if existing is not None:
            return existing

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

        await self.enforcer.add_policy(user_sub(user_id), instance_obj(resource, object_id), action)
        logger.info(
            "ObjectPermissionService - grant - user={} {}:{}/{}",
            user_id,
            resource,
            object_id,
            action,
        )
        return grant

    @transactional
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
        existing = await self.repository.find_active(
            session,
            user_id=user_id,
            resource=resource,
            object_id=object_id,
            action=action,
        )
        if existing is None:
            return False

        await self.repository.delete(session, item_id=existing.id)

        await self.enforcer.remove_policy(user_sub(user_id), instance_obj(resource, object_id), action)
        logger.info(
            "ObjectPermissionService - revoke - user={} {}:{}/{}",
            user_id,
            resource,
            object_id,
            action,
        )
        return True
