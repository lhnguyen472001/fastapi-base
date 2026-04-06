import uuid

from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column

from .sentinel import SentinelMixin


@declarative_mixin
class UUIDPrimaryKeyMixin(SentinelMixin):
    """Mixin for adding a UUID primary key column."""

    @classmethod
    @declared_attr
    def id(cls) -> Mapped[uuid.UUID]:
        """UUID primary column."""
        return mapped_column(
            PGUUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        )

    def __repr__(self) -> str:
        """String representation of the UUID primary key."""
        return f'{self.__class__.__name__}(id="{self.id}")'
