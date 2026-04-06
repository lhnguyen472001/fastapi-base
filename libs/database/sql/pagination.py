"""Pagination utilities for repository operations."""

from typing import Any, Generic, Literal, Self, Sequence

from pydantic import ConfigDict, Field, dataclasses, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from .types import SQLAlchemyModelT


@dataclasses.dataclass(frozen=True, kw_only=True)
class PaginationParams:
    """Parameters for pagination."""

    page: int = Field(default=1, ge=1)
    """Page number (1-based)."""

    size: int = Field(default=20, gt=0, le=100)
    """Number of items per page."""

    max_size: int = Field(default=100, gt=0)
    """Maximum allowed page size."""

    @property
    def offset(self) -> int:
        """Calculate offset for database query."""
        return (self.page - 1) * self.size

    @model_validator(mode="after")
    def validate_size(self) -> Self:
        """Validate the page size. If it exceeds the maximum size, raise a ValueError."""
        if self.size > self.max_size:
            raise ValueError(f"Page size {self.size} cannot exceed {self.max_size}")
        return self


@dataclasses.dataclass(frozen=True, kw_only=True, config=ConfigDict(arbitrary_types_allowed=True))
class PagedResult(Generic[SQLAlchemyModelT]):
    """Result of a paginated query."""

    items: Sequence[SQLAlchemyModelT] = Field(default_factory=list)
    """Items on current page."""

    total: int = Field(default=0)
    """Total number of items across all pages."""

    page: int = Field(default=1)
    """Current page number."""

    size: int = Field(default=20)
    """Items per page."""

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        return (self.total + self.size - 1) // self.size

    @property
    def has_next(self) -> bool:
        """Whether there's a next page."""
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        """Whether there's a previous page."""
        return self.page > 1

    @property
    def next_page(self) -> int | None:
        """Next page number if available."""
        return self.page + 1 if self.has_next else None

    @property
    def previous_page(self) -> int | None:
        """Previous page number if available."""
        return self.page - 1 if self.has_previous else None


class PaginationHelper:
    """Helper class for pagination operations."""

    @staticmethod
    async def paginate(
        session: AsyncSession,
        query: Select[tuple[SQLAlchemyModelT]],
        pagination: PaginationParams,
        count_query: Select[tuple[int]] | None = None,
    ) -> PagedResult[SQLAlchemyModelT]:
        """Execute paginated query and return results with metadata.

        Args:
            session: Database session
            query: Main query to paginate
            pagination: Pagination parameters
            count_query: Custom count query (optional)

        Returns:
            Paginated result with items and metadata
        """
        # Execute count query
        if count_query is None:
            # Create count query from main query
            count_query = select(func.count()).select_from(query.subquery())

        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        # Execute paginated query
        paginated_query = query.offset(pagination.offset).limit(pagination.size)
        result = await session.execute(paginated_query)
        items = list(result.scalars().all())

        return PagedResult(items=items, total=total, page=pagination.page, size=pagination.size)  # type: ignore[call-arg]

    @staticmethod
    def apply_pagination(
        query: Select[tuple[SQLAlchemyModelT]],
        pagination: PaginationParams,
    ) -> Select[tuple[SQLAlchemyModelT]]:
        """Apply pagination to a query."""
        return query.offset(pagination.offset).limit(pagination.size)


# Cursor-based pagination for better performance with large datasets
@dataclasses.dataclass(frozen=True, kw_only=True)
class CursorParams:
    """Parameters for cursor-based pagination."""

    cursor: Any | None = Field(default=None)
    """Cursor value for pagination."""

    size: int = Field(default=20, ge=1, le=100)
    """Number of items to fetch."""

    direction: Literal["next", "previous"] = Field(default="next")
    """Direction: 'next' or 'previous'."""


@dataclasses.dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class CursorResult(Generic[SQLAlchemyModelT]):
    """Result of cursor-based pagination."""

    items: Sequence[SQLAlchemyModelT]
    """Items in current page."""

    next_cursor: Any | None
    """Cursor for next page."""

    previous_cursor: Any | None
    """Cursor for previous page."""

    has_next: bool = Field(default=False)
    """Whether there are more items."""


class CursorPagination:
    """Cursor-based pagination for efficient handling of large datasets."""

    @staticmethod
    def paginate_by_cursor(
        query: Select[tuple[SQLAlchemyModelT]],
        cursor_field: str,
        params: CursorParams,
    ) -> Select[tuple[SQLAlchemyModelT]]:
        """Apply cursor-based pagination to query."""
        if params.cursor is not None:
            if params.direction == "next" and params:
                query = query.where(getattr(query.column_descriptions[0]["type"], cursor_field) > params.cursor)
            else:  # previous
                query = query.where(getattr(query.column_descriptions[0]["type"], cursor_field) < params.cursor)

        return query.limit(params.size + 1)  # +1 to check if there are more items
