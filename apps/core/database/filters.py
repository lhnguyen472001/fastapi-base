import abc
import datetime
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any, Generic, Literal, cast

from pydantic import ConfigDict, dataclasses
from sqlalchemy.sql import any_, not_, operators as ops, text
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import Select

from .types import SQLAlchemyModelT, StatementTypeT
from .utils import get_instrumented_attr

if TYPE_CHECKING:
    from sqlalchemy.types import Date


class StatementFilter(abc.ABC):
    """Abstract base class for SQLAlchemy statement filters.

    This class defines the interface for all filter types in the system. Each filter
    implementation must provide a method to append its filtering logic to an existing
    SQLAlchemy statement.
    """

    @abc.abstractmethod
    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append filter conditions to a SQLAlchemy statement.

        Args:
            statement: The SQLAlchemy statement to modify
            model: The SQLAlchemy model class
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            StatementTypeT: Modified SQLAlchemy statement with filter conditions applied

        Raises:
            NotImplementedError: If the concrete class doesn't implement this method

        Note:
            This method must be implemented by all concrete filter classes.

        See Also:
            :meth:`sqlalchemy.sql.expression.Select.where`: SQLAlchemy where clause
        """
        return statement


@dataclasses.dataclass(frozen=True, kw_only=True)
class BeforeAfter(StatementFilter):
    """Filter for checking if a field is before/after a given date."""

    field_name: str
    before: datetime.datetime | None
    after: datetime.datetime | None

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append filter conditions to a SQLAlchemy statement."""
        field = get_instrumented_attr(model, self.field_name)
        if self.before:
            statement = cast("StatementTypeT", statement.where(field < self.before))

        if self.after:
            statement = cast("StatementTypeT", statement.where(field > self.after))

        return statement


@dataclasses.dataclass(frozen=True, kw_only=True)
class OnBeforeAfter(StatementFilter):
    """Filter for checking if a field is on or before/after a given date."""

    field_name: str
    on_or_before: datetime.datetime | None
    on_or_after: datetime.datetime | None

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append filter conditions to a SQLAlchemy statement.

        Args:
            statement: The SQLAlchemy statement to modify
            model: The SQLAlchemy model class
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            StatementTypeT: Modified SQLAlchemy statement with filter conditions applied
        """
        field = get_instrumented_attr(model, self.field_name)
        if self.on_or_before:
            statement = cast("StatementTypeT", statement.where(field <= self.on_or_before))

        if self.on_or_after:
            statement = cast("StatementTypeT", statement.where(field >= self.on_or_after))

        return statement


class InAnyFilter(StatementFilter, abc.ABC):
    """Abstract base class for filters that check if a field is in a collection of values."""


@dataclasses.dataclass(
    frozen=True,
    kw_only=True,
    config=ConfigDict(arbitrary_types_allowed=True),
)
class CollectionFilter(InAnyFilter, Generic[SQLAlchemyModelT]):
    """Filter for checking if a field is in a collection of values."""

    field_name: str
    values: Collection[SQLAlchemyModelT] | None

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append filter conditions to a SQLAlchemy statement.

        Args:
            statement: The SQLAlchemy statement to modify
            model: The SQLAlchemy model class
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            StatementTypeT: Modified SQLAlchemy statement with filter conditions applied
        """
        field = get_instrumented_attr(model, self.field_name)
        prefer_any = kwargs.get("prefer_any", False)
        if self.values is None:
            return statement

        if not self.values:
            return cast("StatementTypeT", statement.where(text("1=-1")))

        if prefer_any:
            return cast("StatementTypeT", statement.where(any_(self.values) == field))

        return cast("StatementTypeT", statement.where(field.in_(self.values)))


