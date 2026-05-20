"""Thin async Google OAuth2 client built on httpx.

Implements :class:`apps.auth.protocols.OAuthProviderProtocol`. The
provider-neutral userinfo dataclass lives in :mod:`apps.auth.protocols`
as :class:`OAuthUserInfo`; ``GoogleUserInfo`` is kept here as an alias
so existing imports (``from apps.auth.oauth import GoogleUserInfo``)
keep working.
"""

from urllib.parse import urlencode

import httpx
from loguru import logger

from apps.auth.constants import (
    GOOGLE_AUTHORIZE_ENDPOINT,
    GOOGLE_OAUTH_HTTP_TIMEOUT_SECONDS,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_USERINFO_ENDPOINT,
)
from apps.auth.exceptions import OAuthProviderError
from apps.auth.protocols import OAuthUserInfo

# Back-compat alias: legacy callers import ``GoogleUserInfo`` from this
# module. The canonical type now lives on the protocol so non-Google
# providers can return the same shape.
GoogleUserInfo = OAuthUserInfo


class GoogleOAuthClient:
    """Async Google OAuth2 client.

    Holds a long-lived :class:`httpx.AsyncClient` so consecutive OAuth
    callbacks reuse TCP+TLS connections instead of paying the handshake
    every request. The client is created lazily on first use and torn
    down explicitly via :meth:`aclose` from the FastAPI lifespan.
    """

    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared async client, creating it if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=GOOGLE_OAUTH_HTTP_TIMEOUT_SECONDS)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx client; safe to call when never used."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Build the Google consent screen URL.

        Args:
            state: Opaque random string the caller will validate on callback
                to mitigate CSRF.
            code_challenge: PKCE S256 challenge derived from a random
                ``code_verifier`` held server-side; Google requires the
                matching verifier on the token endpoint to redeem the code.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_OAUTH_SCOPES,
            # No ``access_type=offline`` / ``prompt=consent`` — we authenticate
            # the user once per login and have no background flow that needs
            # a refresh token. Re-add both (and persist the refresh token
            # encrypted at rest) before introducing any "act as the user
            # later" feature.
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{GOOGLE_AUTHORIZE_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthUserInfo:
        """Exchange an authorization code for an access token + userinfo.

        Args:
            code: Authorization code returned by Google to the redirect URI.
            code_verifier: PKCE verifier whose SHA-256 must match the
                ``code_challenge`` sent to ``build_authorize_url``. Google
                rejects the exchange if the values do not match.
        """
        client = self._get_client()
        try:
            token_response = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            logger.error(
                "GoogleOAuthClient - exchange_code - token request failed: {err}",
                err=e,
            )
            raise OAuthProviderError(message="Failed to contact Google.") from e

        if token_response.status_code != 200:
            logger.error(
                "GoogleOAuthClient - exchange_code - token endpoint returned {code}: {body}",
                code=token_response.status_code,
                body=token_response.text,
            )
            raise OAuthProviderError(message="Google rejected the authorization code.")

        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise OAuthProviderError(message="Google response missing access_token.")

        try:
            userinfo_response = await client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as e:
            logger.error(
                "GoogleOAuthClient - exchange_code - userinfo request failed: {err}",
                err=e,
            )
            raise OAuthProviderError(message="Failed to fetch Google userinfo.") from e

        if userinfo_response.status_code != 200:
            raise OAuthProviderError(message="Google userinfo request failed.")

        data = userinfo_response.json()
        sub = data.get("sub")
        email = data.get("email")
        if not sub or not email:
            raise OAuthProviderError(message="Google userinfo missing sub or email.")

        return OAuthUserInfo(
            sub=sub,
            email=email,
            email_verified=bool(data.get("email_verified", False)),
            name=data.get("name"),
            picture=data.get("picture"),
        )
