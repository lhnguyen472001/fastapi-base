"""FastAPI dependencies for the workspace module.

Three primitives:

* ``get_workspace_by_slug`` — public-route dependency that resolves a slug
  to a non-deleted :class:`Workspace`. Sets :data:`workspace_ctx` so any
  downstream code can read the active workspace id without re-querying.
* ``require_workspace_member`` — authenticated-route dependency that
  resolves the slug **and** verifies the caller has any membership row.
* ``require_workspace_role(*allowed)`` — same as ``require_workspace_member``
  but additionally enforces that the caller's role is in ``allowed``.

The dependencies always raise :class:`WorkspaceNotFoundError` for both true
404 and cross-workspace access (i.e. authenticated user with no membership)
to prevent existence probing. Once the caller is past the membership gate,
:class:`WorkspaceRoleForbiddenError` is the surfaced 403 for role mismatch.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, Path

from apps.auth.dependencies import get_current_user
from apps.core.database.session import session_factory
from apps.workspace.containers import WorkspaceContainer
from apps.workspace.enums import WorkspaceRole
from apps.workspace.exceptions import (
    WorkspaceNotFoundError,
    WorkspaceNotMemberError,
    WorkspaceRoleForbiddenError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.user.models import User
    from apps.workspace.models import Workspace
    from apps.workspace.services import WorkspaceMemberService, WorkspaceService

# Active-workspace ContextVar — populated by every workspace dependency
# below so blog repositories / services can read the scope without
# threading workspace_id through every call.
workspace_ctx: ContextVar[uuid.UUID | None] = ContextVar("workspace_ctx", default=None)


def get_active_workspace_id() -> uuid.UUID | None:
    """Read the workspace id active for the current request, if any."""
    return workspace_ctx.get()


@inject
async def get_workspace_by_slug(
    workspace_slug: str = Path(..., description="Workspace slug from the URL."),
    session: AsyncSession = Depends(session_factory),
    workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
) -> Workspace:
    """Resolve a workspace slug to a non-deleted :class:`Workspace`.

    Pure read path — does not require authentication. Used by public
    blog endpoints (e.g. listing published posts).
    """
    workspace = await workspace_service.get_by_slug(session, slug=workspace_slug)
    workspace_ctx.set(workspace.id)
    return workspace


def require_workspace_member() -> Callable[..., Awaitable[Workspace]]:
    """Build a FastAPI dependency that asserts the caller is a member.

    Raises:
        WorkspaceNotFoundError: When the slug doesn't resolve OR when the
            authenticated caller has no membership row (existence is masked).
    """

    @inject
    async def _check(
        workspace_slug: str = Path(..., description="Workspace slug from the URL."),
        session: AsyncSession = Depends(session_factory),
        current_user: User = Depends(get_current_user),
        workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
        member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
    ) -> Workspace:
        workspace = await workspace_service.get_by_slug(session, slug=workspace_slug)

        membership = await member_service.find_membership(
            session,
            workspace_id=workspace.id,
            user_id=current_user.id,
        )
        if membership is None:
            # Mask existence — surface the same 404 a non-member would get.
            raise WorkspaceNotFoundError(message=f"Workspace with slug '{workspace_slug}' not found.")

        workspace_ctx.set(workspace.id)
        return workspace

    return _check


def require_workspace_role(*allowed: WorkspaceRole) -> Callable[..., Awaitable[Workspace]]:
    """Build a FastAPI dependency that asserts the caller has one of ``allowed`` roles.

    Args:
        *allowed: Roles that satisfy the gate. At least one must be provided.

    Raises:
        WorkspaceNotFoundError: Slug missing or caller is not a member.
        WorkspaceRoleForbiddenError: Caller is a member but role is not in ``allowed``.
    """
    if not allowed:
        msg = "require_workspace_role requires at least one allowed role."
        raise ValueError(msg)
    allowed_values = {role.value for role in allowed}

    @inject
    async def _check(
        workspace_slug: str = Path(..., description="Workspace slug from the URL."),
        session: AsyncSession = Depends(session_factory),
        current_user: User = Depends(get_current_user),
        workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
        member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
    ) -> Workspace:
        workspace = await workspace_service.get_by_slug(session, slug=workspace_slug)

        membership = await member_service.find_membership(
            session,
            workspace_id=workspace.id,
            user_id=current_user.id,
        )
        if membership is None:
            raise WorkspaceNotFoundError(message=f"Workspace with slug '{workspace_slug}' not found.")

        if membership.role not in allowed_values:
            raise WorkspaceRoleForbiddenError(
                message=(f"Role '{membership.role}' is not permitted; required one of: {sorted(allowed_values)}."),
            )

        workspace_ctx.set(workspace.id)
        return workspace

    return _check


__all__ = (
    "WorkspaceNotMemberError",
    "get_active_workspace_id",
    "get_workspace_by_slug",
    "require_workspace_member",
    "require_workspace_role",
    "workspace_ctx",
)
