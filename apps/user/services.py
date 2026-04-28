"""User service: business logic and orchestration for the user module."""

import datetime
import secrets
import uuid
from collections.abc import Sequence

from apps.auth.security import hash_password_async
from apps.core.database.filters import LimitOffsetPaginationFilter
from apps.core.database.types import SessionType
from apps.core.services.base import SQLAlchemyService
from apps.user.exceptions import UserAlreadyExistsError, UserNotFoundError
from apps.user.models import User
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest, ListUsersRequest, UpdateUserRequest


class UserService(SQLAlchemyService[User]):
    """User service.

    Wraps :class:`UserRepository` with the business rules required by the
    user CRUD endpoints: password hashing, uniqueness validation, soft
    delete, and not-found propagation.
    """

    repository: UserRepository

    def __init__(self, repository: UserRepository) -> None:
        """Initialize user service.

        Args:
            repository: User repository.
        """
        super().__init__(repository)

    async def create(self, session: SessionType, *, data: CreateUserRequest) -> User:
        """Create a new user.

        Args:
            session: Database session.
            data: Validated request body.

        Returns:
            The persisted :class:`User` instance.

        Raises:
            UserAlreadyExistsError: If another user with the same email or username
                already exists (excluding soft-deleted rows).
        """
        existing = await self.repository.find_by_email_or_username(session, email=data.email, username=data.username)
        if existing is not None:
            raise UserAlreadyExistsError(
                message=f"User with email '{data.email}' or username '{data.username}' already exists."
            )

        payload: dict = {
            "email": data.email,
            "username": data.username,
            "hashed_password": await hash_password_async(data.password),
            # New users start INACTIVE — must verify email via OTP first.
            "is_active": False,
        }
        return await self.repository.add(session, payload, expunge=False)

    async def get_or_create_oauth_user(
        self,
        session: SessionType,
        *,
        email: str,
        username_hint: str,
        google_sub: str,
    ) -> User:
        """Find an existing user by ``google_sub`` or ``email``; create one if missing.

        OAuth users are created **active** because the upstream provider
        (Google) has already verified the email address. The local password
        is set to a random unguessable value so password login is impossible
        for these accounts unless the user later runs a password-reset flow.

        If a user already exists by email but is not yet linked to Google,
        we link by setting ``google_sub`` and marking the email verified.

        Args:
            session: Database session.
            email: Verified email from the OAuth provider.
            username_hint: Suggested username (typically email local part).
            google_sub: The provider's stable subject identifier.

        Returns:
            The persisted :class:`User` instance.
        """
        # 1. Already linked? Return as-is.
        existing = await self.repository.find_by_email_or_username(session, email=email)
        if existing is not None:
            if existing.google_sub is None:
                existing.google_sub = google_sub
            if existing.email_verified_at is None:
                existing.email_verified_at = datetime.datetime.now(datetime.UTC)
            if not existing.is_active:
                existing.is_active = True
            return existing

        # 2. Brand new user — derive a unique username from the hint.
        username = await self._unique_username(session, username_hint)
        random_password = secrets.token_urlsafe(32)

        payload: dict = {
            "email": email,
            "username": username,
            "hashed_password": await hash_password_async(random_password),
            "is_active": True,
            "email_verified_at": datetime.datetime.now(datetime.UTC),
            "google_sub": google_sub,
        }
        return await self.repository.add(session, payload, expunge=False)

    async def _unique_username(self, session: SessionType, hint: str) -> str:
        """Disambiguate a username by appending random suffixes on collision."""
        candidate = hint
        for _ in range(5):
            collision = await self.repository.find_by_email_or_username(session, username=candidate)
            if collision is None:
                return candidate
            candidate = f"{hint}_{secrets.token_hex(3)}"
        # 5 collisions in a row is astronomically unlikely; fall back to a
        # fully random username.
        return f"user_{secrets.token_hex(8)}"

    async def find_or_raise(self, session: SessionType, *, user_id: uuid.UUID) -> User:
        """Fetch a user by ID or raise; excludes soft-deleted rows.

        Distinct name from the base ``get_by_id`` (which returns ``T | None``)
        to avoid the LSP violation that an override otherwise introduces.

        Args:
            session: Database session.
            user_id: The user's primary key.

        Returns:
            The :class:`User` instance.

        Raises:
            UserNotFoundError: If no active user matches the given ID.
        """
        user = await self.repository.find_by_id(session, user_id=user_id)
        if user is None:
            raise UserNotFoundError(message=f"User with id '{user_id}' not found.")
        return user

    async def list_users(self, session: SessionType, *, params: ListUsersRequest) -> tuple[Sequence[User], int]:
        """List active users with pagination and optional filters.

        Args:
            session: Database session.
            params: Pagination + filter parameters from the request.

        Returns:
            ``(items, total)`` — page of users plus the total count after filters.
        """
        filter_kwargs: dict = {}
        if params.is_active is not None:
            filter_kwargs["is_active"] = params.is_active

        return await self.repository.list_and_count(
            session,
            LimitOffsetPaginationFilter(limit=params.limit, offset=params.offset),
            **filter_kwargs,
        )

    async def update(self, session: SessionType, *, user_id: uuid.UUID, data: UpdateUserRequest) -> User:
        """Update an existing user.

        Args:
            session: Database session.
            user_id: The user's primary key.
            data: Partial update payload (only set fields are applied).

        Returns:
            The updated :class:`User` instance.

        Raises:
            UserNotFoundError: If the user does not exist or is soft-deleted.
            UserAlreadyExistsError: If the new email or username collides with
                another active user.
        """
        await self.get_by_id(session, user_id=user_id)

        if data.email is not None or data.username is not None:
            conflict = await self.repository.find_by_email_or_username(
                session,
                email=data.email,
                username=data.username,
                exclude_id=user_id,
            )
            if conflict is not None:
                raise UserAlreadyExistsError(message="Another user already uses this email or username.")

        update_payload = data.model_dump(exclude_unset=True)
        if "password" in update_payload:
            update_payload["hashed_password"] = await hash_password_async(update_payload.pop("password"))

        updated = await self.repository.update(session, item_id=user_id, data=update_payload)
        if updated is None:
            # Defensive: get_by_id above already guarantees existence, but the
            # update path could still return None if the row was deleted between
            # the two queries.
            raise UserNotFoundError(message=f"User with id '{user_id}' not found.")
        return updated

    async def soft_delete(self, session: SessionType, *, user_id: uuid.UUID) -> User:
        """Soft-delete a user by setting ``deleted_at`` to the current UTC time.

        Args:
            session: Database session.
            user_id: The user's primary key.

        Returns:
            The soft-deleted :class:`User` instance.

        Raises:
            UserNotFoundError: If the user does not exist or is already soft-deleted.
        """
        user = await self.get_by_id(session, user_id=user_id)
        user.deleted_at = datetime.datetime.now(datetime.UTC)
        return user

    async def get_by_email_or_username(
        self,
        session: SessionType,
        *,
        email: str | None = None,
        username: str | None = None,
    ) -> User | None:
        """Look up a user by email or username (used by the future auth module)."""
        return await self.repository.find_by_email_or_username(session, username=username, email=email)
