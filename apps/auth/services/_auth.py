"""AuthService facade — orchestrates the auth sub-services."""

from __future__ import annotations

import uuid

from apps.auth.enums import TokenType
from apps.auth.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidTwoFactorCodeError,
    TokenExpiredError,
)
from apps.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    Setup2FAResponse,
    TokenPair,
    TwoFactorChallenge,
)
from apps.auth.services._email_verification import EmailVerificationService
from apps.auth.services._oauth import OAuthService
from apps.auth.services._tokens import TokenService
from apps.auth.services._two_factor import TwoFactorService
from apps.core.database.types import SessionType
from apps.core.security import (
    TokenError,
    TokenExpiredError as CoreTokenExpiredError,
    create_challenge_token,
    decode_token,
    verify_password_async,
)
from apps.user.models import User
from apps.user.services import UserService


class AuthService:
    """Facade composing the auth sub-services.

    Exposes the same public method set as before the 3.2 split so routes and
    tests don't need to change. Each method delegates to the focused sub-
    service responsible for the concern.
    """

    def __init__(
        self,
        *,
        user_service: UserService,
        token_service: TokenService,
        email_verification_service: EmailVerificationService,
        two_factor_service: TwoFactorService,
        oauth_service: OAuthService,
    ) -> None:
        self.user_service = user_service
        self.token_service = token_service
        self.email_verification_service = email_verification_service
        self.two_factor_service = two_factor_service
        self.oauth_service = oauth_service

    # ----------------------------- registration ----------------------------

    async def register(self, session: SessionType, *, data: RegisterRequest) -> User:
        """Register a new user (inactive) and email them an OTP code."""
        user = await self.user_service.create(session, data=data)
        await self.email_verification_service.issue_and_send(session, user=user)
        return user

    async def verify_email(self, session: SessionType, *, email: str, code: str) -> User:
        return await self.email_verification_service.verify(session, email=email, code=code)

    async def resend_verification(self, session: SessionType, *, email: str) -> None:
        await self.email_verification_service.resend(session, email=email)

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

        pair, _ = await self.token_service.issue_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)
        return pair

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
            payload = decode_token(challenge_token, expected_type=TokenType.CHALLENGE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        user = await self.user_service.get_by_id(session, user_id=user_id)
        if not self.two_factor_service.verify(user, totp_code):
            raise InvalidTwoFactorCodeError()

        pair, _ = await self.token_service.issue_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)
        return pair

    async def _authenticate(self, session: SessionType, *, email: str, password: str) -> User:
        """Verify password and ensure the user is active."""
        user = await self.user_service.get_by_email_or_username(session, email=email)
        if user is None:
            raise InvalidCredentialsError()
        if not await verify_password_async(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise EmailNotVerifiedError()
        return user

    # ------------------------- refresh / logout / me -----------------------

    async def refresh(
        self,
        session: SessionType,
        *,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        return await self.token_service.refresh(
            session,
            raw_refresh_token=raw_refresh_token,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def logout(self, session: SessionType, *, raw_refresh_token: str) -> None:
        await self.token_service.logout(session, raw_refresh_token=raw_refresh_token)

    async def get_user_from_access_token(self, session: SessionType, *, token: str) -> User:
        return await self.token_service.user_from_access_token(session, token=token)

    # ------------------------------- 2FA -----------------------------------

    async def setup_2fa(self, session: SessionType, *, user: User) -> Setup2FAResponse:
        return await self.two_factor_service.setup(session, user=user)

    async def enable_2fa(self, session: SessionType, *, user: User, totp_code: str) -> None:
        await self.two_factor_service.enable(session, user=user, totp_code=totp_code)

    async def disable_2fa(self, session: SessionType, *, user: User, password: str, totp_code: str) -> None:
        await self.two_factor_service.disable(session, user=user, password=password, totp_code=totp_code)

    # ----------------------------- Google OAuth ----------------------------

    def google_authorize_url(self, *, state: str) -> str:
        return self.oauth_service.authorize_url(state=state)

    def issue_oauth_state_token(self) -> str:
        return self.oauth_service.issue_state_token()

    def verify_oauth_state_token(self, state: str) -> None:
        self.oauth_service.verify_state_token(state)

    async def google_callback(
        self,
        session: SessionType,
        *,
        code: str,
        state: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair | TwoFactorChallenge:
        """Exchange a Google authorization code and either log in or register."""
        user = await self.oauth_service.exchange_code_and_link(session, code=code, state=state)

        if user.is_2fa_enabled:
            challenge_token = create_challenge_token(subject=str(user.id))
            return TwoFactorChallenge(challenge_token=challenge_token)

        pair, _ = await self.token_service.issue_pair(session, user=user, user_agent=user_agent, ip_address=ip_address)
        return pair
