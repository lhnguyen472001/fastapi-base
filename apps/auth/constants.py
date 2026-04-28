"""Auth-module constants.

Module-level constants are centralised here so call sites import a single
named value instead of repeating literals (and so any tweak — e.g. lowering
the bcrypt cost factor under tests — happens in one place).
"""

from __future__ import annotations

from typing import Final

BCRYPT_ROUNDS: Final[int] = 12
OAUTH_STATE_COOKIE_NAME: Final[str] = "oauth_state"

USER_CACHE_KEY_PREFIX: Final[str] = "auth:user"
USER_CACHE_TTL_SECONDS: Final[int] = 60

OAUTH_COOKIE_PATH: Final[str] = "/api/v1/auth/oauth/google"

GOOGLE_AUTHORIZE_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"  # noqa: S105 — public OAuth endpoint URL, not a credential
GOOGLE_USERINFO_ENDPOINT: Final[str] = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_OAUTH_SCOPES: Final[str] = "openid email profile"

GOOGLE_OAUTH_HTTP_TIMEOUT_SECONDS: Final[float] = 10.0