@dataclasses.dataclass(
    frozen=True,
    kw_only=True,
    config=ConfigDict(arbitrary_types_allowed=True),
)
class NotInCollectionFilter(InAnyFilter, Generic[SQLAlchemyModelT]):
    """Filter for checking if a field is not in a collection of values."""

    field_name: str
    values: Collection[SQLAlchemyModelT] | None

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append filter conditions to a SQLAlchemy statement."""
        field = get_instrumented_attr(model, self.field_name)
        prefer_any = kwargs.get("prefer_any", False)
        if not self.values:
            return statement

        if prefer_any:
            return cast("StatementTypeT", statement.where(any_(self.values) != field))

        return cast("StatementTypeT", statement.where(not_(field.in_(self.values))))


class PaginationFilter(StatementFilter, abc.ABC):
    """Abstract base class for pagination filters.

    Subclasses should implement pagination logic, such as limit/offset or
    cursor-based pagination.
    """


@dataclasses.dataclass(frozen=True, kw_only=True)
class LimitOffsetPaginationFilter(PaginationFilter):
    """Filter for applying limit and offset pagination to a SQLAlchemy statement."""

    limit: int
    offset: int

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append limit and offset pagination to a SQLAlchemy statement.

        Args:
            statement: The SQLAlchemy statement to modify
            model: The SQLAlchemy model class
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        Returns:
            StatementTypeT: Modified SQLAlchemy statement with limit and offset pagination applied
        """
        if isinstance(statement, Select):
            return cast("StatementTypeT", statement.limit(self.limit).offset(self.offset))
        return statement


VALID_DIRECTIONS = ["asc", "desc"]


@dataclasses.dataclass(frozen=True, kw_only=True)
class OrderBy(StatementFilter):
    """Filter for applying order by clause to a SQLAlchemy statement."""

    field_name: str
    direction: Literal["asc", "desc"] = "asc"

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append order by clause to a SQLAlchemy statement."""
        if not isinstance(statement, Select):
            return statement

        field = get_instrumented_attr(model, self.field_name)
        if self.direction == "asc":
            return cast("StatementTypeT", statement.order_by(field.asc()))

        return cast("StatementTypeT", statement.order_by(field.desc()))


operators_map: dict[str, Callable[[Any, Any], ColumnElement[bool]]] = {
    "eq": ops.eq,
    "ne": ops.ne,
    "gt": ops.gt,
    "ge": ops.ge,
    "lt": ops.lt,
    "le": ops.le,
    "in": ops.in_op,
    "notin": ops.notin_op,
    "between": lambda c, v: c.between(v[0], v[1]),
    "like": ops.like_op,
    "ilike": ops.ilike_op,
    "startswith": ops.startswith_op,
    "istartswith": lambda c, v: c.ilike(v + "%"),
    "endswith": ops.endswith_op,
    "iendswith": lambda c, v: c.ilike("%" + v),
    "dateeq": lambda c, v: cast("Date", c) == v,
}
VALID_OPERATORS = set(operators_map.keys())


@dataclasses.dataclass(frozen=True, kw_only=True)
class ComparisonFilter(StatementFilter):
    """Filter for applying a comparison operator to a SQLAlchemy statement."""

    field_name: str
    operator: str
    value: Any

    def append_to_statement(
        self,
        statement: StatementTypeT,
        model: type[SQLAlchemyModelT],
        *args: tuple[Any],
        **kwargs: dict[str, Any],
    ) -> StatementTypeT:
        """Append comparison operator to a SQLAlchemy statement.

        Args:
            statement: The SQLAlchemy statement to modify
            model: The SQLAlchemy model class
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            StatementTypeT: Modified SQLAlchemy statement with comparison operator applied
        """
        field = get_instrumented_attr(model, self.field_name)
        operator_func = operators_map.get(self.operator)

        if operator_func is None:
            msg = f"Invalid operator '{self.operator}'. Must be one of: {', '.join(sorted(VALID_OPERATORS))}"
            raise ValueError(msg)

        condition = operator_func(field, self.value)
        return cast("StatementTypeT", statement.where(condition))
