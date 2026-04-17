"""Admin RBAC endpoints.

All mutating endpoints are protected by ``require_access("rbac", "manage")``
so only users carrying that permission may modify policies. The bootstrap
(initial superadmin) is expected to be seeded out-of-band, e.g. via an
Alembic data migration or a CLI command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from apps.auth.dependencies import get_current_user
from apps.core.database.session import session_factory
from apps.core.schemas.response import (
    APIResponse,
    JsonResponseStatuses,
    ResponseCodes,
)
from apps.rbac.containers import RBACContainer
from apps.rbac.decorators import require_access
from apps.rbac.schemas import (
    AddUserToGroupRequest,
    AssignRoleToGroupRequest,
    AssignRoleToUserRequest,
    CreateGroupRequest,
    CreatePermissionRequest,
    CreateRoleRequest,
    GrantObjectPermissionRequest,
    GrantPermissionRequest,
    GroupResponse,
    PermissionResponse,
    RevokeObjectPermissionRequest,
    RoleResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.rbac.services import AccessService, RBACService
    from apps.user.models import User

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.post(
    "/roles",
    response_model=APIResponse[RoleResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
@require_access("rbac", "manage")
async def create_role(
    data: CreateRoleRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[RoleResponse]:
    role = await rbac_service.create_role(
        session,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        parent_id=data.parent_id,
        level=data.level,
    )
    return APIResponse[RoleResponse](
        code=ResponseCodes.API000,
        data=RoleResponse.model_validate(role),
        status=JsonResponseStatuses.SUCCESS,
        message="Role created.",
    )


@router.post(
    "/permissions",
    response_model=APIResponse[PermissionResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
@require_access("rbac", "manage")
async def create_permission(
    data: CreatePermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[PermissionResponse]:
    perm = await rbac_service.create_permission(
        session,
        name=data.name,
        display_name=data.display_name,
        resource=data.resource,
        action=data.action,
        description=data.description,
        category=data.category,
    )
    return APIResponse[PermissionResponse](
        code=ResponseCodes.API000,
        data=PermissionResponse.model_validate(perm),
        status=JsonResponseStatuses.SUCCESS,
        message="Permission created.",
    )


@router.post(
    "/groups",
    response_model=APIResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
@require_access("rbac", "manage")
async def create_group(
    data: CreateGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[GroupResponse]:
    group = await rbac_service.create_group(
        session,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        parent_id=data.parent_id,
        level=data.level,
    )
    return APIResponse[GroupResponse](
        code=ResponseCodes.API000,
        data=GroupResponse.model_validate(group),
        status=JsonResponseStatuses.SUCCESS,
        message="Group created.",
    )


@router.post("/role-permissions", status_code=status.HTTP_201_CREATED)
@inject
@require_access("rbac", "manage")
async def grant_permission(
    data: GrantPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),
) -> APIResponse[None]:
    await rbac_service.grant_permission_to_role(
        session,
        role_id=data.role_id,
        permission_id=data.permission_id,
        granted_by=current_user.id,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="Permission granted.",
    )


@router.post("/user-roles", status_code=status.HTTP_201_CREATED)
@inject
@require_access("rbac", "manage")
async def assign_role_to_user(
    data: AssignRoleToUserRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),
) -> APIResponse[None]:
    await rbac_service.assign_role_to_user(
        session,
        user_id=data.user_id,
        role_id=data.role_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="Role assigned.",
    )


@router.post("/user-groups", status_code=status.HTTP_201_CREATED)
@inject
@require_access("rbac", "manage")
async def add_user_to_group(
    data: AddUserToGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),
) -> APIResponse[None]:
    await rbac_service.add_user_to_group(
        session,
        user_id=data.user_id,
        group_id=data.group_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="User added to group.",
    )


@router.post("/group-roles", status_code=status.HTTP_201_CREATED)
@inject
@require_access("rbac", "manage")
async def assign_role_to_group(
    data: AssignRoleToGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),
) -> APIResponse[None]:
    await rbac_service.assign_role_to_group(
        session,
        group_id=data.group_id,
        role_id=data.role_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="Role assigned to group.",
    )


@router.post("/object-permissions", status_code=status.HTTP_201_CREATED)
@inject
@require_access("rbac", "manage")
async def grant_object_permission(
    data: GrantObjectPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),
) -> APIResponse[None]:
    """Grant ``user_id`` the right to ``action`` on a specific instance
    identified by ``(resource, object_id)``."""
    await rbac_service.grant_object_permission(
        session,
        user_id=data.user_id,
        resource=data.resource,
        object_id=data.object_id,
        action=data.action,
        granted_by=current_user.id,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="Object permission granted.",
    )


@router.delete("/object-permissions", status_code=status.HTTP_200_OK)
@inject
@require_access("rbac", "manage")
async def revoke_object_permission(
    data: RevokeObjectPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[None]:
    """Revoke a previously granted per-object permission."""
    await rbac_service.revoke_object_permission(
        session,
        user_id=data.user_id,
        resource=data.resource,
        object_id=data.object_id,
        action=data.action,
    )
    return APIResponse[None](
        code=ResponseCodes.API000,
        data=None,
        status=JsonResponseStatuses.SUCCESS,
        message="Object permission revoked.",
    )
