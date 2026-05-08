"""Read-side methods of :class:`BaseSQLAlchemyRepository`.

Composed into the public class via multiple inheritance. The mixin assumes
its host provides the identity attributes (``self.statement``,
``self.id_attribute``, ``self._query_builder``) and the private helpers
(``self._build_query_statement``, ``self._execute``, ``self.apply_filter``)
declared on :class:`BaseSQLAlchemyRepository`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Generic, cast

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlalchemy.sql import ColumnElement, Select, exists, literal, select

from apps.core.database.filters import StatementFilter
from apps.core.database.repository import _listing
from apps.core.database.types import (
    ExecutableOptions,
    OrderingPair,
    SessionType,
    SQLAlchemyModelT,
)


class _ReadRepositoryMixin(Generic[SQLAlchemyModelT]):
    """Read methods extracted from BaseSQLAlchemyRepository.

    See module docstring for the host-class contract.
    """

    async def get_one(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        expunge: bool = True,
        **kwargs: dict[str, Any],
    ) -> SQLAlchemyModelT | None:
        """Return one record matching ``filters`` (and any ``kwargs`` predicates), or ``None``."""
        statement = self._build_query_statement(  # type: ignore[attr-defined]
            *filters,
            statement=statement if statement is not None else self.statement,  # type: ignore[attr-defined]
            execution_options=execution_options,
            filter_kwargs=kwargs,
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)  # type: ignore[attr-defined]
        instance = query_result.scalar_one_or_none()

        if instance and expunge:
            session.expunge(instance)

        return instance

    async def get_one_by_id(
        self,
        session: SessionType,
        *,
        item_id: Any,
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        expunge: bool = True,
    ) -> SQLAlchemyModelT | None:
        """Return the row whose ``id_attribute`` equals ``item_id``, or ``None`` if missing."""
        statement = self._build_query_statement(  # type: ignore[attr-defined]
            statement=statement if statement is not None else self.statement,  # type: ignore[attr-defined]
            execution_options=execution_options,
            filter_kwargs=[(id_attribute or self.id_attribute, item_id)],  # type: ignore[attr-defined]
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)  # type: ignore[attr-defined]
        instance = query_result.scalar_one_or_none()

        if instance and expunge:
            session.expunge(instance)

        return instance

    async def list_items(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: list[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        eager_load: Sequence[InstrumentedAttribute[Any] | _AbstractLoad] | None = None,
        **kwargs: dict[str, Any],
    ) -> Sequence[SQLAlchemyModelT]:
        """List all records matching ``filters`` (and any ``kwargs`` predicates)."""
        statement = self._build_query_statement(  # type: ignore[attr-defined]
            *filters,
            statement=statement if statement is not None else self.statement,  # type: ignore[attr-defined]
            execution_options=execution_options,
            filter_kwargs=kwargs,
            order_by=order_by,
            eager_load=eager_load,
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)  # type: ignore[attr-defined]
        instances = query_result.scalars().all()

        if expunge and instances:
            for instance in instances:
                session.expunge(instance)

        return instances

    async def list_and_count(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: list[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        using_window_function: bool = False,
        eager_load: Sequence[InstrumentedAttribute[Any] | _AbstractLoad] | None = None,
        **kwargs: dict[str, Any],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """List records and total count.

        Defaults to the two-query strategy: a ``COUNT(*)`` first, then the
        page SELECT only when the count is non-zero. ``COUNT(*) OVER ()``
        is faster only for explicitly small / sparse result sets — under a
        broad filter it forces Postgres to evaluate the entire filtered
        set even when the page is just ``LIMIT 10``. Pass
        ``using_window_function=True`` to opt in for those workloads.
        """
        if using_window_function:
            return await self._list_with_count_window_function(
                session,
                *filters,
                statement=statement,
                order_by=order_by,
                execution_options=execution_options,
                expunge=expunge,
                uniquify=uniquify,
                eager_load=eager_load,
                **kwargs,
            )

        return await self._list_with_count_basic(
            session,
            *filters,
            statement=statement,
            order_by=order_by,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            eager_load=eager_load,
            **kwargs,
        )

    async def count(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> int:
        """Count records matching ``filters`` (and any ``filter_kwargs`` predicates)."""
        statement = self._build_query_statement(  # type: ignore[attr-defined]
            *filters,
            statement=statement if statement is not None else self.statement,  # type: ignore[attr-defined]
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
            count=True,
        )

        result = await self._execute(session, statement, uniquify=uniquify)  # type: ignore[attr-defined]
        return cast("int", result.scalar_one())

    async def _find_exists(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> bool:
        """Return ``True`` if any row matches the filters.

        Uses ``SELECT EXISTS(... LIMIT 1)`` so the engine short-circuits at
        the first match instead of counting every row.
        """
        inner = self._build_query_statement(  # type: ignore[attr-defined]
            *filters,
            statement=self.statement,  # type: ignore[attr-defined]
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
        )

        existence_query = select(exists(inner.with_only_columns(literal(1)).limit(1)))

        result = await self._execute(session, existence_query, uniquify=uniquify)  # type: ignore[attr-defined]
        return bool(result.scalar())

    async def _list_with_count_basic(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: list[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        eager_load: Sequence[InstrumentedAttribute[Any] | _AbstractLoad] | None = None,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """Two-query list+count fallback. Delegates to :mod:`._listing`."""
        return await _listing.list_with_count_basic(
            self,
            session,
            *filters,
            statement=statement,
            order_by=order_by,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            eager_load=eager_load,
            **filter_kwargs,
        )

    async def _list_with_count_window_function(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: list[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        eager_load: Sequence[InstrumentedAttribute[Any] | _AbstractLoad] | None = None,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """Single-query list+count via ``COUNT(*) OVER ()``. Delegates to :mod:`._listing`."""
        return await _listing.list_with_count_window_function(
            self,
            session,
            *filters,
            statement=statement,
            order_by=order_by,
            execution_options=execution_options,
            expunge=expunge,
            uniquify=uniquify,
            eager_load=eager_load,
            **filter_kwargs,
        )
