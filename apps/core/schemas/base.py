from typing import TypeVar

from pydantic import BaseModel, ConfigDict

SchemaT = TypeVar("SchemaT", bound="BaseObjectSchema")


class BaseObjectSchema(BaseModel):
    """Base schema for all objects."""

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=True,
    )
