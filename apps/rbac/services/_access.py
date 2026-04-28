"""Read-side RBAC / ABAC checks used by the route decorators."""

import asyncio
import uuid
from typing import Any

import casbin
from loguru import logger

from apps.rbac.services._helpers import instance_obj, read_attr, user_sub


class AccessService:
    """Read-side: RBAC + ABAC checks used by the decorators."""

    def __init__(self, *, enforcer: casbin.AsyncEnforcer) -> None:
        self.enforcer = enforcer

    async def check(
        self,
        *,
        user_id: uuid.UUID,
        resource: str,
        action: str,
    ) -> bool:
        """Plain RBAC check."""
        allowed = await asyncio.to_thread(self.enforcer.enforce, user_sub(user_id), resource, action)
        logger.debug(
            "AccessService - check - user={} {}:{} -> {}",
            user_id,
            resource,
            action,
            allowed,
        )
        return bool(allowed)

    async def check_object(
        self,
        *,
        user_id: uuid.UUID,
        obj: Any,
        action: str,
        resource: str | None = None,
        id_attr: str = "id",
    ) -> bool:
        """ABAC check with three layers (in order):

        1. **Owner short-circuit**: ``obj.owner_id == user_id`` → allow.
        2. **Per-object grant**: a row in ``object_permissions`` exposed in
           Casbin as ``p, user:<id>, <resource>:<object_id>, <action>``.
        3. **Type-level RBAC fallback**: ``p, role:<id>, <resource>, <action>``
           inherited via ``g, user:<id>, role:<id>``.
        """
        owner_id = read_attr(obj, "owner_id")
        if owner_id is not None and str(owner_id) == str(user_id):
            logger.debug("AccessService - check_object - owner match user={}", user_id)
            return True

        if resource is not None:
            object_id = read_attr(obj, id_attr)
            if object_id is not None:
                token = instance_obj(resource, str(object_id))
                if await asyncio.to_thread(self.enforcer.enforce, user_sub(user_id), token, action):
                    logger.debug(
                        "AccessService - check_object - instance grant user={} {}/{}",
                        user_id,
                        token,
                        action,
                    )
                    return True

            return await self.check(user_id=user_id, resource=resource, action=action)
        return False
