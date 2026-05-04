"""Workspace HTTP routes — workspace CRUD and member management.

Routes split into two concern groups:

* **Self-service** (``/workspaces`` root) — list-mine, create. Auth required;
  no path-bound workspace yet.
* **Workspace-scoped** (``/workspaces/{workspace_slug}``) — read, update,
  soft-delete, member sub-routes. Each route uses
  :func:`apps.workspace.dependencies.require_workspace_role` to gate access.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from apps.auth.dependencies import get_current_user
from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.workspace.containers import WorkspaceContainer
from apps.workspace.dependencies import require_workspace_member, require_workspace_role
from apps.workspace.enums import WorkspaceRole
from apps.workspace.schemas import (
    AddMemberRequest,
    CreateWorkspaceRequest,
    ListMembersRequest,
    ListWorkspacesRequest,
    UpdateMemberRoleRequest,
    UpdateWorkspaceRequest,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.user.models import User
    from apps.workspace.models import Workspace
    from apps.workspace.services import WorkspaceMemberService, WorkspaceService

workspace_router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# ---------------------------------------------------------------------------
# Self-service workspace endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("", response_model=APIResponse[PaginatedResponse[WorkspaceResponse]])
@inject
async def list_my_workspaces(
    params: ListWorkspacesRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
) -> APIResponse[PaginatedResponse[WorkspaceResponse]]:
    """List workspaces the authenticated caller belongs to."""
    items, total = await workspace_service.list_for_user(
        session,
        user_id=current_user.id,
        params=params,
    )
    return APIResponse[PaginatedResponse[WorkspaceResponse]].success(
        data=PaginatedResponse[WorkspaceResponse](
            items=[WorkspaceResponse.model_validate(w) for w in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Workspaces retrieved successfully.",
    )


@workspace_router.post(
    "",
    response_model=APIResponse[WorkspaceResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_workspace(
    data: CreateWorkspaceRequest,
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
) -> APIResponse[WorkspaceResponse]:
    """Create a workspace and seat the caller as its bootstrap owner."""
    workspace = await workspace_service.create(
        session,
        owner_user_id=current_user.id,
        data=data,
    )
    return APIResponse[WorkspaceResponse].success(
        data=WorkspaceResponse.model_validate(workspace),
        message="Workspace created successfully.",
    )


# ---------------------------------------------------------------------------
# Workspace-scoped endpoints
# ---------------------------------------------------------------------------


@workspace_router.get(
    "/{workspace_slug}",
    response_model=APIResponse[WorkspaceResponse],
)
async def get_workspace(
    workspace: Workspace = Depends(require_workspace_member()),
) -> APIResponse[WorkspaceResponse]:
    """Fetch a single workspace by slug. Caller must be a member."""
    return APIResponse[WorkspaceResponse].success(
        data=WorkspaceResponse.model_validate(workspace),
        message="Workspace retrieved successfully.",
    )


@workspace_router.patch(
    "/{workspace_slug}",
    response_model=APIResponse[WorkspaceResponse],
)
@inject
async def update_workspace(
    data: UpdateWorkspaceRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER)),
    session: AsyncSession = Depends(session_factory),
    workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
) -> APIResponse[WorkspaceResponse]:
    """Update workspace metadata. Owner-only."""
    updated = await workspace_service.update(
        session,
        workspace_id=workspace.id,
        data=data,
    )
    return APIResponse[WorkspaceResponse].success(
        data=WorkspaceResponse.model_validate(updated),
        message="Workspace updated successfully.",
    )


@workspace_router.delete(
    "/{workspace_slug}",
    response_model=APIResponse[WorkspaceResponse],
)
@inject
async def delete_workspace(
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER)),
    session: AsyncSession = Depends(session_factory),
    workspace_service: WorkspaceService = Depends(Provide[WorkspaceContainer.workspace_service]),
) -> APIResponse[WorkspaceResponse]:
    """Soft-delete a workspace. Owner-only."""
    deleted = await workspace_service.soft_delete(session, workspace_id=workspace.id)
    return APIResponse[WorkspaceResponse].success(
        data=WorkspaceResponse.model_validate(deleted),
        message="Workspace deleted successfully.",
    )


# ---------------------------------------------------------------------------
# Workspace member endpoints
# ---------------------------------------------------------------------------


@workspace_router.get(
    "/{workspace_slug}/members",
    response_model=APIResponse[PaginatedResponse[WorkspaceMemberResponse]],
)
@inject
async def list_workspace_members(
    params: ListMembersRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
) -> APIResponse[PaginatedResponse[WorkspaceMemberResponse]]:
    """List members of the workspace. Any member can view."""
    items, total = await member_service.list_members(
        session,
        workspace_id=workspace.id,
        params=params,
    )
    return APIResponse[PaginatedResponse[WorkspaceMemberResponse]].success(
        data=PaginatedResponse[WorkspaceMemberResponse](
            items=[WorkspaceMemberResponse.model_validate(m) for m in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Workspace members retrieved successfully.",
    )


@workspace_router.post(
    "/{workspace_slug}/members",
    response_model=APIResponse[WorkspaceMemberResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def add_workspace_member(
    data: AddMemberRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER)),
    session: AsyncSession = Depends(session_factory),
    current_user: User = Depends(get_current_user),
    member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
) -> APIResponse[WorkspaceMemberResponse]:
    """Add a member to the workspace. Owner-only."""
    member = await member_service.add_member(
        session,
        workspace_id=workspace.id,
        invited_by_user_id=current_user.id,
        data=data,
    )
    return APIResponse[WorkspaceMemberResponse].success(
        data=WorkspaceMemberResponse.model_validate(member),
        message="Workspace member added successfully.",
    )


@workspace_router.patch(
    "/{workspace_slug}/members/{user_id}",
    response_model=APIResponse[WorkspaceMemberResponse],
)
@inject
async def change_workspace_member_role(
    user_id: uuid.UUID,
    data: UpdateMemberRoleRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER)),
    session: AsyncSession = Depends(session_factory),
    member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
) -> APIResponse[WorkspaceMemberResponse]:
    """Change a member's role. Owner-only; cannot demote the last owner."""
    member = await member_service.change_role(
        session,
        workspace_id=workspace.id,
        user_id=user_id,
        data=data,
    )
    return APIResponse[WorkspaceMemberResponse].success(
        data=WorkspaceMemberResponse.model_validate(member),
        message="Workspace member role updated successfully.",
    )


@workspace_router.delete(
    "/{workspace_slug}/members/{user_id}",
    response_model=APIResponse[WorkspaceMemberResponse],
)
@inject
async def remove_workspace_member(
    user_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER)),
    session: AsyncSession = Depends(session_factory),
    member_service: WorkspaceMemberService = Depends(Provide[WorkspaceContainer.workspace_member_service]),
) -> APIResponse[WorkspaceMemberResponse]:
    """Remove a member from the workspace. Owner-only; cannot remove the last owner."""
    member = await member_service.remove_member(
        session,
        workspace_id=workspace.id,
        user_id=user_id,
    )
    return APIResponse[WorkspaceMemberResponse].success(
        data=WorkspaceMemberResponse.model_validate(member),
        message="Workspace member removed successfully.",
    )
