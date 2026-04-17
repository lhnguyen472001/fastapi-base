"""Pydantic schemas for the RBAC module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from apps.core.schemas.base import BaseObjectSchema

if TYPE_CHECKING:
    import uuid

# ---- Roles -----------------------------------------------------------------


class CreateRoleRequest(BaseObjectSchema):
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    parent_id: int | None = None
    level: int = Field(default=0, ge=0, le=10)


class RoleResponse(BaseObjectSchema):
    id: int
    name: str
    display_name: str
    description: str | None
    parent_id: int | None
    level: int
    is_system: bool
    is_active: bool


# ---- Permissions -----------------------------------------------------------


class CreatePermissionRequest(BaseObjectSchema):
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=50)
    description: str | None = None
    category: str | None = Field(default=None, max_length=50)


class PermissionResponse(BaseObjectSchema):
    id: int
    name: str
    display_name: str
    resource: str
    action: str
    category: str | None
    is_system: bool
    is_active: bool


# ---- Groups ----------------------------------------------------------------


class CreateGroupRequest(BaseObjectSchema):
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    parent_id: int | None = None
    level: int = Field(default=0, ge=0, le=10)


class GroupResponse(BaseObjectSchema):
    id: int
    name: str
    display_name: str
    description: str | None
    parent_id: int | None
    level: int
    is_system: bool
    is_active: bool


# ---- Assignments -----------------------------------------------------------


class GrantPermissionRequest(BaseObjectSchema):
    role_id: int
    permission_id: int


class AssignRoleToUserRequest(BaseObjectSchema):
    user_id: uuid.UUID
    role_id: int


class AddUserToGroupRequest(BaseObjectSchema):
    user_id: uuid.UUID
    group_id: int


class AssignRoleToGroupRequest(BaseObjectSchema):
    group_id: int
    role_id: int


# ---- Per-object grants -----------------------------------------------------


class GrantObjectPermissionRequest(BaseObjectSchema):
    user_id: uuid.UUID
    resource: str = Field(..., min_length=1, max_length=100)
    object_id: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=50)


class RevokeObjectPermissionRequest(BaseObjectSchema):
    user_id: uuid.UUID
    resource: str = Field(..., min_length=1, max_length=100)
    object_id: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=50)
