"""Role-based repository protocols.

Defines slim, composable Protocols so services can depend on the narrowest
contract they need (Interface Segregation Principle):

* :class:`ReaderProtocol`              — read / query operations
* :class:`WriterProtocol`              — create / update / delete operations
* :class:`UpsertableProtocol`          — find-or-create / get-and-update flows
* :class:`SQLAlchemyRepositoryProtocol` — composite of all three (full CRUD)

Concrete implementations (e.g. :class:`BaseSQLAlchemyRepository`) satisfy the
composite automatically.

Usage::

    class UserReadService:
        def __init__(self, repo: ReaderProtocol[User]) -> None: ...

    class UserCrudService:
        def __init__(self, repo: SQLAlchemyRepositoryProtocol[User]) -> None: ...
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Generic, List, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.sql import ColumnElement

from apps.core.database.sql.filters import StatementFilter
from apps.core.database.sql.types import OrderingPair, SQLAlchemyModelT

__all__ = [
    "ReaderProtocol",
    "RepositoryT",
    "SQLAlchemyRepositoryProtocol",
    "UpsertableProtocol",
    "WriterProtocol",
]


class ReaderProtocol(Protocol[SQLAlchemyModelT], Generic[SQLAlchemyModelT]):
    """Read-only repository surface."""

    async def get_one(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        **kwargs: Any,
    ) -> SQLAlchemyModelT | None: ...

    async def get_one_by_id(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        item_id: Any,
        expunge: bool = True,
    ) -> SQLAlchemyModelT | None: ...

    async def list_items(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        order_by: List[OrderingPair] | OrderingPair | None = None,
        **kwargs: Any,
    ) -> Sequence[SQLAlchemyModelT]: ...

    async def list_and_count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        order_by: List[OrderingPair] | OrderingPair | None = None,
        **kwargs: Any,
    ) -> tuple[Sequence[SQLAlchemyModelT], int]: ...

    async def count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        **kwargs: Any,
    ) -> int: ...


class WriterProtocol(Protocol[SQLAlchemyModelT], Generic[SQLAlchemyModelT]):
    """Write-only repository surface."""

    async def add(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        expunge: bool = True,
    ) -> SQLAlchemyModelT: ...

    async def add_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: Sequence[SQLAlchemyModelT | dict[str, Any]],
        *,
        expunge: bool = True,
    ) -> Sequence[SQLAlchemyModelT]: ...

    async def update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        item_id: Any,
        data: SQLAlchemyModelT | dict[str, Any],
    ) -> SQLAlchemyModelT | None: ...

    async def delete(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        item_id: Any,
    ) -> SQLAlchemyModelT | None: ...

    async def delete_where(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        **kwargs: Any,
    ) -> Sequence[SQLAlchemyModelT] | None: ...


class UpsertableProtocol(Protocol[SQLAlchemyModelT], Generic[SQLAlchemyModelT]):
    """Repository surface for find-or-create / get-and-update flows."""

    async def get_or_upsert(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        upsert: bool = False,
        **kwargs: Any,
    ) -> tuple[SQLAlchemyModelT, bool]: ...

    async def get_and_update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        **kwargs: Any,
    ) -> tuple[SQLAlchemyModelT | None, bool]: ...


class SQLAlchemyRepositoryProtocol(
    ReaderProtocol[SQLAlchemyModelT],
    WriterProtocol[SQLAlchemyModelT],
    UpsertableProtocol[SQLAlchemyModelT],
    Protocol[SQLAlchemyModelT],
):
    """Composite full-CRUD repository protocol.

    Concrete repositories declare their mapped model via ``model_type`` so
    the statement builder can construct queries against the right table.
    """

    model_type: ClassVar[type[SQLAlchemyModelT]]


RepositoryT = TypeVar("RepositoryT", bound="SQLAlchemyRepositoryProtocol")
