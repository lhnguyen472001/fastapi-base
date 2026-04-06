import uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey

from libs.database.sql.model.base import UUIDAuditBase


class RefreshToken(UUIDAuditBase):
    """Refresh token model."""

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
