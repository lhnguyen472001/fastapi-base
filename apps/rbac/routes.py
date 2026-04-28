"""Admin RBAC endpoints.

All mutating endpoints are gated by ``Depends(access_required("rbac",
"manage"))`` so only users carrying that permission may modify policies.
The bootstrap (initial superadmin) is expected to be seeded out-of-band,
e.g. via an Alembic data migration or a CLI command.
"""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.session import session_factory
from apps.core.schemas.response import (
    APIResponse,
)
from apps.rbac.containers import RBACContainer
from apps.rbac.dependencies import access_required
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
from apps.rbac.services import RBACService
from apps.user.models import User

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.post(
    "/roles",
    response_model=APIResponse[RoleResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_role(
    data: CreateRoleRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    _: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[RoleResponse]:
    role = await rbac_service.create_role(
        session,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        parent_id=data.parent_id,
        level=data.level,
    )
    return APIResponse[RoleResponse].success(data=RoleResponse.model_validate(role), message="Role created.")


@router.post(
    "/permissions",
    response_model=APIResponse[PermissionResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_permission(
    data: CreatePermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    _: User = Depends(access_required("rbac", "manage")),
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
    return APIResponse[PermissionResponse].success(
        data=PermissionResponse.model_validate(perm), message="Permission created."
    )


@router.post(
    "/groups",
    response_model=APIResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_group(
    data: CreateGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    _: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[GroupResponse]:
    group = await rbac_service.create_group(
        session,
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        parent_id=data.parent_id,
        level=data.level,
    )
    return APIResponse[GroupResponse].success(data=GroupResponse.model_validate(group), message="Group created.")


@router.post("/role-permissions", status_code=status.HTTP_201_CREATED)
@inject
async def grant_permission(
    data: GrantPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    current_user: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[None]:
    await rbac_service.grant_permission_to_role(
        session,
        role_id=data.role_id,
        permission_id=data.permission_id,
        granted_by=current_user.id,
    )
    return APIResponse[None].success(data=None, message="Permission granted.")


@router.post("/user-roles", status_code=status.HTTP_201_CREATED)
@inject
async def assign_role_to_user(
    data: AssignRoleToUserRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    current_user: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[None]:
    await rbac_service.assign_role_to_user(
        session,
        user_id=data.user_id,
        role_id=data.role_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None].success(data=None, message="Role assigned.")


@router.post("/user-groups", status_code=status.HTTP_201_CREATED)
@inject
async def add_user_to_group(
    data: AddUserToGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    current_user: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[None]:
    await rbac_service.add_user_to_group(
        session,
        user_id=data.user_id,
        group_id=data.group_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None].success(data=None, message="User added to group.")


@router.post("/group-roles", status_code=status.HTTP_201_CREATED)
@inject
async def assign_role_to_group(
    data: AssignRoleToGroupRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    current_user: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[None]:
    await rbac_service.assign_role_to_group(
        session,
        group_id=data.group_id,
        role_id=data.role_id,
        assigned_by=current_user.id,
    )
    return APIResponse[None].success(data=None, message="Role assigned to group.")


@router.post("/object-permissions", status_code=status.HTTP_201_CREATED)
@inject
async def grant_object_permission(
    data: GrantObjectPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    current_user: User = Depends(access_required("rbac", "manage")),
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
    return APIResponse[None].success(data=None, message="Object permission granted.")


@router.delete("/object-permissions", status_code=status.HTTP_200_OK)
@inject
async def revoke_object_permission(
    data: RevokeObjectPermissionRequest,
    session: AsyncSession = Depends(session_factory),
    rbac_service: RBACService = Depends(Provide[RBACContainer.rbac_service]),
    _: User = Depends(access_required("rbac", "manage")),
) -> APIResponse[None]:
    """Revoke a previously granted per-object permission."""
    await rbac_service.revoke_object_permission(
        session,
        user_id=data.user_id,
        resource=data.resource,
        object_id=data.object_id,
        action=data.action,
    )
    return APIResponse[None].success(data=None, message="Object permission revoked.")
