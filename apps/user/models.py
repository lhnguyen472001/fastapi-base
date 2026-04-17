"""User model."""

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.model import HasSoftDeletedMixin
from apps.core.database.types import DateTimeUTC

if TYPE_CHECKING:
    from apps.auth.models import EmailVerification, RefreshToken


class User(UUIDAuditBase, HasSoftDeletedMixin):
    """User model.

    New users start with ``is_active=False``. Activation happens when the user
    confirms their email via OTP (see ``apps.auth.services.AuthService.verify_email``).
    OAuth-registered users (e.g. Google) skip the OTP step and are created
    with ``is_active=True`` because the upstream provider has already verified
    the email.
    """

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Email verification — set when OTP confirmation succeeds.
    email_verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)

    # Google OAuth linkage — Google's stable user ID (`sub` claim). Unique
    # when not null so two users cannot share the same Google account.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)

    # TOTP-based 2FA. ``totp_secret`` is the base32 secret consumed by
    # authenticator apps. ``is_2fa_enabled`` is a separate flag because we
    # store the secret during setup but only enable it after the user proves
    # they can generate a valid code.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_2fa_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        lazy="raise",
    )
    email_verifications: Mapped[list["EmailVerification"]] = relationship(
        "EmailVerification",
        back_populates="user",
        cascade="all, delete-orphan",
    )
