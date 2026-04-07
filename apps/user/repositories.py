import uuid
from typing import Protocol

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.sql.repository import BaseSQLAlchemyRepository
from apps.user.models import User


class UserRepositoryProtocol(Protocol):
    """Interface for User repository operations."""

    async def find_by_id(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> User | None: ...

    async def find_by_email_or_username(
        self,
        session: AsyncSession,
        *,
        email: str | None = None,
        username: str | None = None,
        exclude_id: uuid.UUID | None = None,
    ) -> User | None: ...


class UserRepository(BaseSQLAlchemyRepository[User]):
    """Concrete repository for User model operations."""

    model_type = User

    async def find_by_id(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> User | None:
        """Find a user by ID."""
        stmt = self.filter_select_by_kwargs(self.statement, {"id": user_id})
        if not include_deleted:
            stmt = self.apply_filter(stmt, User.deleted_at.is_(None))

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_email_or_username(
        self,
        session: AsyncSession,
        *,
        email: str | None = None,
        username: str | None = None,
        exclude_id: uuid.UUID | None = None,
    ) -> User | None:
        """Find a user matching email or username, optionally excluding a specific ID."""
        conditions = []
        if email is not None:
            conditions.append(User.email == email)
        if username is not None:
            conditions.append(User.username == username)

        if not conditions:
            return None

        stmt = self.apply_filter(
            self.statement, or_(*conditions), User.deleted_at.is_(None)
        )
        if exclude_id is not None:
            stmt = self.apply_filter(stmt, User.id != exclude_id)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()
