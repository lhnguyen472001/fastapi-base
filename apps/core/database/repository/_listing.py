"""List+count execution strategies for :class:`BaseSQLAlchemyRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.core.database.repository._result_processor import (
    collect_rows as _collect_rows_fn,
    collect_rows_with_window_count as _collect_rows_with_window_count_fn,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.orm import InstrumentedAttribute
    from sqlalchemy.orm.strategy_options import _AbstractLoad
    from sqlalchemy.sql import ColumnElement, Select

    from apps.core.database.filters import StatementFilter
    from apps.core.database.repository.base import BaseSQLAlchemyRepository
    from apps.core.database.types import (
        ExecutableOptions,
        OrderingPair,
        SessionType,
        SQLAlchemyModelT,
    )


async def list_with_count_basic(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
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
    """Two-query list+count: COUNT first, then SELECT only when count > 0."""
    count_result = await repo.count(
        session,
        *filters,
        statement=statement,
        execution_options=execution_options,
        uniquify=uniquify,
        **filter_kwargs,
    )

    if count_result == 0:
        return [], 0

    statement = repo._build_query_statement(
        *filters,
        statement=statement if statement is not None else repo.statement,
        execution_options=execution_options,
        filter_kwargs=filter_kwargs,
        order_by=order_by,
        eager_load=eager_load,
    )

    query_result = await repo._execute(session, statement, uniquify=uniquify)
    instances = _collect_rows_fn(query_result, session=session, expunge=expunge)
    return instances, count_result


async def list_with_count_window_function(
    repo: BaseSQLAlchemyRepository[SQLAlchemyModelT],
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
    """Single-query list+count using ``COUNT(*) OVER ()`` (Postgres default)."""
    from sqlalchemy.sql import func as sql_func
    from sqlalchemy.sql.expression import over

    statement = repo._build_query_statement(
        *filters,
        statement=statement if statement is not None else repo.statement,
        execution_options=execution_options,
        filter_kwargs=filter_kwargs,
        order_by=order_by,
        eager_load=eager_load,
    )

    statement = statement.add_columns(over(sql_func.count()))
    result = await repo._execute(session, statement, uniquify=uniquify)

    return _collect_rows_with_window_count_fn(result, session=session, expunge=expunge)
