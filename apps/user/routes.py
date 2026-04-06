import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.user.containers import UserContainer
from apps.user.schemas import CreateUserRequest, ListUsersRequest, UpdateUserRequest, UserResponse
from apps.user.services import UserService
from libs.database.sql.session import session_factory
from libs.schemas.response import APIResponse, JsonResponseStatuses, PaginatedResponse, ResponseCodes

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=APIResponse[UserResponse], status_code=201)
@inject
async def create_user(
    data: CreateUserRequest,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Create a new user."""
    user = await service.create_user(session, data=data)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User created successfully.",
    )


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Get a user by ID."""
    user = await service.get_user(session, user_id=user_id)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User retrieved successfully.",
    )


@router.get("", response_model=APIResponse[PaginatedResponse[UserResponse]])
@inject
async def list_users(
    params: ListUsersRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[PaginatedResponse[UserResponse]]:
    """List users with pagination."""
    result = await service.list_users(session, params=params)
    return APIResponse[PaginatedResponse[UserResponse]](
        code=ResponseCodes.API000,
        data=result,
        status=JsonResponseStatuses.SUCCESS,
        message="Users retrieved successfully.",
    )


@router.patch("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def update_user(
    user_id: uuid.UUID,
    data: UpdateUserRequest,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Update an existing user."""
    user = await service.update_user(session, user_id=user_id, data=data)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User updated successfully.",
    )


@router.delete("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Soft-delete a user."""
    user = await service.delete_user(session, user_id=user_id)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User deleted successfully.",
    )
