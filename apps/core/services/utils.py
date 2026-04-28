from collections.abc import Sequence
from typing import Any, ClassVar, overload

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.engine import Row

from apps.core.database.filters import LimitOffsetPaginationFilter
from apps.core.database.types import RowMappingT, SQLAlchemyModelT
from apps.core.schemas import BaseObjectSchema, PaginatedResponse, SchemaT

type DataT = SQLAlchemyModelT | RowMappingT | Row[Any] | dict[str, Any]


class ResultConverter:
    """Converter for transforming repository results to Pydantic schemas.

    Provides flexible conversion from database models, rows, and mappings
    to typed Pydantic schemas with support for pagination.

    Performance optimizations:
    - Uses TypeAdapter for bulk validation (2-3x faster than loop)
    - Caches TypeAdapter instances per schema type
    - Preserves detailed ValidationError context
    """

    # Cache TypeAdapter instances for reuse across conversions
    _adapter_cache: ClassVar[dict[type[BaseObjectSchema], TypeAdapter[Any]]] = {}
    _list_adapter_cache: ClassVar[dict[type[BaseObjectSchema], TypeAdapter[Any]]] = {}

    @classmethod
    def _get_adapter(cls, schema_type: type[SchemaT]) -> TypeAdapter[SchemaT]:
        """Return a cached TypeAdapter for the given schema type."""
        adapter = cls._adapter_cache.get(schema_type)
        if adapter is None:
            adapter = TypeAdapter(schema_type)
            cls._adapter_cache[schema_type] = adapter
        return adapter

    @classmethod
    def _get_list_adapter(cls, schema_type: type[SchemaT]) -> TypeAdapter[list[SchemaT]]:
        """Return a cached TypeAdapter for ``list[schema_type]``."""
        adapter = cls._list_adapter_cache.get(schema_type)
        if adapter is None:
            adapter = TypeAdapter(list[schema_type])  # type: ignore[valid-type]
            cls._list_adapter_cache[schema_type] = adapter
        return adapter

    def _convert_single(self, data: DataT, schema_type: type[SchemaT]) -> SchemaT:
        """Convert single item with enhanced error context.

        Args:
            data: Single data item to convert.
            schema_type: Target schema type.

        Returns:
            Converted schema instance.

        Raises:
            ValueError: With preserved ValidationError details.
        """
        try:
            return self._get_adapter(schema_type).validate_python(data)
        except ValidationError as e:
            data_type = type(data).__name__
            error_details = "\n".join(f"  - {err['loc']}: {err['msg']}" for err in e.errors())
            raise ValueError(f"Failed to convert {data_type} to {schema_type.__name__}:\n{error_details}") from e

    def _convert_bulk(self, data: Sequence[DataT], schema_type: type[SchemaT]) -> list[SchemaT]:
        """Convert sequence using optimized bulk validation.

        Uses TypeAdapter for ~2-3x performance improvement over loop-based validation.
        Falls back to item-by-item validation if bulk validation fails to provide
        detailed error location.

        Args:
            data: Sequence of data items to convert.
            schema_type: Target schema type.

        Returns:
            List of converted schema instances.

        Raises:
            ValueError: With detailed error context including failing item index.
        """
        if not data:
            return []

        try:
            list_adapter = self._get_list_adapter(schema_type)
            return list_adapter.validate_python(data)
        except ValidationError:
            items = []
            adapter = self._get_adapter(schema_type)
            for idx, item in enumerate(data):
                try:
                    items.append(adapter.validate_python(item))
                except ValidationError as e:
                    item_type = type(item).__name__
                    error_details = "\n".join(f"  - {err['loc']}: {err['msg']}" for err in e.errors())
                    raise ValueError(
                        f"Failed to convert {item_type} at index {idx} to {schema_type.__name__}:\n{error_details}"
                    ) from e
            return items

    @overload
    def to_schema(
        self,
        data: DataT | None,
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> SchemaT | DataT | None: ...

    @overload
    def to_schema(
        self,
        data: Sequence[DataT],
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> Sequence[SchemaT] | Sequence[DataT]: ...

    @overload
    def to_schema(
        self,
        data: Sequence[DataT],
        total: int,
        pagination_filter: LimitOffsetPaginationFilter | None = None,
        *,
        schema_type: type[SchemaT],
    ) -> PaginatedResponse[SchemaT]: ...

    def to_schema(
        self,
        data: DataT | Sequence[DataT] | None,
        total: int | None = None,
        pagination_filter: LimitOffsetPaginationFilter | None = None,
        *,
        schema_type: type[SchemaT] | None = None,
    ) -> SchemaT | Sequence[SchemaT] | PaginatedResponse[SchemaT] | DataT | Sequence[DataT] | None:
        """Convert database results to Pydantic schemas.

        Handles None values and optional schema_type for flexible conversion.

        Args:
            data(DataT | Sequence[DataT] | None): Single item, sequence of items, or None to convert.
            total(int | None): Total count for pagination (optional).
            pagination_filter(LimitOffsetPaginationFilter | None): Pagination filters (optional).

        Keyword Args:
            schema_type(Type[SchemaT] | None): Target Pydantic schema type (optional).

        Returns:
            Converted schema(s), original data, or None based on inputs.

        Raises:
            ValueError: If validation fails during schema conversion.
        """
        # Handle None data
        if data is None:
            return None

        # Handle no schema_type - return data as-is
        if schema_type is None:
            if total is not None and isinstance(data, Sequence):
                # Return as tuple for pagination without schema
                return data, total
            return data

        # Single item conversion
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            return self._convert_single(data, schema_type)

        # Bulk sequence conversion with optimization
        items = self._convert_bulk(data, schema_type)

        # Paginated result
        if total is not None:
            limit = pagination_filter.limit if pagination_filter else len(items)
            offset = pagination_filter.offset if pagination_filter else 0
            return PaginatedResponse[schema_type](
                items=items,
                total=total,
                limit=limit,
                offset=offset,
            )

        return items
