import uuid
from collections.abc import Iterable, Sequence
from typing import Any, ClassVar, Generic, List, Literal, cast, overload

from sqlalchemy.engine import Dialect, Result
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement, Delete, Select, Update, delete, exists, literal, select, text
from sqlalchemy.sql import func as sql_func
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate
from sqlalchemy.sql.expression import over
from sqlalchemy.sql.selectable import ForUpdateParameter

from apps.core.database.sql.filters import StatementFilter
from apps.core.database.sql.types import MISSING, ExecutableOptions, OrderingPair, SQLAlchemyModelT, StatementTypeT
from apps.core.database.sql.utils import get_instrumented_attr


class BaseSQLAlchemyRepository(Generic[SQLAlchemyModelT]):
    """Base repository class for all repositories."""

    model_type: ClassVar[type[SQLAlchemyModelT]]

    id_attribute: str | InstrumentedAttribute[Any] = "id"
    statement: Select[tuple[SQLAlchemyModelT]]

    def __init__(self, *, statement: Select[tuple[SQLAlchemyModelT]] | None = None, **kwargs: Any) -> None:
        """Initialize the repository.

        Args:
            statement: The SQLAlchemy statement to use for the repository.
            **kwargs: Additional keyword arguments for the repository.
        """
        self.statement = statement or select(self.model_type)
        self.kwargs = kwargs

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

        Args:
            *filters: Filter conditions to apply.
            apply_pagination: Whether to apply pagination filters.
            statement: The base SQL statement to filter.

        Returns:
            StatementTypeT: The filtered SQL statement.
        """
        for filter_condition in filters:
            if isinstance(filter_condition, ColumnElement):
                statement = cast("StatementTypeT", statement.where(filter_condition))
            else:
                # Handle StatementFilter - apply it to the statement with model
                statement = cast("StatementTypeT", filter_condition.append_to_statement(statement, self.model_type))

        return statement

    def apply_order_by(
        self,
        statement: StatementTypeT,
        order_by: OrderingPair | List[OrderingPair],
    ) -> StatementTypeT:
        """Apply ordering to a SQL statement.

        Args:
            statement: The SQL statement to order.
            order_by: Ordering specification. Either a single tuple or list of tuples where:
                - First element is the field name or InstrumentedAttribute to order by
                - Second element is a boolean indicating descending (True) or ascending (False)

        Returns:
            StatementTypeT: The ordered SQL statement.
        """
        if not isinstance(statement, Select):
            return statement

        if not isinstance(order_by, list):
            order_by = [order_by]

        for field_name, is_desc in order_by:
            field = get_instrumented_attr(self.model_type, field_name)
            statement = cast("StatementTypeT", statement.order_by(field.desc() if is_desc else field.asc()))

        return statement

    def filter_select_by_kwargs(
        self,
        statement: StatementTypeT,
        kwargs: dict[Any, Any] | Iterable[tuple[Any, Any]],
    ) -> StatementTypeT:
        """Filter a statement using keyword arguments.

        Args:
            statement (StatementTypeT): The SQL statement to filter.
            kwargs (dict[Any, Any] | Iterable[tuple[Any, Any]]): Dictionary or iterable of tuples containing filter criteria.
                Keys should be model attribute names, values are what to filter for.

        Returns:
            StatementTypeT: The filtered SQL statement.
        """
        for k, v in dict(kwargs).items():
            field = get_instrumented_attr(self.model_type, k)
            statement = cast("StatementTypeT", statement.where(field == v))

        return statement

    @classmethod
    def get_id_attribute_value(
        cls,
        item: SQLAlchemyModelT | type[SQLAlchemyModelT],
        id_attribute: str | InstrumentedAttribute[Any] | None = None,
    ) -> Any:
        """Get value of attribute named as :attr:`id_attribute` on ``item``.

        Args:
            item: Anything that should have an attribute named as :attr:`id_attribute` value.
            id_attribute: Allows customization of the unique identifier to use for model fetching.
                Defaults to `None`, but can reference any surrogate or candidate key for the table.

        Returns:
            The value of attribute on ``item`` named as :attr:`id_attribute`.
        """
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
        """Return the ``item`` after the ID is set to the appropriate attribute.

        Args:
            item_id: Value of ID to be set on instance
            item: Anything that should have an attribute named as :attr:`id_attribute` value.
            id_attribute: Allows customization of the unique identifier to use for model fetching.
                Defaults to `None`, but can reference any surrogate or candidate key for the table.

        Returns:
            Item with ``item_id`` set to :attr:`id_attribute`
        """
        if id_attribute is None:
            id_attribute = cls.id_attribute

        if isinstance(id_attribute, InstrumentedAttribute):
            id_attribute = id_attribute.key

        setattr(item, id_attribute, item_id)

        return item

    def _build_match_filter(
        self,
        match_fields: List[str] | str | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build match filter from match_fields and kwargs.

        Args:
            match_fields: Fields to match for filtering. Can be a single field name,
                         list of field names, or None to use all kwargs.
            kwargs: Keyword arguments containing field values to match.

        Returns:
            Dictionary of field names to values for matching.
        """
        match_fields = [match_fields] if isinstance(match_fields, str) else match_fields or []
        if match_fields:
            return {
                field_name: kwargs.get(field_name) for field_name in match_fields if kwargs.get(field_name) is not None
            }
        return kwargs

    async def add(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        expunge: bool = True,
    ) -> SQLAlchemyModelT:
        """Add a model instance to the database.

        Args:
            session: Database session
            data: The model instance or dictionary to add.
            expunge: Whether to expunge the model instance from the session after adding.

        Returns:
            The added model instance.
        """
        model = self.model_type(**data) if isinstance(data, dict) else data
        await self._attach_to_session(session, model, strategy="insert", load=False)

        await session.flush()
        if expunge:
            # Flush to persist and get database-generated values (id, timestamps, etc.)
            session.expunge(model)

        return model

    async def add_many(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        data: Sequence[SQLAlchemyModelT | dict[str, Any]],
        *,
        expunge: bool = True,
    ) -> Sequence[SQLAlchemyModelT]:
        """Add multiple model instances to the database.

        Args:
            session: Database session
            data: The model instances or dictionaries to add.
            expunge: Whether to expunge the model instances from the session after adding.

        Returns:
            The added model instances.
        """
        data = [self.model_type(**item) if isinstance(item, dict) else item for item in data]
        session.add_all(data)

        if expunge:
            await session.flush()
            for model in data:
                session.expunge(model)

        return cast(Sequence[SQLAlchemyModelT], data)

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
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.

        Keyword Args:
            statement(Select[tuple[SQLAlchemyModelT]] | None): The statement to execute.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.
            uniquify(bool): Whether to ensure the result is unique.
            expunge(bool): Whether to automatically expunge the object from the session.
            **kwargs(dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            SQLAlchemyModelT | None: The model instance if found, otherwise None.
        """
        statement = self._build_query_statement(
            *filters,
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=kwargs,
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)
        instance = query_result.scalar_one_or_none()

        if instance and expunge:
            session.expunge(instance)

        return instance

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
        """Retrieves a single record from the database based on the provided filters.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session

        Keyword Args:
            item_id(Any): The ID of the item to retrieve.
            statement(Select[tuple[SQLAlchemyModelT]] | None): The statement to execute.
            id_attribute(str | InstrumentedAttribute[Any] | None): The attribute to use as the ID.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.
            uniquify(bool): Whether to ensure the result is unique.
            expunge(bool): Whether to automatically expunge the object from the session.

        Returns:
            SQLAlchemyModelT | None: The retrieved record, or None if not found.
        """
        statement = self._build_query_statement(
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=[(id_attribute or self.id_attribute, item_id)],
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)
        instance = query_result.scalar_one_or_none()

        if instance and expunge:
            session.expunge(instance)

        return instance

    async def get_and_update(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        with_for_update: bool | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **kwargs: dict[str, Any],
    ) -> tuple[SQLAlchemyModelT | None, bool]:
        """Retrieve and update a record based on the provided filters.

        Uses SELECT FOR UPDATE to prevent race conditions during concurrent updates.

        Args:
            session: Database session
            filters: Filters to apply to the query.

        Keyword Args:
            match_fields: Fields to match for update.
            attribute_names: Attributes to include in the update.
            with_for_update: Whether to use a "for update" lock.
            loader_options: Load specification for eager loading.
            execution_options: Additional execution options for the query.
            expunge: Whether to automatically expunge the object from the session.
            uniquify: Whether to ensure the result is unique.
            **kwargs: Additional keyword arguments for the query.

        Returns:
            tuple[SQLAlchemyModelT | None, bool]: A tuple containing the retrieved record and a boolean indicating
            whether it was updated.
        """
        match_filter = self._build_match_filter(match_fields, kwargs)

        # Use SELECT FOR UPDATE to lock the row and prevent race conditions
        statement = self.statement.with_for_update()

        existing_instance = await self.get_one(
            session,
            *filters,
            **match_filter,
            statement=statement,
            execution_options=execution_options,
            uniquify=uniquify,
            expunge=False,  # Keep in session for lock to remain active
        )

        if not existing_instance:
            return None, False

        updated = False
        for field_name, new_field_value in kwargs.items():
            field = getattr(existing_instance, field_name, MISSING)
            if field is not MISSING and field != new_field_value:
                updated = True
                setattr(existing_instance, field_name, new_field_value)

        # Only perform merge and refresh if changes were made
        if updated:
            existing_instance = await self._attach_to_session(session, existing_instance, strategy="merge", load=True)

            await session.refresh(
                existing_instance,
                attribute_names=attribute_names,
                with_for_update=with_for_update,
            )

        if expunge:
            session.expunge(existing_instance)

        return existing_instance, updated

    async def get_or_upsert(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        match_fields: List[str] | str | None = None,
        attribute_names: Iterable[str] | None = None,
        upsert: bool = False,
        with_for_update: bool | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **kwargs: dict[str, Any],
    ) -> tuple[SQLAlchemyModelT, bool]:
        """Retrieve or upsert a record based on the provided filters.

        Uses SELECT FOR UPDATE to prevent race conditions when checking existence
        before inserting new records.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            *filters(StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            match_fields(List[str] | str | None): Fields to match for upsert.
            attribute_names(Iterable[str] | None): Attributes to include in the upsert.
            upsert(bool): Whether to perform an upsert operation.
            with_for_update(bool | None): Whether to use a "for update" lock.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.
            expunge(bool): Whether to automatically expunge the object from the session.
            uniquify(bool): Whether to ensure the result is unique.
            **kwargs(dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            tuple[SQLAlchemyModelT, bool]: A tuple containing the retrieved or upserted record and a boolean indicating
            whether it was newly created.
        """
        match_filter = self._build_match_filter(match_fields, kwargs)

        # Use SELECT FOR UPDATE to lock the row and prevent race conditions
        statement = self.statement.with_for_update()

        existing_instance = await self.get_one(
            session,
            *filters,
            **match_filter,
            statement=statement,
            execution_options=execution_options,
            expunge=False,  # Keep in session for lock to remain active
        )

        if not existing_instance:
            # Row is locked, safe to insert
            return await self.add(session, data=kwargs, expunge=expunge), True

        # Record already exists - return False for "was_created"
        if upsert:
            for field_name, new_field_value in kwargs.items():
                field = getattr(existing_instance, field_name, MISSING)
                if field is not MISSING and field != new_field_value:
                    setattr(existing_instance, field_name, new_field_value)

            existing_instance = await self._attach_to_session(session, existing_instance, strategy="merge", load=True)

            await session.refresh(
                existing_instance,
                attribute_names=attribute_names,
                with_for_update=with_for_update,
            )

        if expunge:
            session.expunge(existing_instance)

        return existing_instance, False

    async def list_items(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **kwargs: dict[str, Any],
    ) -> Sequence[SQLAlchemyModelT]:
        """List all records from the database.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            order_by (List[OrderingPair] | OrderingPair | None): Ordering specification.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.
        """
        statement = self._build_query_statement(
            *filters,
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=kwargs,
            order_by=order_by,
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)
        instances = query_result.scalars().all()

        if expunge and instances:
            # Per-row expunge is intentional: expunge_all() would also detach
            # any other entities the caller has attached to the session.
            for instance in instances:
                session.expunge(instance)

        return instances

    async def list_and_count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        using_window_function: bool = True,
        **kwargs: dict[str, Any],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """List and count records from the database.

        Defaults to a single-query window-function strategy on Postgres
        (one round-trip instead of two). Pass ``using_window_function=False``
        to fall back to the basic two-query implementation if your dialect
        does not support window functions.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            *filters(StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement(Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            order_by(List[OrderingPair] | OrderingPair | None): Ordering specification.
            execution_options(dict[str, Any] | None): Additional execution options for the query.
            expunge(bool): Whether to automatically expunge the object from the session.
            uniquify(bool): Whether to ensure the result is unique.
            using_window_function(bool): Whether to use a window function to count the records.
            **kwargs(dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            tuple[Sequence[SQLAlchemyModelT], int]: A tuple containing the list of records and the count of records.
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
            **kwargs,
        )

    async def count(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> int:
        """Count records from the database.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            *filters(StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement(Select[tuple[SQLAlchemyModelT]] | None): The SQLAlchemy statement to execute.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.
            uniquify(bool): Whether to ensure the result is unique.
            **filter_kwargs(dict[str, Any] | Iterable[tuple[Any, Any]]): Additional keyword arguments for the query.

        Returns:
            int: The count of records.
        """
        statement = self._build_query_statement(
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
            count=True,
        )

        result = await self._execute(session, statement, uniquify=uniquify)
        return cast("int", result.scalar_one())

    async def update(  # noqa: C901
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        item_id: str | uuid.UUID | InstrumentedAttribute[Any],
        data: SQLAlchemyModelT | dict[str, Any],
        *,
        attribute_names: Iterable[str] | None = None,
        with_for_update: ForUpdateParameter = None,
        expunge: bool | None = None,
        execution_options: ExecutableOptions | None = None,
    ) -> SQLAlchemyModelT | None:
        """Update a record based on the provided data.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            item_id(StrUUID | InstrumentedAttribute[Any]): The ID of the record to update.
            data(SQLAlchemyModelT | dict[str, Any]): The data to update (model instance or dict).

        Keyword Args:
            attribute_names(Iterable[str] | None): Attributes to include in the update.
            with_for_update(ForUpdateParameter | None): Whether to use a "for update" lock.
            expunge(bool | None): Whether to automatically expunge the object from the session.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.

        Returns:
            SQLAlchemyModelT | None: The updated model instance, or None if not found.
        """
        # Store original data for updates
        update_data = data if isinstance(data, dict) else None

        # Convert dict to model instance to extract ID
        if isinstance(data, dict):
            data = self.model_type(**data)

        # Fetch existing instance
        existing_instance = await self.get_one_by_id(
            session,
            item_id=item_id,
            execution_options=execution_options,
            expunge=False,  # Keep instance attached to session for proper change tracking
        )

        if not existing_instance:
            return None

        # Apply updates from data to existing instance
        if update_data is not None:
            # Update from dict - only update provided fields
            for field_name, new_value in update_data.items():
                if hasattr(existing_instance, field_name):
                    setattr(existing_instance, field_name, new_value)
        else:
            # Update from model instance - copy all mapped attributes
            for column in self.model_type.__table__.columns:
                field_name = column.name
                if hasattr(data, field_name):
                    setattr(existing_instance, field_name, getattr(data, field_name))

        # Merge changes into session
        existing_instance = await self._attach_to_session(session, existing_instance, strategy="merge", load=True)

        await session.flush()
        if expunge:
            session.expunge(existing_instance)

        return existing_instance

    async def delete(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        item_id: Any,
        *,
        id_attribute: InstrumentedAttribute[Any] | str | None = None,
        expunge: bool | None = None,
        execution_options: ExecutableOptions | None = None,
    ) -> SQLAlchemyModelT | None:
        """Delete a record from the database.

        Args:
            session(AsyncSession | async_scoped_session[AsyncSession]): Database session
            item_id(Any): The ID of the record to delete.

        Keyword Args:
            id_attribute(InstrumentedAttribute[Any] | str | None): The attribute to use as the ID.
            expunge(bool | None): Whether to automatically expunge the object from the session.
            loader_options(LoaderOptions | None): Load specification for eager loading.
            execution_options(dict[str, Any] | None): Additional execution options for the query.

        Returns:
            SQLAlchemyModelT | None: The deleted record, or None if not found.
        """
        existing_instance = await self.get_one_by_id(
            session,
            item_id=item_id,
            id_attribute=id_attribute,
            execution_options=execution_options,
        )

        if not existing_instance:
            return None

        await session.delete(existing_instance)

        if expunge:
            session.expunge(existing_instance)

        return existing_instance

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
        """Delete records that match filters and return deleted instances when possible.

        Args:
            session: Database session
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            expunge (bool): Whether to automatically expunge the object from the session.
            uniquify (bool): Whether to ensure the result is unique.
            sanity_check (bool): Whether to perform a sanity check on the affected row count.
            **kwargs (dict[str, Any]): Additional keyword arguments for the query.

        Returns:
            Sequence[SQLAlchemyModelT] | None: The deleted instances.
        """
        statement = self._build_query_statement(
            *filters,
            statement=delete(self.model_type),
            execution_options=execution_options,
            filter_kwargs=kwargs,
        )

        dialect = self._get_dialect(session)
        if dialect.delete_executemany_returning:
            instances = await session.scalars(statement.returning(self.model_type))
        else:
            instances = await self.list_items(
                session,
                *filters,
                execution_options=execution_options,
                expunge=expunge,
                uniquify=uniquify,
            )

            query_result = await self._execute(session, statement=statement, uniquify=uniquify)
            row_count = getattr(query_result, "rowcount", 0)

            if sanity_check and row_count > 0 and len(instances) != row_count:
                return None

        return cast("Sequence[SQLAlchemyModelT]", instances)

    async def _find_exists(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        execution_options: ExecutableOptions | None = None,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> bool:
        """Check if a record exists in the database based on the provided filters.

        Uses EXISTS query with LIMIT 1 for optimal performance instead of COUNT.

        Args:
            session: Database session
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            loader_options (LoaderOptions | None): Load specification for eager loading.
            execution_options (dict[str, Any] | None): Additional execution options for the query.
            uniquify (bool): Whether to ensure the result is unique.
            **filter_kwargs (dict[str, Any] | Iterable[tuple[Any, Any]]): Additional keyword arguments for the query.

        Returns:
            bool: True if a record exists, False otherwise.
        """
        # Build the inner SELECT with the user filters applied.
        inner = self._build_query_statement(
            *filters,
            statement=self.statement,
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
        )

        # Wrap in SELECT EXISTS(SELECT 1 ... LIMIT 1) so the engine short-circuits
        # at the first matching row instead of counting / projecting columns.
        existence_query = select(exists(inner.with_only_columns(literal(1)).limit(1)))

        result = await self._execute(session, existence_query, uniquify=uniquify)
        return bool(result.scalar())

    def _get_soft_delete_filter(self) -> ColumnElement[bool] | None:
        """Get soft delete filter if model has deleted_at attribute.

        Returns:
            ColumnElement[bool] | None: Filter to exclude soft-deleted records, or None if model doesn't support soft delete.
        """
        try:
            deleted_at_attr = getattr(self.model_type, "deleted_at", None)
            if deleted_at_attr is not None:
                return deleted_at_attr.is_(None)
        except AttributeError:
            pass
        return None

    def _apply_execution_options(
        self,
        statement: StatementTypeT,
        execution_options: ExecutableOptions | None,
    ) -> StatementTypeT:
        """Apply execution options if provided."""
        if not execution_options:
            return statement

        return cast("StatementTypeT", statement.execution_options(**execution_options))

    def _apply_filter_kwargs(
        self,
        statement: StatementTypeT,
        filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]] | None,
    ) -> StatementTypeT:
        """Apply keyword filters when present."""
        if not filter_kwargs:
            return statement

        return cast("StatementTypeT", self.filter_select_by_kwargs(statement, kwargs=filter_kwargs))

    def _apply_count_projection(self, statement: StatementTypeT, *, enable: bool = False) -> StatementTypeT:
        """Apply count projection when requested."""
        if not enable:
            return statement

        return (
            statement.with_only_columns(sql_func.count(text("1")), maintain_column_froms=True).limit(None).offset(None)
        )

    def _build_query_statement(
        self,
        *filters: StatementFilter | ColumnElement[bool],
        statement: StatementTypeT,
        execution_options: ExecutableOptions | None = None,
        filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        count: bool = False,
    ) -> StatementTypeT:
        """Return the query statement with the loader options and execution options applied.

        Args:
            *filters (StatementFilter | ColumnElement[bool]): Filters to apply to the query.
            statement (StatementTypeT): The statement to apply the loader options and execution options to.

        Keyword Args:
            execution_options (dict[str, Any] | None): The execution options to apply to the statement.
            filter_kwargs: Additional keyword arguments for the query.
            order_by (List[OrderingPair] | OrderingPair | None): Ordering to apply to the query.
            count: Whether to apply a count query.

        Returns:
            StatementTypeT: The query statement with the loader options and execution options applied.
        """
        # Apply soft delete filter for SELECT queries only (not for DELETE/UPDATE)
        soft_delete_filter = None
        if isinstance(statement, Select):
            soft_delete_filter = self._get_soft_delete_filter()

        # Combine filters: user filters first, then soft delete filter
        all_filters = list(filters)
        if soft_delete_filter is not None:
            all_filters.append(soft_delete_filter)

        statement = cast("StatementTypeT", self.apply_filter(statement, *all_filters))

        statement = self._apply_execution_options(statement, execution_options)
        statement = self._apply_filter_kwargs(statement, filter_kwargs)

        if order_by is not None:
            statement = self.apply_order_by(statement, order_by)

        return self._apply_count_projection(statement, enable=count)

    async def _attach_to_session(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        model: SQLAlchemyModelT,
        *,
        strategy: Literal["insert", "merge"] = "insert",
        load: bool = True,
    ) -> SQLAlchemyModelT:
        """Attach a model instance to the session.

        Args:
            session: Database session
            model: The model instance to attach.
            strategy: The strategy to use when attaching the model instance to the session.
            load: Whether to load the model instance after attaching it to the session.

        Returns:
            The attached model instance.

        Raises:
            ValueError: If strategy is not 'insert' or 'merge'.
        """
        if strategy == "insert":
            session.add(model)
            return model
        if strategy == "merge":
            return await session.merge(model, load=load)
        raise ValueError(f"Invalid strategy: {strategy}. Must be 'insert' or 'merge'.")

    async def _execute(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        statement: StatementTypeT,
        *,
        uniquify: bool = True,
    ) -> Result[tuple[SQLAlchemyModelT]]:
        """Execute a statement and return the result.

        Args:
            session: Database session
            statement (Select[tuple[SQLAlchemyModelT]]): The statement to execute.

        Keyword Args:
            uniquify (bool): Whether to ensure the result is unique.

        Returns:
            Result[tuple[SQLAlchemyModelT]]: The result of the statement.
        """
        result = await session.execute(statement)

        if uniquify:
            result = result.unique()

        return result

    async def _list_with_count_basic(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        """List with count using a basic approach."""
        count_result = await self.count(
            session,
            *filters,
            statement=statement,
            execution_options=execution_options,
            uniquify=uniquify,
            **filter_kwargs,
        )

        if count_result == 0:
            return [], 0

        statement = self._build_query_statement(
            *filters,
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
            order_by=order_by,
        )

        query_result = await self._execute(session, statement, uniquify=uniquify)

        instances: list[SQLAlchemyModelT] = []
        for (instance,) in query_result:
            if expunge:
                session.expunge(instance)

            instances.append(instance)

        return instances, count_result

    async def _list_with_count_window_function(
        self,
        session: AsyncSession | async_scoped_session[AsyncSession],
        *filters: StatementFilter | ColumnElement[bool],
        statement: Select[tuple[SQLAlchemyModelT]] | None = None,
        order_by: List[OrderingPair] | OrderingPair | None = None,
        execution_options: ExecutableOptions | None = None,
        expunge: bool = True,
        uniquify: bool = True,
        **filter_kwargs: dict[str, Any] | Iterable[tuple[Any, Any]],
    ) -> tuple[Sequence[SQLAlchemyModelT], int]:
        statement = self._build_query_statement(
            *filters,
            statement=statement if statement is not None else self.statement,
            execution_options=execution_options,
            filter_kwargs=filter_kwargs,
            order_by=order_by,
        )

        statement = statement.add_columns(over(sql_func.count()))
        result = await self._execute(session, statement, uniquify=uniquify)

        count: int = 0
        instances: list[SQLAlchemyModelT] = []
        for i, (instance, count_value) in enumerate(result):
            if expunge:
                session.expunge(instance)

            instances.append(instance)

            if i == 0:
                count = count_value

        return instances, count

    @classmethod
    def _get_dialect(cls, session: AsyncSession | async_scoped_session[AsyncSession]) -> Dialect:
        """Get the dialect from a session."""
        return session.bind.dialect if getattr(session, "bind", None) else session.get_bind().dialect

    @property
    def model(self) -> type[SQLAlchemyModelT]:
        """Get the model type for this repository."""
        return self.model_type
