import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, declared_attr

from libs.database.sql.registry import MetadataRegistry, orm_registry

from .mixins import BigIntPrimaryKeyMixin, HasTimestampMixin, UUIDPrimaryKeyMixin


class BaseAttributes:
    """Basic attributes for SQLAlchemy tables and queries.

    Provides a method to convert the model to a Dictionary representation.

    Methods:
        to_Dict: Converts the model to a Dictionary, excluding specified fields. :no-index:
    """

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """Convert the model instance to a dictionary.

        Args:
            exclude (set, optional): A set of attribute names to exclude from the dictionary. Defaults to None.

        Returns:
            dict: A dictionary representation of the model instance.
        """
        # In SQLAlchemy 2.x, unloaded is a set, not a method
        unloaded: set[Any] = getattr(self._sa_instance_state, "unloaded", set())
        exclude = {"sa_orm_sentinel", "_sentinel"}.union(unloaded).union(exclude or [])
        return {
            field: getattr(self, field)
            for field in self.__mapper__.columns.keys()  # noqa: SIM118
            if field not in exclude
        }


class CommonTableAttributes(BaseAttributes):
    """Common attributes for SQLAlchemy tables.

    Inherits from :class:`BasicAttributes` and provides a mechanism to infer table names from class names.

    Attributes:
        __tablename__ (str): The inferred table name.
    """

    pattern = re.compile(r"(?<!^)(?=[A-Z])")

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:  # noqa: PLW3201
        """Dynamic attribute for create name of table in database."""
        return cls.pattern.sub("_", cls.__name__).lower() + "s"


class AdvancedDeclarativeBase(DeclarativeBase):
    """A subclass of declarative base that allows for overriding of the registry.

    Inherits from :class:`sqlalchemy.orm.DeclarativeBase`.

    Attributes:
        registry (:class:`sqlalchemy.orm.registry`): The registry for the declarative base.
        __metadata_registry__ (:class:`~base.MetadataRegistry`): The metadata registry.
        __bind_key__ (Optional[:class:`str`]): The bind key for the metadata.
    """

    registry = orm_registry
    __abstract__ = True
    __metadata_registry__: MetadataRegistry = MetadataRegistry()
    __bind_key__: str | None = None

    def __init_subclass__(cls, **kw: dict[str, Any]) -> None:  # noqa: D105
        bind_key = getattr(cls, "__bind_key__", None)
        if bind_key:
            cls.metadata = cls.__metadata_registry__.get(bind_key)
        elif None not in cls.__metadata_registry__ and getattr(cls, "metadata", None):
            cls.__metadata_registry__[None] = cls.metadata
        super().__init_subclass__(**kw)


class UUIDBase(
    AsyncAttrs,
    CommonTableAttributes,
    AdvancedDeclarativeBase,
    UUIDPrimaryKeyMixin,
):
    """Base for all SQLAlchemy declarative models with UUID v4 primary keys.

    .. seealso::
        :class:`CommonTableAttributes`
        :class:`mixins.UUIDPrimaryKeyMixin`
        :class:`AdvancedDeclarativeBase`
        :class:`AsyncAttrs`
    """

    __abstract__ = True


class UUIDAuditBase(
    CommonTableAttributes,
    UUIDPrimaryKeyMixin,
    HasTimestampMixin,
    AdvancedDeclarativeBase,
    AsyncAttrs,
):
    """Base for declarative models with UUID v4 primary keys and audit columns.

    . seealso::
        :class:`CommonTableAttributes`
        :class:`mixins.UUIDPrimaryKey`
        :class:`mixins.AuditColumns`
        :class:`AdvancedDeclarativeBase`
        :class:`AsyncAttrs`
    """

    __abstract__ = True


class BigIntBase(
    AsyncAttrs,
    CommonTableAttributes,
    AdvancedDeclarativeBase,
    BigIntPrimaryKeyMixin,
):
    """Base for all SQLAlchemy declarative models with BigInt primary keys.

    .. seealso::
        :class:`mixins.BigIntPrimaryKey`
        :class:`CommonTableAttributes`
        :class:`AdvancedDeclarativeBase`
        :class:`AsyncAttrs`
    """

    __abstract__ = True


class BigIntAuditBase(
    AsyncAttrs,
    CommonTableAttributes,
    AdvancedDeclarativeBase,
    BigIntPrimaryKeyMixin,
    HasTimestampMixin,
):
    """Base for declarative models with BigInt primary keys and audit columns.

    .. seealso::
        :class:`CommonTableAttributes`
        :class:`mixins.BigIntPrimaryKey`
        :class:`mixins.AuditColumns`
        :class:`AdvancedDeclarativeBase`
        :class:`AsyncAttrs`
    """

    __abstract__ = True


class DefaultBase(CommonTableAttributes, AdvancedDeclarativeBase, AsyncAttrs):
    """Base for all SQLAlchemy declarative models.  No primary key is added.

    .. seealso::
        :class:`CommonTableAttributes`
        :class:`AdvancedDeclarativeBase`
        :class:`AsyncAttrs`
    """

    __abstract__ = True
