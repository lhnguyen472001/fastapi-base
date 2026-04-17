"""Generic read/write/read+write SQLAlchemy service bases.

Return-type convention
----------------------

Service methods may return either ORM models or Pydantic schemas:

* **Route-facing public methods** should prefer returning the ORM model and
  let the route convert via ``ResponseSchema.model_validate(obj)``. This is
  the default pattern everywhere in this project.
* **Inter-service calls** always use the ORM model, because consumers
  (e.g. :class:`apps.auth.services.AuthService` reading ``user.is_2fa_enabled``
  / ``user.hashed_password`` from :meth:`apps.user.services.UserService.get_by_id`)
  need ORM-only attributes and relationships that Pydantic response schemas
  deliberately hide.
* The optional ``schema_type=`` argument on the base methods below is a
  convenience that routes are free to use when no inter-service reuse is
  expected; domain services currently omit it and return models.

In short: returning the model is always safe for inter-service consumers;
returning a schema is a route-layer responsibility and should not be done
from methods that will also be called by another service.
"""

from collections.abc import Sequence
from typing import Any, Generic

from sqlalchemy.sql.elements import ColumnElement

from apps.core.database.filters import StatementFilter
from apps.core.database.repository import SQLAlchemyRepositoryProtocol
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType, SQLAlchemyModelT
from apps.core.schemas.base import SchemaT
from apps.core.services.utils import ResultConverter


class BaseSQLAlchemyService(ResultConverter, Generic[SQLAlchemyModelT]):
    """Base service class for all services."""

    repository: SQLAlchemyRepositoryProtocol[SQLAlchemyModelT]

    def __init__(self, repository: SQLAlchemyRepositoryProtocol[SQLAlchemyModelT]) -> None:
        """Initialize service with repository.

        Args:
            repository: Repository instance for data access.
        """
        self.repository = repository


