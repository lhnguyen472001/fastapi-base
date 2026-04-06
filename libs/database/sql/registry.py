import datetime
import uuid
from collections.abc import Iterator
from typing import Any, Self, TypeAlias, cast

from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import registry as SQLAlchemyRegistry  # noqa: N812
from sqlalchemy.sql.schema import _NamingSchemaParameter as NamingSchemaParameter  # pyright: ignore[reportPrivateUsage]
from sqlalchemy.types import TypeEngine

from .types import DateTimeUTC

__all__ = [
    "MetadataRegistry",
    "metadata_registry",
    "orm_registry",
]

"""Templates for automated constraint name generation."""
NAMING_CONVENTION: NamingSchemaParameter = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TypeAnnotationMap: TypeAlias = dict[Any, type[TypeEngine[Any]] | TypeEngine[Any]]


def create_registry(custom_annotation_map: TypeAnnotationMap | None = None) -> SQLAlchemyRegistry:
    """Create a new SQLAlchemy registry.

    Args:
        custom_annotation_map (dict, optional): Custom type annotations to use for the registry.

    Returns:
        :class:`sqlalchemy.orm.registry`: A new SQLAlchemy registry with the specified type annotations.
    """
    meta = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: TypeAnnotationMap = {
        uuid.UUID: PGUUID,
        datetime.datetime: DateTimeUTC,
        dict: PGJSONB,
        dict[str, Any]: PGJSONB,
        dict[str, str]: PGJSONB,
    }

    if custom_annotation_map:
        type_annotation_map.update(custom_annotation_map)

    return SQLAlchemyRegistry(metadata=meta, type_annotation_map=type_annotation_map)


orm_registry = create_registry()


class MetadataRegistry:
    """A registry for metadata.

    Provides methods to get and set metadata for different bind keys.

    Methods:
        get: Retrieves the metadata for a given bind key.
        set: Sets the metadata for a given bind key.
    """

    _instance: Self | None = None
    _registry: dict[str | None, MetaData] = {None: orm_registry.metadata}  # noqa: RUF012

    def __new__(cls) -> Self:
        """Create a new instance of MetadataRegistry.

        Returns:
            MetadataRegistry: The singleton instance of MetadataRegistry.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cast(Self, cls._instance)

    def get(self, bind_key: str | None = None) -> MetaData:
        """Get the metadata for the given bind key."""
        return self._registry.setdefault(bind_key, MetaData(naming_convention=NAMING_CONVENTION))

    def set(self, bind_key: str | None, metadata: MetaData) -> None:
        """Set the metadata for the given bind key."""
        self._registry[bind_key] = metadata

    def __iter__(self) -> Iterator[str | None]:  # noqa: D105
        return iter(self._registry)

    def __getitem__(self, bind_key: str | None) -> MetaData:  # noqa: D105
        return self._registry[bind_key]

    def __setitem__(self, bind_key: str | None, metadata: MetaData) -> None:  # noqa: D105
        self._registry[bind_key] = metadata

    def __contains__(self, bind_key: str | None) -> bool:  # noqa: D105
        return bind_key in self._registry


metadata_registry = MetadataRegistry()
