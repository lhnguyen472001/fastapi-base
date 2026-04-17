"""TOTP (time-based one-time password) 2FA service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyotp

from apps.auth.exceptions import (
    InvalidCredentialsError,
    InvalidTwoFactorCodeError,
    TwoFactorNotEnabledError,
)
from apps.auth.schemas import Setup2FAResponse
from apps.core.security import verify_password_async
from apps.settings import app_settings

if TYPE_CHECKING:
    from apps.core.database.types import SessionType
    from apps.user.models import User


class TwoFactorService:
    """TOTP setup / enable / disable / verify.

    The service is session-scoped: callers pass an already-loaded user ORM
    object and the service mutates its ``totp_secret`` / ``is_2fa_enabled``
    fields, relying on SQLAlchemy's session to flush.
    """

    async def setup(self, session: SessionType, *, user: User) -> Setup2FAResponse:
        """Generate a new TOTP secret for the user (not yet enabled)."""
        secret = pyotp.random_base32()
        user.totp_secret = secret
        # Stay disabled until the user proves they can generate a code via enable.
        user.is_2fa_enabled = False
        await session.flush()

        otpauth_url = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=app_settings.auth.totp_issuer)
        return Setup2FAResponse(secret=secret, otpauth_url=otpauth_url)

    async def enable(self, session: SessionType, *, user: User, totp_code: str) -> None:
        """Confirm setup by validating one TOTP code, then enable 2FA."""
        if not user.totp_secret:
            raise InvalidTwoFactorCodeError(message="2FA setup has not been started for this user.")
        if not pyotp.TOTP(user.totp_secret).verify(totp_code):
            raise InvalidTwoFactorCodeError()
        user.is_2fa_enabled = True
        await session.flush()

    async def disable(
        self,
        session: SessionType,
        *,
        user: User,
        password: str,
        totp_code: str,
    ) -> None:
        """Disable 2FA. Requires both the current password AND a valid TOTP."""
        if not user.is_2fa_enabled or not user.totp_secret:
            raise TwoFactorNotEnabledError()
        if not await verify_password_async(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not pyotp.TOTP(user.totp_secret).verify(totp_code):
            raise InvalidTwoFactorCodeError()
        user.is_2fa_enabled = False
        user.totp_secret = None
        await session.flush()

    def verify(self, user: User, totp_code: str) -> bool:
        """Check a TOTP code against the user's secret.

        Returns ``False`` if 2FA is not enabled or the secret is missing,
        so callers can treat "no 2FA configured" and "wrong code" uniformly.
        """
        if not user.is_2fa_enabled or not user.totp_secret:
            return False
        return bool(pyotp.TOTP(user.totp_secret).verify(totp_code))
