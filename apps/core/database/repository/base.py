"""Identity, query-composition, and shared helpers for the SQL repository.

Read methods live in :mod:`apps.core.database.repository._read` and write
methods live in :mod:`apps.core.database.repository._write`. The public
:class:`BaseSQLAlchemyRepository` composes those mixins on top of the
identity attributes and private helpers declared here.
"""

from collections.abc import Iterable
from typing import Any, ClassVar, Literal, cast, overload

from sqlalchemy.engine import Dialect, Result
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlalchemy.sql import (
    ColumnElement,
    Delete,
    Select,
    Update,
    select,
)
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate

from apps.core.database.filters import StatementFilter
from apps.core.database.repository._query_builder import QueryBuilder
from apps.core.database.repository._read import _ReadRepositoryMixin
from apps.core.database.repository._result_processor import (
    execute_statement as _execute_statement_fn,
)
from apps.core.database.repository._statements import (
    apply_count_projection as _apply_count_projection_fn,
    apply_execution_options as _apply_execution_options_fn,
    build_match_filter as _build_match_filter_fn,
    get_dialect as _get_dialect_fn,
    get_soft_delete_filter as _get_soft_delete_filter_fn,
)
from apps.core.database.repository._write import _WriteRepositoryMixin
from apps.core.database.types import (
    ExecutableOptions,
    OrderingPair,
    SessionType,
    StatementTypeT,
)


