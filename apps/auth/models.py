"""Auth-related ORM models: refresh tokens and email verification (OTP)."""

import datetime
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.types import DateTimeUTC

if TYPE_CHECKING:
    from apps.user.models import User


class RefreshToken(UUIDAuditBase):
    """Long-lived refresh token persisted as a SHA-256 hash.

    The plaintext token is returned to the client once at issuance and never
    stored — only ``token_hash`` is. Lookups happen by hash. Tokens are
    rotated on every successful refresh: the old row gets ``revoked_at`` set
    and a new row is inserted with ``replaced_by_id`` pointing to its successor.
    """

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    # Audit metadata so we can present an "active sessions" view in the future.
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),)


class OTPPurpose(enum.StrEnum):
    """Reason an OTP was issued."""

    EMAIL_VERIFICATION = "email_verification"


class EmailVerification(UUIDAuditBase):
    """One-time password issued to confirm a user's email address.

    The plaintext code is sent to the user's email and discarded; only
    ``code_hash`` is persisted. Codes expire after a configurable window
    (default 10 minutes) and are limited to ``otp_max_attempts`` wrong
    submissions before being marked used.
    """

    __table_args__ = (
        Index(
            "ix_email_verifications_user_id_purpose_used_at",
            "user_id",
            "purpose",
            "used_at",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="email_verifications")
