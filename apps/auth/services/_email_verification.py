"""Email-verification OTP issuance and validation."""

import datetime

from loguru import logger

from apps.auth.exceptions import InvalidOtpError
from apps.auth.models import EmailVerification, OTPPurpose
from apps.auth.repository import EmailVerificationRepository
from apps.auth.security import generate_otp_code, hash_otp_code
from apps.core.database.types import SessionType
from apps.core.email import EmailMessage, EmailRenderer, EmailSenderProtocol
from apps.settings import app_settings
from apps.user.models import User
from apps.user.services import UserService


class EmailVerificationService:
    """Issue, resend, and validate email-verification OTPs.

    The OTP is a short numeric code emailed to the user at registration. The
    user submits it back via ``verify`` to flip ``is_active=True`` on their
    account. Failures return a generic error code so the endpoint can't be
    abused for email enumeration.
    """

    def __init__(
        self,
        *,
        user_service: UserService,
        email_verification_repository: EmailVerificationRepository,
        email_sender: EmailSenderProtocol,
        email_renderer: EmailRenderer,
    ) -> None:
        self.user_service = user_service
        self.email_verification_repository = email_verification_repository
        self.email_sender = email_sender
        self.email_renderer = email_renderer

    async def verify(self, session: SessionType, *, email: str, code: str) -> User:
        """Confirm an email-verification OTP and activate the user.

        Concurrency: the attempts counter is bumped via a single atomic
        UPDATE so two simultaneous verify requests cannot both observe
        ``attempts < max`` and bypass the rate limit.
        """
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None:
            # Same generic error as wrong code to avoid email enumeration.
            raise InvalidOtpError()

        otp = await self.email_verification_repository.find_active_for_user(session, user_id=user.id)
        if otp is None:
            raise InvalidOtpError()

        max_attempts = app_settings.auth.otp_max_attempts
        consumed = await self.email_verification_repository.consume_attempt_atomic(
            session, otp=otp, max_attempts=max_attempts
        )
        if not consumed:
            # Row was exhausted, used, or expired — treat as a generic
            # OTP failure so we leak nothing about which case it was.
            raise InvalidOtpError()

        if otp.code_hash != hash_otp_code(code):
            # The attempt was already counted by the atomic UPDATE above.
            # If this attempt just hit the cap, mark the row used so a
            # later guess can't squeeze through on a stale find.
            if otp.attempts >= max_attempts:
                otp.used_at = datetime.datetime.now(datetime.UTC)
                await session.flush()
            raise InvalidOtpError()

        # Success — mark code used + activate user.
        now = datetime.datetime.now(datetime.UTC)
        otp.used_at = now
        user.is_active = True
        user.email_verified_at = now
        await session.flush()
        return user

    async def resend(self, session: SessionType, *, email: str) -> None:
        """Issue a fresh OTP for an unverified user.

        Always returns successfully — never reveals whether the email exists
        or whether the user is already verified.
        """
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None or user.email_verified_at is not None:
            return
        await self.email_verification_repository.invalidate_active_for_user(session, user_id=user.id)
        await self.issue_and_send(session, user=user)

    async def issue_and_send(self, session: SessionType, *, user: User) -> None:
        """Generate, persist, and email a fresh OTP code.

        SMTP delivery failures are logged and swallowed so a downed mail
        server cannot block registration. Users in that case can request a
        new code via :meth:`resend` once mail recovers.
        """
        code = generate_otp_code()
        ttl_minutes = app_settings.auth.otp_expire_minutes
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=ttl_minutes)

        otp = EmailVerification(
            user_id=user.id,
            code_hash=hash_otp_code(code),
            purpose=OTPPurpose.EMAIL_VERIFICATION.value,
            expires_at=expires_at,
        )
        session.add(otp)
        await session.flush()

        subject = f"{app_settings.app_name} — verify your email"
        plain_body, html_body = self.email_renderer.render(
            "verification_email",
            subject=subject,
            app_name=app_settings.app_name,
            username=user.username,
            code=code,
            ttl_minutes=ttl_minutes,
        )

        try:
            await self.email_sender.send(
                EmailMessage(
                    to=user.email,
                    subject=subject,
                    body=plain_body,
                    html_body=html_body,
                )
            )
        except Exception as exc:
            # Don't roll back the registration; the OTP row is still in the
            # session and the user can call /auth/verify-email/resend later.
            logger.error(
                "EmailVerificationService - issue_and_send - delivery failed for user_id={uid}: {err}",
                uid=user.id,
                err=exc,
            )
            return

        logger.info("EmailVerificationService - issue_and_send - user_id={uid}", uid=user.id)
