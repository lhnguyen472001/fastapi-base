"""Auth service"""

import datetime
import uuid

import pyotp
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from apps.auth.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidOtpError,
    InvalidTokenError,
    InvalidTwoFactorCodeError,
    RefreshTokenRevokedError,
    TokenExpiredError,
    TwoFactorNotEnabledError,
)
from apps.auth.models import EmailVerification, OtpPurpose, RefreshToken
from apps.auth.oauth import GoogleOAuthClient
from apps.auth.repository import EmailVerificationRepository, RefreshTokenRepository
from apps.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    Setup2FAResponse,
    TokenPair,
    TwoFactorChallenge,
)
from apps.core.email import EmailMessage, EmailRenderer, EmailSenderProtocol
from apps.core.security import (
    ACCESS_TOKEN_TYPE,
    CHALLENGE_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_challenge_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp_code,
    hash_token,
    verify_password,
)
from apps.core.security import (
    TokenExpiredError as CoreTokenExpiredError,
)
from apps.settings import app_settings
from apps.user.exceptions import UserAlreadyExistsError, UserNotFoundError
from apps.user.models import User
from apps.user.services import UserService

SessionType = AsyncSession | async_scoped_session[AsyncSession]


class AuthService:
    """Stateful auth service composing User + RefreshToken + EmailVerification."""

    def __init__(
        self,
        *,
        user_service: UserService,
        refresh_token_repository: RefreshTokenRepository,
        email_verification_repository: EmailVerificationRepository,
        email_sender: EmailSenderProtocol,
        email_renderer: EmailRenderer,
        google_oauth_client: GoogleOAuthClient,
    ) -> None:
        self.user_service = user_service
        self.refresh_token_repository = refresh_token_repository
        self.email_verification_repository = email_verification_repository
        self.email_sender = email_sender
        self.email_renderer = email_renderer
        self.google_oauth_client = google_oauth_client

    # ----------------------------- registration ----------------------------

    async def register(
        self,
        session: SessionType,
        *,
        data: RegisterRequest,
    ) -> User:
        """Register a new user (inactive) and email them an OTP code."""

        try:
            user = await self.user_service.create(session, data=data)
        except UserAlreadyExistsError:
            raise

        await self._issue_and_send_otp(session, user=user)
        return user

    async def verify_email(self, session: SessionType, *, email: str, code: str) -> User:
        """Confirm an email-verification OTP and activate the user."""
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None:
            # Same generic error as wrong code to avoid email enumeration.
            raise InvalidOtpError()

        otp = await self.email_verification_repository.find_active_for_user(session, user_id=user.id)
        if otp is None:
            raise InvalidOtpError()

        if otp.attempts >= app_settings.auth.otp_max_attempts:
            otp.used_at = datetime.datetime.now(datetime.UTC)
            await session.flush()
            raise InvalidOtpError()

        if otp.code_hash != hash_otp_code(code):
            otp.attempts += 1
            await session.flush()
            raise InvalidOtpError()

        # Success — mark code used + activate user.
        now = datetime.datetime.now(datetime.UTC)
        otp.used_at = now
        user.is_active = True
        user.email_verified_at = now
        await session.flush()
        return user

    async def resend_verification(self, session: SessionType, *, email: str) -> None:
        """Issue a fresh OTP for an unverified user.

        Always returns successfully — never reveals whether the email exists
        or whether the user is already verified.
        """
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None or user.email_verified_at is not None:
            return
        await self.email_verification_repository.invalidate_active_for_user(session, user_id=user.id)
        await self._issue_and_send_otp(session, user=user)

    async def _issue_and_send_otp(self, session: SessionType, *, user: User) -> None:
        """Generate, persist, and email a fresh OTP code.

        SMTP delivery failures are logged and swallowed so a downed mail
        server cannot block registration. Users in that case can request a
        new code via :meth:`resend_verification` once mail recovers.
        """
        code = generate_otp_code()
        ttl_minutes = app_settings.auth.otp_expire_minutes
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=ttl_minutes)

        otp = EmailVerification(
            user_id=user.id,
            code_hash=hash_otp_code(code),
            purpose=OtpPurpose.EMAIL_VERIFICATION.value,
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
        except Exception as exc:  # noqa: BLE001 - log + swallow on purpose
            # Don't roll back the registration; the OTP row is still in the
            # session and the user can call /auth/verify-email/resend later.
            logger.error(
                "AuthService - _issue_and_send_otp - delivery failed for user_id={uid}: {err}",
                uid=user.id,
                err=exc,
            )
            return

        logger.info("AuthService - _issue_and_send_otp - user_id={uid}", uid=user.id)

    # -------------------------------- login --------------------------------

    async def login(
        self,
        session: SessionType,
        *,
        data: LoginRequest,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair | TwoFactorChallenge:
        """Step 1 of password login.

        Returns a full token pair if the user does NOT have 2FA enabled,
        otherwise returns a 2FA challenge that the client must answer via
        :meth:`login_2fa`.
        """
        user = await self._authenticate(session, email=data.email, password=data.password)

        if user.is_2fa_enabled:
            challenge_token = create_challenge_token(subject=str(user.id))
            return TwoFactorChallenge(challenge_token=challenge_token)

        return await self._issue_token_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)

    async def login_2fa(
        self,
        session: SessionType,
        *,
        challenge_token: str,
        totp_code: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Step 2 of password login — answer the 2FA challenge."""
        try:
            payload = decode_token(challenge_token, expected_type=CHALLENGE_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        user = await self.user_service.get_by_id(session, user_id=user_id)
        if not user.is_2fa_enabled or not user.totp_secret:
            raise InvalidTwoFactorCodeError()

        if not pyotp.TOTP(user.totp_secret).verify(totp_code):
            raise InvalidTwoFactorCodeError()

        return await self._issue_token_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)

    async def _authenticate(self, session: SessionType, *, email: str, password: str) -> User:
        """Verify password and ensure the user is active."""
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None:
            raise InvalidCredentialsError()
        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise EmailNotVerifiedError()
        return user

    # ------------------------------- refresh -------------------------------

    async def refresh(
        self,
        session: SessionType,
        *,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Rotate a refresh token: revoke the old, issue a new pair."""
        try:
            payload = decode_token(raw_refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is None:
            raise RefreshTokenRevokedError()

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        user = await self.user_service.get_by_id(session, user_id=user_id)

        new_pair = await self._issue_token_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)

        # Mark old token revoked + record successor for theft-detection auditing.
        existing.revoked_at = datetime.datetime.now(datetime.UTC)
        new_token_row = await self.refresh_token_repository.find_active_by_hash(
            session, token_hash=hash_token(new_pair.refresh_token)
        )
        if new_token_row is not None:
            existing.replaced_by_id = new_token_row.id
        await session.flush()

        return new_pair

    # -------------------------------- logout -------------------------------

    async def logout(self, session: SessionType, *, raw_refresh_token: str) -> None:
        """Revoke a refresh token. Idempotent — never raises on missing token."""
        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is not None:
            existing.revoked_at = datetime.datetime.now(datetime.UTC)
            await session.flush()

    # --------------------------------- me ----------------------------------

    async def get_user_from_access_token(self, session: SessionType, *, token: str) -> User:
        """Decode an access token and return the corresponding active user."""
        try:
            payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        try:
            user = await self.user_service.get_by_id(session, user_id=user_id)
        except UserNotFoundError as e:
            raise InvalidTokenError() from e

        if not user.is_active:
            raise EmailNotVerifiedError()
        return user

    # ------------------------------- 2FA setup -----------------------------

    async def setup_2fa(self, session: SessionType, *, user: User) -> Setup2FAResponse:
        """Generate a new TOTP secret for the user (not yet enabled)."""
        secret = pyotp.random_base32()
        user.totp_secret = secret
        # Stay disabled until the user proves they can generate a code via enable_2fa.
        user.is_2fa_enabled = False
        await session.flush()

        otpauth_url = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=app_settings.auth.totp_issuer)
        return Setup2FAResponse(secret=secret, otpauth_url=otpauth_url)

    async def enable_2fa(self, session: SessionType, *, user: User, totp_code: str) -> None:
        """Confirm setup by validating one TOTP code, then enable 2FA."""
        if not user.totp_secret:
            raise InvalidTwoFactorCodeError(message="2FA setup has not been started for this user.")
        if not pyotp.TOTP(user.totp_secret).verify(totp_code):
            raise InvalidTwoFactorCodeError()
        user.is_2fa_enabled = True
        await session.flush()

    async def disable_2fa(self, session: SessionType, *, user: User, password: str, totp_code: str) -> None:
        """Disable 2FA. Requires both the current password AND a valid TOTP."""
        if not user.is_2fa_enabled or not user.totp_secret:
            raise TwoFactorNotEnabledError()
        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not pyotp.TOTP(user.totp_secret).verify(totp_code):
            raise InvalidTwoFactorCodeError()
        user.is_2fa_enabled = False
        user.totp_secret = None
        await session.flush()

    # ------------------------- token pair issuance -------------------------

    async def _issue_token_pair(
        self,
        session: SessionType,
        *,
        user: User,
        user_agent: str | None,
        ip_address: str | None,
    ) -> TokenPair:
        """Mint an access token + persist a hashed refresh token row."""
        access_token = create_access_token(subject=str(user.id))
        refresh_raw, refresh_expires_at = create_refresh_token(subject=str(user.id))

        refresh_row = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        session.add(refresh_row)
        await session.flush()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=app_settings.auth.access_token_expire_minutes * 60,
        )

    # ----------------------------- Google OAuth ----------------------------

    def google_authorize_url(self, *, state: str) -> str:
        """Build the Google consent screen URL.

        ``state`` is a signed challenge JWT we mint server-side; the callback
        verifies it before exchanging the code so an attacker can't trick a
        logged-in user into linking their account to the attacker's Google
        identity.
        """
        return self.google_oauth_client.build_authorize_url(state=state)

    def issue_oauth_state_token(self) -> str:
        """Mint a short-lived signed state token (reuses the challenge JWT type)."""
        # Subject is empty — we don't know who's logging in yet.
        return create_challenge_token(subject="oauth_state")

    def verify_oauth_state_token(self, state: str) -> None:
        """Validate a state token issued by :meth:`issue_oauth_state_token`."""
        try:
            payload = decode_token(state, expected_type=CHALLENGE_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise InvalidTokenError(message="OAuth state expired.") from e
        except TokenError as e:
            raise InvalidTokenError(message="OAuth state invalid.") from e
        if payload.get("sub") != "oauth_state":
            raise InvalidTokenError(message="OAuth state subject mismatch.")

    async def google_callback(
        self,
        session: SessionType,
        *,
        code: str,
        state: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair | TwoFactorChallenge:
        """Exchange a Google authorization code and either log in or register.

        OAuth users skip email-OTP verification because Google has already
        verified their email. They are still subject to the local 2FA flow
        if they previously enabled it.
        """
        self.verify_oauth_state_token(state)

        userinfo = await self.google_oauth_client.exchange_code(code=code)
        if not userinfo.email_verified:
            raise InvalidTokenError(message="Google account email is not verified.")

        username_hint = userinfo.email.split("@", 1)[0]
        user = await self.user_service.get_or_create_oauth_user(
            session,
            email=userinfo.email,
            username_hint=username_hint,
            google_sub=userinfo.sub,
        )

        if user.is_2fa_enabled:
            challenge_token = create_challenge_token(subject=str(user.id))
            return TwoFactorChallenge(challenge_token=challenge_token)

        return await self._issue_token_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)
