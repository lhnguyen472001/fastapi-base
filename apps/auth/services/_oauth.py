"""Google OAuth login / link service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.auth.exceptions import (
    OAuthEmailNotVerifiedError,
    OAuthStateExpiredError,
    OAuthStateInvalidError,
)
from apps.core.security import (
    CHALLENGE_TOKEN_TYPE,
    TokenError,
    TokenExpiredError as CoreTokenExpiredError,
    create_challenge_token,
    decode_token,
)

if TYPE_CHECKING:
    from apps.auth.oauth import GoogleOAuthClient
    from apps.core.database.types import SessionType
    from apps.user.models import User
    from apps.user.services import UserService


class OAuthService:
    """Google OAuth2: authorize URL, signed state, code exchange → user."""

    def __init__(
        self,
        *,
        user_service: UserService,
        google_oauth_client: GoogleOAuthClient,
    ) -> None:
        self.user_service = user_service
        self.google_oauth_client = google_oauth_client

    def authorize_url(self, *, state: str) -> str:
        """Build the Google consent screen URL.

        ``state`` is a signed challenge JWT minted by
        :meth:`issue_state_token`; the callback verifies it before exchanging
        the code so an attacker can't trick a logged-in user into linking
        their account to the attacker's Google identity.
        """
        return self.google_oauth_client.build_authorize_url(state=state)

    def issue_state_token(self) -> str:
        """Mint a short-lived signed state token (reuses the challenge JWT type).

        Subject is the constant ``"oauth_state"`` — we don't know who's
        logging in yet.
        """
        return create_challenge_token(subject="oauth_state")

    def verify_state_token(self, state: str) -> None:
        """Validate a state token issued by :meth:`issue_state_token`."""
        try:
            payload = decode_token(state, expected_type=CHALLENGE_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise OAuthStateExpiredError() from e
        except TokenError as e:
            raise OAuthStateInvalidError() from e
        if payload.get("sub") != "oauth_state":
            raise OAuthStateInvalidError()

    async def exchange_code_and_link(
        self,
        session: SessionType,
        *,
        code: str,
        state: str,
    ) -> User:
        """Verify state, exchange the auth code, and link or create the user.

        Returns the resolved :class:`User` ORM object. Callers decide whether
        to issue a token pair or a 2FA challenge based on
        ``user.is_2fa_enabled``.

        OAuth users skip email-OTP verification because Google has already
        verified their email.
        """
        self.verify_state_token(state)

        userinfo = await self.google_oauth_client.exchange_code(code=code)
        if not userinfo.email_verified:
            raise OAuthEmailNotVerifiedError()

        username_hint = userinfo.email.split("@", 1)[0]
        return await self.user_service.get_or_create_oauth_user(
            session,
            email=userinfo.email,
            username_hint=username_hint,
            google_sub=userinfo.sub,
        )
