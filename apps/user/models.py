from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.database.sql.model.base import UUIDAuditBase
from libs.database.sql.model.mixins import HasSoftDeletedMixin


class User(UUIDAuditBase, HasSoftDeletedMixin):
    """User model."""

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(  # noqa: F821
        "RefreshToken",
        back_populates="user",
        lazy="selectin",
    )
