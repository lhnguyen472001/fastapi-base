"""Thin async Google OAuth2 client built on httpx."""


from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from loguru import logger

from apps.auth.exceptions import OAuthProviderError

GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_OAUTH_SCOPES = "openid email profile"


@dataclass(slots=True, kw_only=True, frozen=True)
class GoogleUserInfo:
    """Subset of Google's userinfo response that we care about."""

    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


class GoogleOAuthClient:
    """Async Google OAuth2 client.

    Stateless aside from the configured client_id/secret/redirect_uri.
    Each method call opens a fresh ``httpx.AsyncClient`` so the client is
    safe to share across requests.
    """

    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def build_authorize_url(self, *, state: str) -> str:
        """Build the Google consent screen URL.

        Args:
            state: Opaque random string the caller will validate on callback
                to mitigate CSRF.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_OAUTH_SCOPES,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTHORIZE_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, *, code: str) -> GoogleUserInfo:
        """Exchange an authorization code for an access token + userinfo."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                token_response = await client.post(
                    GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as e:
                logger.error("GoogleOAuthClient - exchange_code - token request failed: {err}", err=e)
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
                logger.error("GoogleOAuthClient - exchange_code - userinfo request failed: {err}", err=e)
                raise OAuthProviderError(message="Failed to fetch Google userinfo.") from e

            if userinfo_response.status_code != 200:
                raise OAuthProviderError(message="Google userinfo request failed.")

            data = userinfo_response.json()
            sub = data.get("sub")
            email = data.get("email")
            if not sub or not email:
                raise OAuthProviderError(message="Google userinfo missing sub or email.")

            return GoogleUserInfo(
                sub=sub,
                email=email,
                email_verified=bool(data.get("email_verified", False)),
                name=data.get("name"),
                picture=data.get("picture"),
            )
