from sqlalchemy import Sequence
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column
from sqlalchemy.types import BigInteger


@declarative_mixin
class BigIntPrimaryKeyMixin:
    """BigInt Primary Key Field Mixin."""

    @classmethod
    @declared_attr
    def id(cls) -> Mapped[int]:
        """BigInt Primary key column."""
        return mapped_column(
            BigInteger(),
            Sequence(f"{cls.__tablename__}_id_seq", optional=False),
            primary_key=True,
        )
