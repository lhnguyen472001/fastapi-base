import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.user.models import User
from libs.database.sql.filters import LimitOffsetPaginationFilter
from libs.database.sql.repository import BaseSQLAlchemyRepository


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

    async def list_and_count(
        self,
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[User], int]: ...

    async def create(self, session: AsyncSession, *, user: User) -> User: ...

    async def save(self, session: AsyncSession, *, user: User) -> User: ...


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

        stmt = self.apply_filter(self.statement, or_(*conditions))
        if exclude_id is not None:
            stmt = self.apply_filter(stmt, User.id != exclude_id)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_and_count(
        self,
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[User], int]:
        """List non-deleted users with pagination and total count."""
        stmt = self.apply_filter(self.statement, User.deleted_at.is_(None))

        if is_active is not None:
            stmt = self.apply_filter(stmt, User.is_active == is_active)

        # Count before pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        # Paginate
        stmt = self.apply_filter(
            stmt, LimitOffsetPaginationFilter(limit=limit, offset=offset)
        )

        result = await session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, session: AsyncSession, *, user: User) -> User:
        """Persist a new user."""
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def save(self, session: AsyncSession, *, user: User) -> User:
        """Flush and refresh a modified user."""
        await session.flush()
        await session.refresh(user)
        return user
