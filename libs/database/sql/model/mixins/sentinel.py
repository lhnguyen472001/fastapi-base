from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, orm_insert_sentinel


@declarative_mixin
class SentinelMixin:
    """Mixin to add a sentinel column to a SQLAlchemy model."""

    @classmethod
    @declared_attr
    def _sentinel(cls) -> Mapped[int]:
        """Sentinel column for the model."""
        return orm_insert_sentinel(name="sa_orm_sentinel", type_=int)
