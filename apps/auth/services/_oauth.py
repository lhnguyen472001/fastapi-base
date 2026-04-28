"""Google OAuth login / link service."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from apps.auth.enums import TokenType
from apps.auth.exceptions import (
    OAuthEmailNotVerifiedError,
    OAuthStateExpiredError,
    OAuthStateInvalidError,
)
from apps.auth.oauth import GoogleOAuthClient
from apps.auth.security import (
    TokenError,
    TokenExpiredError as CoreTokenExpiredError,
    compute_pkce_challenge,
    decode_token,
    generate_oauth_state_token,
    generate_pkce_verifier,
)
from apps.core.database.types import SessionType
from apps.user.models import User
from apps.user.services import UserService

OAUTH_STATE_COOKIE_NAME = "oauth_state"


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthFlowStart:
    """Bundle returned to the route handler when starting an OAuth flow.

    The route surfaces ``authorize_url`` + ``state_token`` to the client and
    sets ``state_id`` as an HttpOnly cookie that is replayed on callback so
    the state cannot be lifted from one browser to another.
    """

    authorize_url: str
    state_token: str
    state_id: str


class OAuthService:
    """Google OAuth2: authorize URL, signed state + cookie, PKCE, code exchange → user."""

    def __init__(
        self,
        *,
        user_service: UserService,
        google_oauth_client: GoogleOAuthClient,
    ) -> None:
        self.user_service = user_service
        self.google_oauth_client = google_oauth_client

    def start_authorize_flow(self) -> OAuthFlowStart:
        """Mint state + PKCE pair and build the Google consent URL.

        The ``state_token`` carries a ``sid`` claim equal to the returned
        ``state_id``; the route stores ``state_id`` in an HttpOnly cookie.
        On callback, the cookie value must match ``sid`` or we reject the
        request — this binds the state to the originating browser session
        and blocks session fixation.

        A fresh PKCE ``code_verifier`` is also embedded in the state token
        as the ``cv`` claim and its S256 ``code_challenge`` is sent to
        Google so the authorization code can only be redeemed by us.
        """
        state_id = uuid.uuid4().hex
        code_verifier = generate_pkce_verifier()
        code_challenge = compute_pkce_challenge(code_verifier)
        state_token = generate_oauth_state_token(state_id=state_id, code_verifier=code_verifier)
        authorize_url = self.google_oauth_client.build_authorize_url(
            state=state_token,
            code_challenge=code_challenge,
        )
        return OAuthFlowStart(
            authorize_url=authorize_url,
            state_token=state_token,
            state_id=state_id,
        )

    def verify_state_token(self, state: str, *, cookie_state_id: str | None) -> dict[str, Any]:
        """Validate the state JWT and confirm it is bound to this browser.

        Returns the decoded claim dict on success so callers (specifically
        :meth:`exchange_code_and_link`) can pull the PKCE ``cv`` claim
        without re-decoding.
        """
        try:
            payload = decode_token(state, expected_type=TokenType.OAUTH_STATE)
        except CoreTokenExpiredError as e:
            raise OAuthStateExpiredError() from e
        except TokenError as e:
            raise OAuthStateInvalidError() from e

        if payload.get("sub") != "oauth_state":
            raise OAuthStateInvalidError()

        sid = payload.get("sid")
        if not sid or not cookie_state_id or not secrets.compare_digest(sid, cookie_state_id):
            raise OAuthStateInvalidError()

        return payload

    async def exchange_code_and_link(
        self,
        session: SessionType,
        *,
        code: str,
        state: str,
        cookie_state_id: str | None,
    ) -> User:
        """Verify state + cookie binding, redeem the code with PKCE, link the user.

        Returns the resolved :class:`User` ORM object. Callers decide whether
        to issue a token pair or a 2FA challenge based on
        ``user.is_2fa_enabled``.

        OAuth users skip email-OTP verification because Google has already
        verified their email.
        """
        payload = self.verify_state_token(state, cookie_state_id=cookie_state_id)
        code_verifier = payload.get("cv")
        if not code_verifier:
            raise OAuthStateInvalidError()

        userinfo = await self.google_oauth_client.exchange_code(code=code, code_verifier=code_verifier)
        if not userinfo.email_verified:
            raise OAuthEmailNotVerifiedError()

        username_hint = userinfo.email.split("@", 1)[0]
        return await self.user_service.get_or_create_oauth_user(
            session,
            email=userinfo.email,
            username_hint=username_hint,
            google_sub=userinfo.sub,
        )
