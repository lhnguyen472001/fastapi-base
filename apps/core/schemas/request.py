from typing import Any

from fastapi import Query
from pydantic import Field

from .base import BaseObjectSchema


class RequestObjectSchema(BaseObjectSchema):
    """Base schema for all request objects."""

    @classmethod
    def collect_alias(cls) -> dict[str, Any]:
        """Collect the alias for the schema."""
        collection = {}
        for f_name, f_obj in cls.model_fields.items():
            if f_obj.alias:
                collection.update({f_obj.alias: f_name})
            else:
                collection.update({f_name: f_name})

        return collection


class OffsetPaginationRequestSchema(RequestObjectSchema):
    """Schema for offset-based pagination requests."""

    limit: int = Field(default=20, ge=1, le=1000, description="Number of items per page")
    offset: int = Field(default=0, description="Offset of current page")


class OrderByRequestSchema(RequestObjectSchema):
    """Schema for ordering requests."""

    orders: list[str] | None = Field(
        Query(
            default_factory=list,
            description="Order by fields with format: field[asc] or field[desc]",
        )
    )
