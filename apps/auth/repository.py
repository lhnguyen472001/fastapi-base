"""Auth-domain repositories: refresh tokens and email-verification OTPs."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.models import EmailVerification, OtpPurpose, RefreshToken
from apps.core.database.sql.repository import BaseSQLAlchemyRepository


class RefreshTokenRepository(BaseSQLAlchemyRepository[RefreshToken]):
    """Persistence for hashed refresh tokens."""

    model_type = RefreshToken

    async def find_active_by_hash(
        self, session: AsyncSession, *, token_hash: str
    ) -> RefreshToken | None:
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

    async def revoke_all_for_user(
        self, session: AsyncSession, *, user_id: uuid.UUID
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
        purpose: OtpPurpose = OtpPurpose.EMAIL_VERIFICATION,
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
        purpose: OtpPurpose = OtpPurpose.EMAIL_VERIFICATION,
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
