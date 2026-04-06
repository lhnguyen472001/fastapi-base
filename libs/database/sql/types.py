import datetime
from collections.abc import Sequence
from typing import Any, Tuple, TypeAlias, TypeVar

from sqlalchemy.engine import Dialect, RowMapping
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute
from sqlalchemy.sql import Delete, Select, Update
from sqlalchemy.sql.base import ExecutableOption
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate
from sqlalchemy.sql.expression import ColumnExpressionArgument
from sqlalchemy.types import DateTime, TypeDecorator

RowT = TypeVar("RowT", bound=Tuple[Any, ...])
RowMappingT = TypeVar("RowMappingT", bound=RowMapping)
WhereClauseT: TypeAlias = ColumnExpressionArgument[bool]
OrderingPair: TypeAlias = tuple[str | InstrumentedAttribute[Any], bool]
ExecutableOptions: TypeAlias = Sequence[ExecutableOption]
SQLAlchemyModelT = TypeVar("SQLAlchemyModelT", bound=DeclarativeBase)
StatementTypeT = TypeVar(
    "StatementTypeT",
    bound=ReturningDelete[tuple[Any]]
    | ReturningUpdate[tuple[Any]]
    | Select[tuple[Any]]
    | Select[Any]
    | Update
    | Delete,
)


class DateTimeUTC(TypeDecorator[datetime.datetime]):
    """Timezone Aware DateTime.

    Ensure UTC is stored in the database and that TZ aware dates are returned for all dialects.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime.datetime]:
        """Return `datetime` Python type."""
        return datetime.datetime

    def process_bind_param(self, value: datetime.datetime | None, dialect: Dialect) -> datetime.datetime | None:
        """Process bind parameter for each special database type."""
        if value is None:
            return value
        if not value.tzinfo:
            msg = "tzinfo is required"
            raise TypeError(msg)
        return value.astimezone(datetime.UTC)

    def process_result_value(self, value: datetime.datetime | None, dialect: Dialect) -> datetime.datetime | None:
        """Process result value for each special database type."""
        if value is None:
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value


class _MISSING:
    """Placeholder for missing values."""


MISSING = _MISSING()
