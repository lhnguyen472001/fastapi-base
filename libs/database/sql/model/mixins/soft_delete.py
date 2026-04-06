import datetime

from libs.database.sql.types import DateTimeUTC
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column


@declarative_mixin
class HasSoftDeletedMixin:
    """Mixin for adding "deleted_at" field."""

    @classmethod
    @declared_attr
    def deleted_at(cls) -> Mapped[datetime.datetime | None]:
        """Soft delete column."""
        return mapped_column(DateTimeUTC(timezone=True), nullable=True)

    def delete(self) -> None:
        """Soft delete object."""
        self.deleted_at = datetime.datetime.now(datetime.UTC)

    def restore(self) -> None:
        """Restore object from soft delete."""
        self.deleted_at = None

    @property
    def is_deleted(self) -> bool:
        """Check if object is deleted."""
        return self.deleted_at is not None

    def __repr__(self) -> str:
        """String representation of the deleted_at attribute."""
        return f'{self.__class__.__name__}(deleted_at="{self.deleted_at}")'
