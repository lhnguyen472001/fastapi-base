"""Auth-domain repositories: refresh tokens and email-verification OTPs."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.models import EmailVerification, OTPPurpose, RefreshToken
from apps.core.database.repository import BaseSQLAlchemyRepository


class RefreshTokenRepository(BaseSQLAlchemyRepository[RefreshToken]):
    """Persistence for hashed refresh tokens."""

    model_type = RefreshToken

    async def find_active_by_hash(self, session: AsyncSession, *, token_hash: str) -> RefreshToken | None:
        """Look up a refresh token by hash, filtering out revoked / expired rows.

        Returns ``None`` if the token does not exist, has been revoked, or
        has passed its expiry. The caller treats all three cases as
        :class:`RefreshTokenRevokedError`.
        """
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > now)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_hash(self, session: AsyncSession, *, token_hash: str) -> RefreshToken | None:
        """Look up a refresh token by hash regardless of revocation / expiry.

        Used by :class:`TokenService.refresh` to disambiguate the "this
        token was never issued" case (likely forgery) from "this token was
        previously rotated" (likely reuse / theft of an old token).
        """
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_all_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
    ) -> None:
        """Revoke every active refresh token for a user (logout-all)."""
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.execute(stmt)


class EmailVerificationRepository(BaseSQLAlchemyRepository[EmailVerification]):
    """Persistence for email-verification OTP codes."""

    model_type = EmailVerification

    async def find_active_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        purpose: OTPPurpose = OTPPurpose.EMAIL_VERIFICATION,
    ) -> EmailVerification | None:
        """Return the latest unused, unexpired OTP for the user, if any."""
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            select(EmailVerification)
            .where(EmailVerification.user_id == user_id)
            .where(EmailVerification.purpose == purpose.value)
            .where(EmailVerification.used_at.is_(None))
            .where(EmailVerification.expires_at > now)
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def invalidate_active_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        purpose: OTPPurpose = OTPPurpose.EMAIL_VERIFICATION,
    ) -> None:
        """Mark all currently active OTPs for the user as used.

        Called before issuing a new code so a stale code can't be replayed
        after the user requested a fresh one.
        """
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            update(EmailVerification)
            .where(EmailVerification.user_id == user_id)
            .where(EmailVerification.purpose == purpose.value)
            .where(EmailVerification.used_at.is_(None))
            .values(used_at=now)
        )
        await session.execute(stmt)

    async def consume_attempt_atomic(
        self,
        session: AsyncSession,
        *,
        otp: EmailVerification,
        max_attempts: int,
    ) -> bool:
        """Atomically bump ``otp.attempts`` iff the row is still consumable.

        Performs a single ``UPDATE … SET attempts = attempts + 1 WHERE id = :id
        AND used_at IS NULL AND expires_at > now AND attempts < :max`` round-
        trip. Concurrent verify requests can no longer both observe
        ``attempts < max`` and proceed — only one increment per attempts-slot
        succeeds.

        Args:
            session: Database session.
            otp: The previously-fetched OTP row to bump. On success the
                in-memory ``attempts`` field is refreshed from the DB.
            max_attempts: Inclusive upper bound from settings.

        Returns:
            ``True`` if the increment was applied (caller may now check the
            code). ``False`` if the row was already exhausted, used, or
            expired between the find and this call — caller must treat as
            a generic OTP failure.
        """
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            update(EmailVerification)
            .where(EmailVerification.id == otp.id)
            .where(EmailVerification.used_at.is_(None))
            .where(EmailVerification.expires_at > now)
            .where(EmailVerification.attempts < max_attempts)
            .values(attempts=EmailVerification.attempts + 1)
        )
        result = await session.execute(stmt)
        if result.rowcount == 0:
            return False
        await session.refresh(otp, attribute_names=["attempts"])
        return True
