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
from apps.auth.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    verify_password_async,
    verify_totp_with_replay_guard,
)
from apps.settings import app_settings
from apps.user.repositories import UserRepository

if TYPE_CHECKING:
    from apps.core.database.types import SessionType
    from apps.user.models import User


class TwoFactorService:
    """TOTP setup / enable / disable / verify with at-rest encryption + replay guard.

    The service is session-scoped: callers pass an already-loaded user ORM
    object; the service routes field mutations through
    :class:`UserRepository` so persistence stays inside the data layer.
    """

    def __init__(self, *, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def setup(self, session: SessionType, *, user: User) -> Setup2FAResponse:
        """Generate a new TOTP secret for the user (not yet enabled).

        The secret is returned in plaintext so the client can render the QR
        code, but stored encrypted in the database.
        """
        secret = pyotp.random_base32()
        await self.user_repository.update(
            session,
            item_id=user.id,
            data={
                "totp_secret": encrypt_totp_secret(secret),
                # Stay disabled until the user proves they can generate a code via enable.
                "is_2fa_enabled": False,
                # Reset the replay counter — a fresh secret has its own counter line.
                "last_totp_counter": None,
            },
        )

        otpauth_url = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=app_settings.auth.totp_issuer)
        return Setup2FAResponse(secret=secret, otpauth_url=otpauth_url)

    async def enable(self, session: SessionType, *, user: User, totp_code: str) -> None:
        """Confirm setup by validating one TOTP code, then enable 2FA."""
        if not user.totp_secret:
            raise InvalidTwoFactorCodeError(message="2FA setup has not been started for this user.")
        if not await self._consume_code(session, user=user, code=totp_code):
            raise InvalidTwoFactorCodeError()
        await self.user_repository.update(session, item_id=user.id, data={"is_2fa_enabled": True})

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
        if not await self._consume_code(session, user=user, code=totp_code):
            raise InvalidTwoFactorCodeError()
        await self.user_repository.update(
            session,
            item_id=user.id,
            data={"is_2fa_enabled": False, "totp_secret": None, "last_totp_counter": None},
        )

    async def verify(self, session: SessionType, *, user: User, totp_code: str) -> bool:
        """Check a TOTP code, advance the replay counter, return success.

        Returns ``False`` when 2FA is disabled, when the secret is missing,
        when the code is wrong, OR when the code has already been consumed
        (replay) — callers cannot distinguish between these failure modes.
        """
        if not user.is_2fa_enabled or not user.totp_secret:
            return False
        return await self._consume_code(session, user=user, code=totp_code)

    async def _consume_code(self, session: SessionType, *, user: User, code: str) -> bool:
        """Verify ``code`` against the user's encrypted secret and bump the counter.

        Returns ``True`` only when the code is valid AND its 30-second time
        slice has not been consumed before. Successful consumption is
        persisted via :class:`UserRepository`.
        """
        plaintext = decrypt_totp_secret(user.totp_secret) if user.totp_secret else ""
        if not plaintext:
            return False
        matched = verify_totp_with_replay_guard(
            secret=plaintext,
            code=code,
            last_counter=user.last_totp_counter,
        )
        if matched is None:
            return False
        await self.user_repository.update(session, item_id=user.id, data={"last_totp_counter": matched})
        return True
