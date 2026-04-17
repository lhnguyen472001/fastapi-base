"""Composable SQL-statement query builder.

Extracted from :class:`apps.core.database.sql.repository.base.BaseSQLAlchemyRepository`
as the first step of the 3.1 split so filter / order / keyword-predicate
composition can be reused and tested in isolation from the CRUD machinery.

The base repository now composes an instance of :class:`QueryBuilder` and
forwards its ``apply_filter`` / ``apply_order_by`` / ``filter_select_by_kwargs``
methods here, preserving the existing public API while carving out a seam
that future phases (CRUD / ResultProcessor extraction) can lean on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, cast

from sqlalchemy.sql import ColumnElement, Select

from apps.core.database.types import (
    OrderingPair,
    SQLAlchemyModelT,
    StatementTypeT,
)
from apps.core.database.utils import get_instrumented_attr

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.core.database.filters import StatementFilter


class QueryBuilder(Generic[SQLAlchemyModelT]):
    """Apply filters, ordering, and keyword predicates to a SQL statement.

    The builder is bound to a single model type at construction so callers
    do not repeat it on every method call. It is stateless across calls —
    each method returns a new statement and never mutates the builder.
    """

    def __init__(self, model_type: type[SQLAlchemyModelT]) -> None:
        self.model_type = model_type

    def apply_filter(
        self,
        statement: StatementTypeT,
        *filters: StatementFilter | ColumnElement[bool],
    ) -> StatementTypeT:
        """Apply a mix of :class:`StatementFilter` and raw ``ColumnElement`` clauses.

        ``StatementFilter`` instances delegate to their own
        ``append_to_statement`` hook; raw column expressions are added via
        ``statement.where(...)``.
        """
        for filter_condition in filters:
            if isinstance(filter_condition, ColumnElement):
                statement = cast("StatementTypeT", statement.where(filter_condition))
            else:
                statement = cast(
                    "StatementTypeT",
                    filter_condition.append_to_statement(statement, self.model_type),
                )
        return statement

    def apply_order_by(
        self,
        statement: StatementTypeT,
        order_by: OrderingPair | list[OrderingPair],
    ) -> StatementTypeT:
        """Apply ordering to a ``Select`` statement.

        Non-``Select`` statements (``Update``, ``Delete``) are returned
        unchanged — SQLAlchemy does not support ``ORDER BY`` on them.
        """
        if not isinstance(statement, Select):
            return statement

        if not isinstance(order_by, list):
            order_by = [order_by]

        for field_name, is_desc in order_by:
            field = get_instrumented_attr(self.model_type, field_name)
            statement = cast(
                "StatementTypeT",
                statement.order_by(field.desc() if is_desc else field.asc()),
            )
        return statement

    def filter_by_kwargs(
        self,
        statement: StatementTypeT,
        kwargs: dict[Any, Any] | Iterable[tuple[Any, Any]],
    ) -> StatementTypeT:
        """Add ``WHERE col = value`` clauses for each keyword pair."""
        for k, v in dict(kwargs).items():
            field = get_instrumented_attr(self.model_type, k)
            statement = cast("StatementTypeT", statement.where(field == v))
        return statement
