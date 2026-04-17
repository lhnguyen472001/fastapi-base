"""Read-side RBAC / ABAC checks used by the route decorators."""


from typing import Any

from loguru import logger

from apps.rbac.services._helpers import instance_obj, read_attr, user_sub

import uuid
import casbin


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
        """Plain RBAC check.

        ``casbin.AsyncEnforcer.enforce`` is synchronous in the current
        casbin-python release (only policy I/O is async), so the call is
        not awaited. The surrounding method stays ``async`` for API
        symmetry with :meth:`check_object` and future async enforcers.
        """
        allowed = self.enforcer.enforce(user_sub(user_id), resource, action)
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

        ``obj`` may be an ORM model or a mapping. ``id_attr`` controls which
        attribute on ``obj`` is read for the instance identifier (default
        ``id``).
        """
        owner_id = read_attr(obj, "owner_id")
        if owner_id is not None and str(owner_id) == str(user_id):
            logger.debug("AccessService - check_object - owner match user={}", user_id)
            return True

        if resource is not None:
            object_id = read_attr(obj, id_attr)
            if object_id is not None:
                token = instance_obj(resource, str(object_id))
                # ``enforce`` is sync in casbin-python — see :meth:`check`.
                if self.enforcer.enforce(user_sub(user_id), token, action):
                    logger.debug(
                        "AccessService - check_object - instance grant user={} {}/{}",
                        user_id,
                        token,
                        action,
                    )
                    return True

            return await self.check(user_id=user_id, resource=resource, action=action)
        return False
