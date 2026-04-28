"""FastAPI ``Depends`` factory for RBAC gating.

Use this in route signatures so the access check is part of the dependency
graph rather than a wrapper decorator. Compared to the legacy
``@require_access`` decorator (kept in :mod:`apps.rbac.decorators` for
back-compat with the integration tests) this form has two advantages:

* The route declares only what it actually consumes — no unused
  ``access_service`` parameter has to appear in the signature.
* The dependency yields the verified :class:`User`, so routes that need
  ``current_user`` (e.g. ``granted_by=current_user.id``) get it from the
  same call.

Usage::

    from apps.rbac.dependencies import access_required


    @router.post("/roles")
    @inject
    async def create_role(
        data: CreateRoleRequest,
        session: AsyncSession = Depends(session_factory),
        rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
        current_user: User = Depends(access_required("rbac", "manage")),
    ) -> APIResponse[RoleResponse]: ...
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import Depends

from apps.auth.dependencies import get_current_user
from apps.rbac.exceptions import AccessDeniedError
from apps.rbac.services import AccessService

if TYPE_CHECKING:
    from apps.user.models import User


def access_required(resource: str, action: str) -> Callable[..., Awaitable[User]]:
    """Build a FastAPI dependency that enforces ``current_user`` may ``action`` on ``resource``.

    Raises:
        AccessDeniedError: When the enforcer denies the request.
    """
    # Imported lazily to avoid a load-time cycle: RBACContainer instantiation
    # in apps.rbac.containers triggers wire() over apps.rbac.routes, which
    # imports this module. Pulling RBACContainer at module top would re-enter
    # rbac.containers mid-initialization. Routes call access_required() at
    # decorator-evaluation time (after both modules are fully loaded), so the
    # in-function import resolves cleanly.
    from apps.rbac.containers import RBACContainer  # noqa: PLC0415

    @inject
    async def _check(
        current_user: User = Depends(get_current_user),
        access_service: AccessService = Depends(Provide[RBACContainer.access_service]),
    ) -> User:
        allowed = await access_service.check(user_id=current_user.id, resource=resource, action=action)
        if not allowed:
            raise AccessDeniedError(message=f"User lacks '{action}' on '{resource}'.")
        return current_user

    return _check
