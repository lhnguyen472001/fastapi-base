"""Casbin rule table — adapter-managed policy storage."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database.model.base import BigIntBase


class CasbinRule(BigIntBase):
    """Casbin rule table.

    ``BigIntBase`` (no audit columns) is used because the
    ``casbin-async-sqlalchemy-adapter`` writes rows directly without
    populating ``created_at`` / ``updated_at``.
    """

    __tablename__ = "casbin_rule"  # type: ignore[assignment]

    ptype: Mapped[str] = mapped_column(String(255), nullable=False)
    v0: Mapped[str | None] = mapped_column(String(255), nullable=True)
    v1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    v2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    v3: Mapped[str | None] = mapped_column(String(255), nullable=True)
    v4: Mapped[str | None] = mapped_column(String(255), nullable=True)
    v5: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __str__(self) -> str:
        arr = [self.ptype]
        for v in (self.v0, self.v1, self.v2, self.v3, self.v4, self.v5):
            if v is None:
                break
            arr.append(v)
        return ", ".join(arr)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__str__()})"
