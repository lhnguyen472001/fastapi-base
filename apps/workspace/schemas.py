"""Workspace module Pydantic schemas — request validation and response serialization."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema
from apps.workspace.constants import (
    WORKSPACE_DESCRIPTION_MAX_LENGTH,
    WORKSPACE_NAME_MAX_LENGTH,
    WORKSPACE_SLUG_MAX_LENGTH,
    WORKSPACE_SLUG_MIN_LENGTH,
)
from apps.workspace.enums import WorkspaceRole

# ---------------------------------------------------------------------------
# Workspace request / response schemas
# ---------------------------------------------------------------------------


class CreateWorkspaceRequest(RequestObjectSchema):
    """Schema for creating a workspace.

    The authenticated caller becomes the bootstrap owner: a
    :class:`WorkspaceMember` row with role ``owner`` is inserted in the
    same transaction.
    """

    slug: str = Field(
        ...,
        min_length=WORKSPACE_SLUG_MIN_LENGTH,
        max_length=WORKSPACE_SLUG_MAX_LENGTH,
        description="URL-safe lowercase identifier; globally unique.",
    )
    name: str = Field(..., min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=WORKSPACE_DESCRIPTION_MAX_LENGTH)


class UpdateWorkspaceRequest(RequestObjectSchema):
    """Schema for partially updating a workspace.

    Slug is intentionally not editable — changing it would invalidate every
    URL that pins the workspace by slug. Surface a separate "rename slug"
    flow if/when product policy allows it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=WORKSPACE_DESCRIPTION_MAX_LENGTH)


class ListWorkspacesRequest(OffsetPaginationRequestSchema):
    """Query params for listing the caller's workspaces."""

    role: WorkspaceRole | None = Field(default=None, description="Filter by the caller's role.")


class WorkspaceResponse(ResponseObjectSchema):
    """Serialized workspace (without member list)."""

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    owner_user_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------------------------------------------------------------------------
# Workspace member request / response schemas
# ---------------------------------------------------------------------------


class AddMemberRequest(RequestObjectSchema):
    """Schema for adding a member to a workspace.

    The caller must already hold ``owner`` role in the target workspace.
    """

    user_id: uuid.UUID = Field(..., description="User to grant membership.")
    role: WorkspaceRole = Field(..., description="Role to grant the new member.")


class UpdateMemberRoleRequest(RequestObjectSchema):
    """Schema for changing an existing member's role.

    Demoting the last owner is rejected at the service layer
    (:class:`WorkspaceLastOwnerError`).
    """

    role: WorkspaceRole = Field(...)


class ListMembersRequest(OffsetPaginationRequestSchema):
    """Query params for listing members of a workspace."""

    role: WorkspaceRole | None = Field(default=None, description="Filter by role.")


class WorkspaceMemberResponse(ResponseObjectSchema):
    """Serialized membership row."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: WorkspaceRole
    invited_by_user_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
