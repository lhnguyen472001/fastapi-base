import datetime
import uuid
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB, UUID as PGUUID
from sqlalchemy.orm import registry as SQLAlchemyRegistry  # noqa: N812
from sqlalchemy.sql.schema import _NamingSchemaParameter as NamingSchemaParameter  # pyright: ignore[reportPrivateUsage]
from sqlalchemy.types import TypeEngine

from .types import DateTimeUTC

__all__ = [
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

type TypeAnnotationMap = dict[Any, type[TypeEngine[Any]] | TypeEngine[Any]]


def create_registry(
    custom_annotation_map: TypeAnnotationMap | None = None,
) -> SQLAlchemyRegistry:
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


def _new_metadata() -> MetaData:
    """Build a fresh MetaData with the project naming convention."""
    return MetaData(naming_convention=NAMING_CONVENTION)


# Module-level registry mapping bind_key -> MetaData. The default key (None)
# always points at the shared orm_registry.metadata so models without a
# __bind_key__ register against the same metadata used everywhere else.
metadata_registry: dict[str | None, MetaData] = {None: orm_registry.metadata}


def get_metadata(bind_key: str | None = None) -> MetaData:
    """Return (and lazily create) the MetaData for a given bind key."""
    return metadata_registry.setdefault(bind_key, _new_metadata())
