import uuid
from typing import Any

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from apps.user.exceptions import UserAlreadyExistsError, UserNotFoundError
from apps.user.models import User
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest, ListUsersRequest, UpdateUserRequest, UserResponse
from libs.schemas.response import PaginatedResponse


class UserService:
    """Service layer for User CRUD operations."""

    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a plain text password using bcrypt."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    async def create_user(self, session: AsyncSession, *, data: CreateUserRequest) -> UserResponse:
        """Create a new user.

        Args:
            session: Database session.
            data: User creation data.

        Returns:
            Created user response.

        Raises:
            UserAlreadyExistsError: If email or username already taken.
        """
        existing = await self.repository.find_by_email_or_username(
            session, email=data.email, username=data.username
        )
        if existing is not None:
            raise UserAlreadyExistsError(
                message=f"User with email '{data.email}' or username '{data.username}' already exists."
            )

        user = User(
            email=data.email,
            username=data.username,
            hashed_password=self._hash_password(data.password),
        )
        user = await self.repository.create(session, user=user)

        return UserResponse.model_validate(user)

    async def get_user(self, session: AsyncSession, *, user_id: uuid.UUID) -> UserResponse:
        """Get a user by ID.

        Args:
            session: Database session.
            user_id: The user's UUID.

        Returns:
            User response.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        user = await self.repository.find_by_id(session, user_id=user_id)
        if user is None:
            raise UserNotFoundError()

        return UserResponse.model_validate(user)

    async def list_users(
        self,
        session: AsyncSession,
        *,
        params: ListUsersRequest,
    ) -> PaginatedResponse[UserResponse]:
        """List users with pagination and optional filtering.

        Args:
            session: Database session.
            params: Pagination and filter parameters.

        Returns:
            Paginated user response.
        """
        users, total = await self.repository.list_and_count(
            session, is_active=params.is_active, limit=params.limit, offset=params.offset
        )

        return PaginatedResponse[UserResponse](
            items=[UserResponse.model_validate(u) for u in users],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    async def update_user(
        self, session: AsyncSession, *, user_id: uuid.UUID, data: UpdateUserRequest
    ) -> UserResponse:
        """Update an existing user.

        Args:
            session: Database session.
            user_id: The user's UUID.
            data: Fields to update.

        Returns:
            Updated user response.

        Raises:
            UserNotFoundError: If user does not exist.
            UserAlreadyExistsError: If email or username conflict.
        """
        user = await self.repository.find_by_id(session, user_id=user_id)
        if user is None:
            raise UserNotFoundError()

        update_data: dict[str, Any] = data.model_dump(exclude_unset=True)

        # Check uniqueness for email/username if being changed
        if "email" in update_data or "username" in update_data:
            conflict = await self.repository.find_by_email_or_username(
                session,
                email=update_data.get("email"),
                username=update_data.get("username"),
                exclude_id=user_id,
            )
            if conflict is not None:
                raise UserAlreadyExistsError()

        # Hash password if provided
        if "password" in update_data:
            update_data["hashed_password"] = self._hash_password(update_data.pop("password"))

        for field, value in update_data.items():
            setattr(user, field, value)

        user = await self.repository.save(session, user=user)

        return UserResponse.model_validate(user)

    async def delete_user(self, session: AsyncSession, *, user_id: uuid.UUID) -> UserResponse:
        """Soft-delete a user.

        Args:
            session: Database session.
            user_id: The user's UUID.

        Returns:
            Deleted user response.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        user = await self.repository.find_by_id(session, user_id=user_id)
        if user is None:
            raise UserNotFoundError()

        user.delete()
        user = await self.repository.save(session, user=user)

        return UserResponse.model_validate(user)
