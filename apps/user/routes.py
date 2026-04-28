"""User CRUD endpoints."""

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.session import session_factory
from apps.core.schemas.response import (
    APIResponse,
    PaginatedResponse,
)
from apps.user.containers import UserContainer
from apps.user.schemas import (
    CreateUserRequest,
    ListUsersRequest,
    UpdateUserRequest,
    UserResponse,
)
from apps.user.services import UserService

user_router = APIRouter(prefix="/users", tags=["users"])


@user_router.post(
    "",
    response_model=APIResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_user(
    data: CreateUserRequest,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Create a new user."""
    user = await user_service.create(session, data=data)
    return APIResponse[UserResponse].success(
        data=UserResponse.model_validate(user), message="User created successfully."
    )


@user_router.get("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Get a user by ID."""
    user = await user_service.find_or_raise(session, user_id=user_id)
    return APIResponse[UserResponse].success(
        data=UserResponse.model_validate(user), message="User retrieved successfully."
    )


@user_router.get("", response_model=APIResponse[PaginatedResponse[UserResponse]])
@inject
async def list_users(
    params: ListUsersRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[PaginatedResponse[UserResponse]]:
    """List users with pagination."""
    items, total = await user_service.list_users(session, params=params)
    return APIResponse[PaginatedResponse[UserResponse]].success(
        data=PaginatedResponse[UserResponse](
            items=[UserResponse.model_validate(u) for u in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Users retrieved successfully.",
    )


@user_router.patch("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def update_user(
    user_id: uuid.UUID,
    data: UpdateUserRequest,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Update an existing user."""
    user = await user_service.update(session, user_id=user_id, data=data)
    return APIResponse[UserResponse].success(
        data=UserResponse.model_validate(user), message="User updated successfully."
    )


@user_router.delete("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    """Soft-delete a user."""
    user = await user_service.soft_delete(session, user_id=user_id)
    return APIResponse[UserResponse].success(
        data=UserResponse.model_validate(user), message="User deleted successfully."
    )
