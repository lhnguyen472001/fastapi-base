from collections.abc import Sequence
from typing import Any, ClassVar, Generic, Iterable, List, Protocol, TypeVar, overload

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement, Delete, Select, Update
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate
from sqlalchemy.sql.selectable import ForUpdateParameter

from libs.database.sql.filters import StatementFilter
from libs.database.sql.types import ExecutableOptions, OrderingPair, SQLAlchemyModelT, StatementTypeT

RepositoryT = TypeVar("RepositoryT", bound="SQLAlchemyRepositoryProtocol")


class SQLAlchemyRepositoryProtocol(Protocol[SQLAlchemyModelT], Generic[SQLAlchemyModelT]):
    """Protocol for all SQLAlchemy repositories."""

    model_type: ClassVar[type[SQLAlchemyModelT]]

    @overload
    def apply_filter(
        self,
        statement: Select[tuple[SQLAlchemyModelT]],
        *filters: StatementFilter | ColumnElement[bool],
        apply_pagination: bool = False,
    ) -> Select[tuple[SQLAlchemyModelT]]: ...

    @overload
    def apply_filter(
        self,
        statement: Delete,
        *filters: StatementFilter | ColumnElement[bool],
        apply_pagination: bool = False,
    ) -> Delete: ...

    @overload
    def apply_filter(
        self,
        statement: Update,
        *filters: StatementFilter | ColumnElement[bool],
        apply_pagination: bool = False,
    ) -> Update: ...

    @overload
    def apply_filter(
        self,
        statement: ReturningDelete[tuple[SQLAlchemyModelT]] | ReturningUpdate[tuple[SQLAlchemyModelT]],
        *filters: StatementFilter | ColumnElement[bool],
        apply_pagination: bool = False,
    ) -> ReturningDelete[tuple[SQLAlchemyModelT]] | ReturningUpdate[tuple[SQLAlchemyModelT]]: ...

    def apply_filter(
        self,
        statement: StatementTypeT,
        *filters: StatementFilter | ColumnElement[bool],
        apply_pagination: bool = False,
    ) -> StatementTypeT:
        """Apply filters to a SQL statement.

        Args:
            *filters: Filter conditions to apply.
            apply_pagination: Whether to apply pagination filters.
            statement: The base SQL statement to filter.

        Returns:
            StatementTypeT: The filtered SQL statement.
        """

    def filter_select_by_kwargs(
        self,
        statement: StatementTypeT,
        kwargs: dict[Any, Any] | Iterable[tuple[Any, Any]],
    ) -> StatementTypeT:
        """Filter a statement using keyword arguments.

        Args:
            statement: :class:`sqlalchemy.sql.Select` The SQL statement to filter.
            kwargs: Dictionary or iterable of tuples containing filter criteria.
                Keys should be model attribute names, values are what to filter for.

        Returns:
            StatementTypeT: The filtered SQL statement.
        """

    def apply_order_by(
        self,
        statement: StatementTypeT,
        order_by: OrderingPair | List[OrderingPair],
    ) -> StatementTypeT:
        """Apply ordering to a SQL statement.

        Args:
            statement: The SQL statement to order.
            order_by: Ordering specification. Either a single tuple or list of tuples where:
                - First element is the field name or :class:`sqlalchemy.orm.InstrumentedAttribute` to order by
                - Second element is a boolean indicating descending (True) or ascending (False)

        Returns:
            StatementTypeT: The ordered SQL statement.
        """

    @classmethod
    def get_id_attribute_value(
        cls,
        item: SQLAlchemyModelT | type[SQLAlchemyModelT],
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
    ) -> Any:
        """Get the value of the ID attribute from rbac.models instance or class.

        Args:
            item: The model instance or class to get the ID attribute value from.
            id_attribute: The attribute name or SQLAlchemy field used as the primary key for the model.

        Returns:
            Any: The value of the ID attribute.
        """

    @classmethod
    def set_id_attribute_value(
        cls,
        item_id: Any,
        item: SQLAlchemyModelT,
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
    ) -> SQLAlchemyModelT:
        """Set the value of the ID attribute on a model instance.

        Args:
            item_id: The value to set for the ID attribute.
            item: The model instance to set the ID attribute value on.
            id_attribute: The attribute name or SQLAlchemy field used as the primary key for the model.

        Returns:
            SQLAlchemyModelT: The updated model instance.
        """

    @overload
    async def add(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *data: SQLAlchemyModelT,
        expunge: bool | None = None,
    ) -> SQLAlchemyModelT: ...

    @overload
    async def add(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        data: dict[str, Any],
        expunge: bool | None = None,
    ) -> SQLAlchemyModelT: ...

    async def add(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        data: SQLAlchemyModelT | dict[str, Any],
        expunge: bool | None = None,
    ) -> SQLAlchemyModelT:
        """Add a new record to the database.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]):
                The SQLAlchemy session to use for the operation.

        Keyword Args:
            data (SQLAlchemyModelT | dict[str, Any]): The data to be added,
                either as a model instance or a dictionary.
            expunge (bool | None): Whether to automatically expunge
                the object from the session.

        Returns:
            SQLAlchemyModelT: The added record.

        Raises:
            Exception: If object exsited.
        """

    @overload
    async def add_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        data: Sequence[SQLAlchemyModelT],
        expunge: bool,
    ) -> Sequence[SQLAlchemyModelT]: ...

    @overload
    async def add_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        data: Sequence[dict[str, Any]],
        expunge: bool,
    ) -> Sequence[SQLAlchemyModelT]: ...

    async def add_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        data: Sequence[SQLAlchemyModelT | dict[str, Any]],
        expunge: bool,
    ) -> Sequence[SQLAlchemyModelT]:
        """Insert multiple records into the database in a single operation.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.

        Keyword Args:
            data (Sequence[SQLAlchemyModelT | dict[str, Any]]): The data to be added, either as a model instance or a dictionary.
            expunge (bool): Whether to automatically expunge the object from the session.

        Returns:
            Sequence[SQLAlchemyModelT]: The added records.
        """

    async def get_one(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        expunge: bool = True,
        **kwargs: dict[str, Any],
    ) -> SQLAlchemyModelT | None:
        """Retrieves a single record from the database based on the provided filters.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            uniquify (bool): Whether to ensure the result is unique.
            expunge (bool): Whether to automatically expunge the object from the session.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            SQLAlchemyModelT | None: The retrieved record, or None if not found.
        """

    async def get_one_by_id(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *,
        item_id: Any,
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        expunge: bool = True,
    ) -> SQLAlchemyModelT | None:
        """Retrieves a record from the database by its ID.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.

        Keyword Args:
            item_id (Any): The ID of the record to retrieve.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            id_attribute (str | InstrumentedAttribute[Any] | None): The attribute to use for the ID, if different from the default.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            uniquify (bool): Whether to ensure the result is unique.
            expunge (bool): Whether to automatically expunge the object from the session.

        Returns:
            SQLAlchemyModelT | None: The retrieved record, or None if not found.
        """

    async def get_and_update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        with_for_update: bool | None = None,
        **kwargs: dict[str, Any],
    ) -> tuple[SQLAlchemyModelT | None, bool]:
        """Retrieve and update a record based on the provided filters.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            match_fields (List[str] | str | None): Fields to match for update.
            attribute_names (Iterable[str] | None): Attributes to include in the update.
            with_for_update (bool | None): Whether to use a "for update" lock.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            tuple[SQLAlchemyModelT | None, bool]: A tuple containing the retrieved record and a boolean indicating
            whether it was newly created.
        """

    async def get_or_upsert(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        execution_options: dict[str, Any] | None = None,
        upsert: bool = False,
        expunge: bool = True,
        uniquify: bool = True,
        with_for_update: bool | None = None,
        **kwargs: dict[str, Any],
    ) -> tuple[SQLAlchemyModelT, bool]:
        """Retrieve or upsert a record based on the provided filters.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            match_fields (List[str] | str | None): Fields to match for upsert.
            attribute_names (Iterable[str] | None): Attributes to include in the upsert.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            upsert (bool): Whether to perform an upsert operation.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            with_for_update (bool | None): Whether to use a "for update" lock.
            **kwargs: Additional keyword arguments for the query.

        Returns:
            tuple[SQLAlchemyModelT, bool]: A tuple containing the retrieved or upserted record and a boolean indicating
            whether it was newly created.
        """

    async def list_items(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: dict[str, Any] | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **kwargs: dict[str, Any],
    ) -> Sequence[SQLAlchemyModelT]:
        """List all records from the database.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session
                    to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            order_by (List[OrderingPair] | OrderingPair | None): Ordering specification.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.
        """

    async def list_and_count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: dict[str, Any] | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        using_window_function: bool = False,
        **kwargs: dict[str, Any],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """List all records from the database and get the count of records.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session
                    to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            order_by (List[OrderingPair] | OrderingPair | None): Ordering specification.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            using_window_function (bool): Whether to use a window function to get the count.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            tuple[Sequence[SQLAlchemyModelT], int]: A tuple containing the list of records and the count of records.
        """

    async def count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        **kwargs: dict[str, Any],
    ) -> int:
        """Get the count of records from the database.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            execution_options (ExecutableOptions | None): Additional execution options for the query.
            uniquify (bool): Whether to ensure the result is unique.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            int: The count of records.
        """

    @overload
    async def update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: SQLAlchemyModelT,
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        with_for_update: ForUpdateParameter = None,
        expunge: bool | None = None,
        execution_options: dict[str, Any] | None = None,
    ) -> SQLAlchemyModelT | None: ...

    @overload
    async def update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: dict[str, Any],
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        with_for_update: ForUpdateParameter = None,
        expunge: bool | None = None,
        execution_options: ExecutableOptions | None = None,
    ) -> SQLAlchemyModelT | None: ...

    async def update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool | None = None,
        with_for_update: ForUpdateParameter = None,
    ) -> SQLAlchemyModelT | None:
        """Update a record in the database.

        Args:
            data (SQLAlchemyModelT | dict[str, Any]): The data to update, either as a model instance or a dictionary.
            id_attribute (InstrumentedAttribute[Any] | str | None): The attribute to use for the ID, if different from the default.
            attribute_names (Iterable[str] | None): Attributes to include in the update.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool | None): Whether to automatically expunge the object from the session.
            with_for_update (ForUpdateParameter): Whether to use a "for update" lock.

        Returns:
            SQLAlchemyModelT | None: The updated record or None if not found.
        """

    @overload
    async def update_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: Sequence[SQLAlchemyModelT],
        *,
        expunge: bool | None = None,
        execution_options: dict[str, Any] | None = None,
    ) -> Sequence[SQLAlchemyModelT]: ...

    @overload
    async def update_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: Sequence[dict[str, Any]],
        *,
        expunge: bool | None = None,
        execution_options: dict[str, Any] | None = None,
    ) -> Sequence[SQLAlchemyModelT]: ...

    async def update_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: Sequence[SQLAlchemyModelT | dict[str, Any]],
        *,
        expunge: bool | None = None,
        execution_options: dict[str, Any] | None = None,
    ) -> Sequence[SQLAlchemyModelT]:
        """Update multiple records in the database in a single operation.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            data (Sequence[SQLAlchemyModelT | dict[str, Any]]): The data to update,
                    either as a model instance or a dictionary.
            expunge (bool | None): Whether to automatically expunge the object from the session.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.

        Returns:
            Sequence[SQLAlchemyModelT]: The updated records.
        """

    async def delete(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        item_id: Any,
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        expunge: bool | None = None,
        execution_options: dict[str, Any] | None = None,
    ) -> SQLAlchemyModelT | None:
        """Delete a record from the database by its ID.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            item_id (Any): The ID of the record to delete.

        Keyword Args:
            id_attribute (InstrumentedAttribute[Any] | str | None): The attribute to use for the ID, if different from the default.
            expunge (bool | None): Whether to automatically expunge the object from the session.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.

        Returns:
            SQLAlchemyModelT | None: The deleted record, or None if not found.
        """

    async def delete_where(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        sanity_check: bool = True,
        **kwargs: dict[str, Any],
    ) -> Sequence[SQLAlchemyModelT] | None:
        """Delete records from the database based on the provided filters.

        Args:
            session (AsyncSession | async_scoped_session[AsyncSession]): The SQLAlchemy session to use for the operation.
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the deletion.
            execution_options (ExecutableOptions | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            sanity_check (bool): Whether to perform a sanity check before deletion.
            **kwargs (dict[str, Any]): Additional keyword arguments for the deletion.

        Returns:
            Sequence[SQLAlchemyModelT] | None: The deleted records, or None if the sanity check failed.
        """
