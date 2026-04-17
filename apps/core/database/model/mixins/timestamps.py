import datetime

from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column

from apps.core.database.types import DateTimeUTC


@declarative_mixin
class CreatedAtMixin:
    """Mixin for adding "created_at" field."""

    @declared_attr
    def created_at(self) -> Mapped[datetime.datetime]:
        """Attribute for the creation date and time of the object."""
        return mapped_column(
            DateTimeUTC(timezone=True),
            default=lambda _: datetime.datetime.now(datetime.UTC),
            nullable=False,
        )

    def __repr__(self) -> str:
        """String representation of the created_at attribute."""
        return f'{self.__class__.__name__}(created_at="{self.created_at}")'


@declarative_mixin
class UpdatedAtMixin:
    """Mixin for adding "updated_at" field."""

    @declared_attr
    def updated_at(self) -> Mapped[datetime.datetime]:
        """Attribute for the last update date and time of the object."""
        return mapped_column(
            DateTimeUTC(timezone=True),
            default=lambda _: datetime.datetime.now(datetime.UTC),
            onupdate=lambda _: datetime.datetime.now(datetime.UTC),
            nullable=False,
        )

    def __repr__(self) -> str:
        """String representation of the updated_at attribute."""
        return f'{self.__class__.__name__}(updated_at="{self.updated_at}")'


@declarative_mixin
class HasTimestampMixin(CreatedAtMixin, UpdatedAtMixin):
    """Mixin for adding "created_at" and "updated_at" fields."""