class BaseSQLAlchemyRepository[SQLAlchemyModelT: DeclarativeBase](
    _ReadRepositoryMixin[SQLAlchemyModelT],
    _WriteRepositoryMixin[SQLAlchemyModelT],
):
    """Base repository class for all repositories.

    The class is decomposed into three pieces for maintainability:

    * Identity, ``__init__``, query-composition (``apply_filter`` /
      ``apply_order_by`` / ``filter_select_by_kwargs``), ID accessors, and
      private statement/session helpers — declared here.
    * Read methods (``get_one``, ``get_one_by_id``, ``list_items``,
      ``list_and_count``, ``count``, ``_find_exists``) — provided by
      :class:`_ReadRepositoryMixin`.
    * Write methods (``add``, ``add_many``, ``update``, ``delete``,
      ``delete_where``, ``get_and_update``, ``get_or_upsert``) — provided
      by :class:`_WriteRepositoryMixin`.

    The mixins reach back into the helpers declared below via ``self.X``
    lookups (resolved by the MRO).
    """

    model_type: ClassVar[type[SQLAlchemyModelT]]

    id_attribute: str | InstrumentedAttribute[Any] = "id"
    statement: Select[tuple[SQLAlchemyModelT]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("__abstract_repository__"):
            return
        own_model_type = cls.__dict__.get("model_type")
        if own_model_type is None or not isinstance(own_model_type, type):
            msg = (
                f"{cls.__name__} must declare class attribute "
                "`model_type = <ORM model class>` "
                "(or set `__abstract_repository__ = True` for intermediate bases)."
            )
            raise TypeError(msg)

    def __init__(self, *, statement: Select[tuple[SQLAlchemyModelT]] | None = None, **kwargs: Any) -> None:
        """Initialize the repository.

        Args:
            statement: Optional starter SELECT statement; defaults to
                ``select(self.model_type)``.
            **kwargs: Additional keyword arguments retained on the instance
                for use by subclasses.
        """
        self.statement = statement or select(self.model_type)
        self.kwargs = kwargs
        self._query_builder: QueryBuilder[SQLAlchemyModelT] = QueryBuilder(self.model_type)

    @overload
    def apply_filter(
        self,
        statement: Select[tuple[SQLAlchemyModelT]],
        *filters: StatementFilter | ColumnElement[bool],
    ) -> Select[tuple[SQLAlchemyModelT]]: ...

    @overload
    def apply_filter(
        self,
        statement: Delete,
        *filters: StatementFilter | ColumnElement[bool],
    ) -> Delete: ...

    @overload
    def apply_filter(
        self,
        statement: Update,
        *filters: StatementFilter | ColumnElement[bool],
    ) -> Update: ...

    @overload
    def apply_filter(
        self,
        statement: ReturningDelete[tuple[SQLAlchemyModelT]] | ReturningUpdate[tuple[SQLAlchemyModelT]],
        *filters: StatementFilter | ColumnElement[bool],
    ) -> ReturningDelete[tuple[SQLAlchemyModelT]] | ReturningUpdate[tuple[SQLAlchemyModelT]]: ...

    def apply_filter(
        self,
        statement: StatementTypeT,
        *filters: StatementFilter | ColumnElement[bool],
    ) -> StatementTypeT:
        """Apply filters to a SQL statement.

        Delegates to :class:`QueryBuilder` (3.1 Phase-A seam). Overloads
        above preserve the precise return-type mapping for callers.
        """
        return self._query_builder.apply_filter(statement, *filters)

    def apply_order_by(
        self,
        statement: StatementTypeT,
        order_by: OrderingPair | list[OrderingPair],
    ) -> StatementTypeT:
        """Apply ordering to a SQL statement.

        Delegates to :class:`QueryBuilder`. ``Update`` / ``Delete`` statements
        are returned unchanged because SQLAlchemy does not support
        ``ORDER BY`` on them.
        """
        return self._query_builder.apply_order_by(statement, order_by)

    def filter_select_by_kwargs(
        self,
        statement: StatementTypeT,
        kwargs: dict[Any, Any] | Iterable[tuple[Any, Any]],
    ) -> StatementTypeT:
        """Filter a statement using keyword arguments.

        Delegates to :class:`QueryBuilder.filter_by_kwargs`.
        """
        return self._query_builder.filter_by_kwargs(statement, kwargs)

    @classmethod
    def get_id_attribute_value(
        cls,
        item: SQLAlchemyModelT | type[SQLAlchemyModelT],
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
    ) -> Any:
        """Get value of attribute named as :attr:`id_attribute` on ``item``."""
        if id_attribute is None:
            id_attribute = cls.id_attribute

        if isinstance(id_attribute, InstrumentedAttribute):
            id_attribute = id_attribute.key

        return getattr(item, id_attribute)

    @classmethod
    def set_id_attribute_value(
        cls,
        item_id: Any,
        item: SQLAlchemyModelT,
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
    ) -> SQLAlchemyModelT:
        """Return the ``item`` after the ID is set to the appropriate attribute."""
        if id_attribute is None:
            id_attribute = cls.id_attribute

        if isinstance(id_attribute, InstrumentedAttribute):
            id_attribute = id_attribute.key

        setattr(item, id_attribute, item_id)
        return item

    def _build_match_filter(
        self,
        match_fields: list[str] | str | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegates to :func:`_statements.build_match_filter`."""
        return _build_match_filter_fn(match_fields, kwargs)

    def _get_soft_delete_filter(self) -> ColumnElement[bool] | None:
        """Delegates to :func:`_statements.get_soft_delete_filter`."""
        return _get_soft_delete_filter_fn(self.model_type)

    def _apply_execution_options(
        self,
        statement: StatementTypeT,
        execution_options: ExecutableOptions | None,
    ) -> StatementTypeT:
        """Delegates to :func:`_statements.apply_execution_options`."""
        return _apply_execution_options_fn(statement, execution_options)

    def _apply_filter_kwargs(
        self,
        statement: StatementTypeT,
        filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]] | None,
    ) -> StatementTypeT:
        """Apply keyword filters when present."""
        if not filter_kwargs:
            return statement

        return cast(
            "StatementTypeT",
            self.filter_select_by_kwargs(statement, kwargs=filter_kwargs),
        )

    def _apply_count_projection(self, statement: StatementTypeT, *, enable: bool = False) -> StatementTypeT:
        """Delegates to :func:`_statements.apply_count_projection`."""
        return _apply_count_projection_fn(statement, enable=enable)

    def _build_query_statement(
        self,
        *filters: StatementFilter | ColumnElement[bool],
        statement: StatementTypeT,
        execution_options: ExecutableOptions | None = None,
        filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]] | None = None,
        order_by: list[OrderingPair] | OrderingPair | None = None,
        count: bool = False,
        eager_load: list[InstrumentedAttribute[Any] | _AbstractLoad] | None = None,
    ) -> StatementTypeT:
        """Compose loader/exec options/filters/order/count into a final statement."""
        soft_delete_filter = None
        if isinstance(statement, Select):
            soft_delete_filter = self._get_soft_delete_filter()

        all_filters = list(filters)
        if soft_delete_filter is not None:
            all_filters.append(soft_delete_filter)

        statement = cast("StatementTypeT", self.apply_filter(statement, *all_filters))

        statement = self._apply_execution_options(statement, execution_options)
        statement = self._apply_filter_kwargs(statement, filter_kwargs)

        if order_by is not None:
            statement = self.apply_order_by(statement, order_by)

        if eager_load and isinstance(statement, Select):
            options = [opt if isinstance(opt, _AbstractLoad) else selectinload(opt) for opt in eager_load]
            statement = cast("StatementTypeT", statement.options(*options))

        return self._apply_count_projection(statement, enable=count)

    async def _attach_to_session(
        self,
        session: SessionType,
        model: SQLAlchemyModelT,
        *,
        strategy: Literal["insert", "merge"] = "insert",
        load: bool = True,
    ) -> SQLAlchemyModelT:
        """Attach a model instance to the session via insert or merge."""
        if strategy == "insert":
            session.add(model)
            return model
        if strategy == "merge":
            return await session.merge(model, load=load)
        raise ValueError(f"Invalid strategy: {strategy}. Must be 'insert' or 'merge'.")

    async def _execute(
        self,
        session: SessionType,
        statement: StatementTypeT,
        *,
        uniquify: bool = True,
    ) -> Result[tuple[SQLAlchemyModelT]]:
        """Delegates to :func:`_result_processor.execute_statement`."""
        return await _execute_statement_fn(session, statement, uniquify=uniquify)

    @classmethod
    def _get_dialect(cls, session: AsyncSession | async_scoped_session[AsyncSession]) -> Dialect:
        """Delegates to :func:`_statements.get_dialect`."""
        return _get_dialect_fn(session)

    @property
    def model(self) -> type[SQLAlchemyModelT]:
        """Get the model type for this repository."""
        return self.model_type
