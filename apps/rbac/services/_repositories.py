"""Repository bundle consumed by the RBAC services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.rbac.repositories import (
        GroupRepository,
        GroupRoleRepository,
        ObjectPermissionRepository,
        PermissionRepository,
        RolePermissionRepository,
        RoleRepository,
        UserGroupRepository,
        UserRoleRepository,
    )


@dataclass(frozen=True)
class RBACRepositories:
    """Collection of repositories required by the RBAC services.

    Grouped into a single DTO so each service constructor takes one
    dependency instead of many. Frozen — treat as an immutable bag of
    collaborators.
    """

    role: RoleRepository
    permission: PermissionRepository
    group: GroupRepository
    role_permission: RolePermissionRepository
    user_role: UserRoleRepository
    user_group: UserGroupRepository
    group_role: GroupRoleRepository
    object_permission: ObjectPermissionRepository