class SQLAlchemyReadService(BaseSQLAlchemyService[SQLAlchemyModelT], Generic[SQLAlchemyModelT]):  # type: ignore[type-arg]
    """Read-only SQLAlchemy service."""

    async def get_by_id(
        self,
        session: SessionType,
        item_id: Any,
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> SchemaT | SQLAlchemyModelT | None:
        """Retrieve a single record by ID.

        Args:
            session: Database session for the operation.
            item_id: The ID of the record to retrieve.
            schema_type: Optional schema type for automatic conversion.

        Returns:
            The retrieved record as schema (if schema_type provided) or model,
            or None if not found.

        Example:
            # Return as model
            user = await service.get_by_id(session, 1)

            # Return as schema
            user_schema = await service.get_by_id(
                session, 1, schema_type=UserSchema
            )
        """
        result = await self.repository.get_one_by_id(session, item_id=item_id, expunge=True)
        return self.to_schema(result, schema_type=schema_type)

    async def get_one(
        self,
        session: SessionType,
        filters: SchemaT | None = None,
        *,
        schema_type: type[SchemaT] | None = None,
        **kwargs: Any,
    ) -> SchemaT | SQLAlchemyModelT | None:
        """Retrieve a single record by filters.

        Args:
            session: Database session for the operation.
            filters: Pydantic schema with filter fields (e.g., age[gt], status)
            schema_type: Optional schema type for automatic conversion.
            **kwargs: Additional filter criteria.

        Returns:
            The retrieved record as schema or model, or None if not found.
        """
        parsed_filters = filters.model_dump(by_alias=True, exclude_none=True) if filters else []
        result = await self.repository.get_one(session, *parsed_filters, **kwargs)
        return self.to_schema(result, schema_type=schema_type)

    async def list_items(
        self,
        session: SessionType,
        filters: SchemaT | Sequence[StatementFilter | ColumnElement[bool]] | None = None,
        schema_type: type[SchemaT] | None = None,
        **kwargs: Any,
    ) -> Sequence[SchemaT] | Sequence[SQLAlchemyModelT]:
        """List all records matching filters.

        Args:
            session: Database session for the operation.
            filters: Can be one of:
                - Pydantic schema with filter fields (e.g., age[gt], status)
                - Sequence of StatementFilter or ColumnElement[bool] objects
                - None for no filters
            schema_type: Optional schema type for automatic conversion.
            **kwargs: Additional filter criteria (order_by, limit, etc.).

        Returns:
            Sequence of records as schemas or models.
        """
        # Handle different filter types
        parsed_filters: list[StatementFilter | ColumnElement[bool]]
        if filters is None:
            parsed_filters = []
        elif isinstance(filters, Sequence) and not isinstance(filters, (str, bytes)):
            # Already a sequence of StatementFilter or ColumnElement
            parsed_filters = list(filters)
        else:
            parsed_filters = filters.model_dump(by_alias=True, exclude_none=True)

        results = await self.repository.list_items(session, *parsed_filters, **kwargs)

        if schema_type is not None:
            return self.to_schema(results, schema_type=schema_type)

        return results

    async def list_with_count(
        self,
        session: SessionType,
        filters: SchemaT | None = None,
        *,
        schema_type: type[SchemaT] | None = None,
        **kwargs: Any,
    ) -> tuple[Sequence[SchemaT | SQLAlchemyModelT], int]:
        """List records with total count.

        Args:
            session: Database session for the operation.
            filters: Pydantic schema with filter fields (e.g., age[gt], status)
            schema_type: Optional schema type for automatic conversion.
            **kwargs: Additional filter criteria.

        Returns:
            Tuple of (records, total_count).
        """
        parsed_filters = filters.model_dump(by_alias=True, exclude_none=True) if filters else []
        results, count = await self.repository.list_and_count(session, *parsed_filters, **kwargs)
        return self.to_schema(results, schema_type=schema_type), count


class SQLAlchemyWriteService(BaseSQLAlchemyService[SQLAlchemyModelT]):  # type: ignore[type-arg]
    """Write-only SQLAlchemy service."""

    @transactional
    async def create(
        self,
        session: SessionType,
        data: dict[str, Any] | SchemaT,
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> SchemaT:
        """Create a new record.

        Args:
            session: Database session for the operation.
            data: Data for the new record (dict or model instance).
            schema_type: Optional schema type for automatic conversion.

        Returns:
            The created record as schema or model.

        Example:
            user = await service.create(
                session,
                data={"name": "John", "email": "john@example.com"},
                schema_type=UserSchema
            )
        """
        result = await self.repository.add(session, data, expunge=True)
        return self.to_schema(result, schema_type=schema_type)

    @transactional
    async def create_many(
        self,
        session: SessionType,
        data: Sequence[dict[str, Any] | SchemaT],
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> Sequence[SchemaT]:
        """Create multiple records.

        Args:
            session: Database session for the operation.
            data: Sequence of data for new records.
            schema_type: Optional schema type for automatic conversion.

        Returns:
            Sequence of created records as schemas or models.

        Example:
            users = await service.create_many(
                session,
                data=[
                    {"name": "John", "email": "john@example.com"},
                    {"name": "Jane", "email": "jane@example.com"},
                ],
                schema_type=UserSchema
            )
        """
        results = await self.repository.add_many(session, data, expunge=True)
        return self.to_schema(results, schema_type=schema_type)

    async def update(
        self,
        session: SessionType,
        item_id: Any,
        data: dict[str, Any] | SchemaT,
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> SchemaT | SQLAlchemyModelT | None:
        """Update an existing record.

        Args:
            session: Database session for the operation.
            item_id: ID of the record to update.
            data: Updated data (dict or model instance).
            schema_type: Optional schema type for automatic conversion.

        Returns:
            The updated record as schema or model, or None if not found.

        Example:
            user = await service.update(
                session,
                item_id=1,
                data={"name": "Jane"},
                schema_type=UserSchema
            )
        """
        data = data.model_dump(exclude_unset=True) if not isinstance(data, dict) else data
        result = await self.repository.update(session, item_id=item_id, data=data)

        if not result:
            return None

        if schema_type is not None:
            return self.to_schema(result, schema_type=schema_type)

        return result

    @transactional
    async def upsert(
        self,
        session: SessionType,
        data: dict[str, Any],
        *,
        match_fields: list[str] | str | None = None,
        schema_type: type[SchemaT] | None = None,
        **kwargs: Any,
    ) -> tuple[SchemaT | SQLAlchemyModelT, bool]:
        """Create or update a record.

        Args:
            session: Database session for the operation.
            data: Data for the record.
            match_fields: Fields to match for finding existing record.
            schema_type: Optional schema type for automatic conversion.
            **kwargs: Additional criteria for matching.

        Returns:
            Tuple of (record, was_created).

        Example:
            user, created = await service.upsert(
                session,
                data={"email": "john@example.com", "name": "John"},
                match_fields="email",
                schema_type=UserSchema
            )
            if created:
                logger.info("Created new user")
            else:
                logger.info("Updated existing user")
        """
        result, was_created = await self.repository.get_or_upsert(
            session, match_fields=match_fields, upsert=True, **data, **kwargs
        )
        if schema_type is not None:
            return self.to_schema(result, schema_type=schema_type), was_created

        return result, was_created

    async def delete(
        self,
        session: SessionType,
        item_id: Any,
    ) -> SQLAlchemyModelT | None:
        """Delete a record by ID.

        Args:
            session: Database session for the operation.
            item_id: ID of the record to delete.

        Returns:
            The deleted record, or None if not found.

        Example:
            deleted_user = await service.delete(session, item_id=1)
            if deleted_user:
                logger.info("Deleted user: {name}", name=deleted_user.name)
        """
        return await self.repository.delete(session, item_id)

    async def delete_where(
        self,
        session: SessionType,
        *filters: StatementFilter | ColumnElement[bool],
        **kwargs: Any,
    ) -> Sequence[SQLAlchemyModelT] | None:
        """Delete records matching filters.

        Args:
            session: Database session for the operation.
            *filters: Filter conditions to apply.
            **kwargs: Additional filter criteria.

        Returns:
            Sequence of deleted records, or None if operation failed.

        Example:
            # Delete inactive users
            deleted = await service.delete_where(
                session,
                User.is_active == False,
                User.last_login < datetime.now() - timedelta(days=365)
            )
            logger.info("Deleted {count} inactive users", count=len(deleted))
        """
        return await self.repository.delete_where(session, *filters, **kwargs)


class SQLAlchemyService(
    SQLAlchemyReadService[SQLAlchemyModelT],
    SQLAlchemyWriteService[SQLAlchemyModelT],
    Generic[SQLAlchemyModelT],
):
    """SQLAlchemy service that combines read and write operations."""
