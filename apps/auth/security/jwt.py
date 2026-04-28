"""RS256 JWT minting / verification + PKCE helpers.

The RSA keypair is loaded lazily via :func:`_load_jwt_keys` and cached for
the process lifetime. Algorithms are hard-pinned to RS256 to prevent the
RS256 -> HS256 confusion attack.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as PyJWTError

from apps.auth.enums import TokenType
from apps.settings import app_settings


@dataclass(frozen=True)
class _JWTKeyPair:
    private_key: bytes
    public_key: bytes


@functools.lru_cache(maxsize=1)
def _load_jwt_keys() -> _JWTKeyPair:
    """Read the RSA keypair from disk (cached after first call)."""
    auth = app_settings.auth
    private_path = auth.jwt_private_key_path
    public_path = auth.jwt_public_key_path

    if not private_path.exists() or not public_path.exists():
        msg = (
            f"JWT key files not found: {private_path}, {public_path}. "
            "Run `uv run python scripts/generate_jwt_keys.py` to generate a dev pair."
        )
        raise RuntimeError(msg)

    return _JWTKeyPair(
        private_key=private_path.read_bytes(),
        public_key=public_path.read_bytes(),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _generate_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_in: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Build and sign a JWT with the standard claims."""
    keys = _load_jwt_keys()
    issued_at = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + expires_in).timestamp()),
        "jti": str(uuid.uuid4()),
        "iss": app_settings.auth.jwt_issuer,
        "aud": app_settings.auth.jwt_audience,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, keys.private_key, algorithm="RS256")


def generate_access_token(*, subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Sign a short-lived access token for the given user subject."""
    return _generate_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_in=timedelta(minutes=app_settings.auth.access_token_expire_minutes),
        extra_claims=extra_claims,
    )


def generate_refresh_token(*, subject: str) -> tuple[str, datetime]:
    """Sign a long-lived refresh token; return (jwt, expires_at)."""
    expires_in = timedelta(days=app_settings.auth.refresh_token_expire_days)
    token = _generate_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        expires_in=expires_in,
    )
    return token, _now() + expires_in


def generate_challenge_token(*, subject: str) -> str:
    """Sign a short-lived 2FA challenge token (issued after step 1 of login)."""
    return _generate_token(
        subject=subject,
        token_type=TokenType.CHALLENGE,
        expires_in=timedelta(minutes=app_settings.auth.challenge_token_expire_minutes),
    )


def generate_oauth_state_token(*, state_id: str, code_verifier: str) -> str:
    """Sign a short-lived OAuth state token bound to a session cookie + PKCE verifier.

    The ``sid`` claim must match the value stored in the companion HttpOnly
    cookie set by ``/oauth/google/authorize``; the ``cv`` claim is the PKCE
    code_verifier used to redeem the authorization code on callback.
    """
    return _generate_token(
        subject="oauth_state",
        token_type=TokenType.OAUTH_STATE,
        expires_in=timedelta(minutes=app_settings.auth.oauth_state_expire_minutes),
        extra_claims={"sid": state_id, "cv": code_verifier},
    )


class TokenError(Exception):
    """Raised when a JWT cannot be decoded or fails validation."""


class TokenExpiredError(TokenError):
    """Raised when a JWT is past its ``exp`` claim."""


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Verify a JWT's signature, expiry, and ``type`` claim.

    Args:
        token: The encoded JWT.
        expected_type: A :class:`apps.auth.enums.TokenType` member
            (``ACCESS`` / ``REFRESH`` / ``CHALLENGE`` / ``OAUTH_STATE``).

    Returns:
        The decoded claims dict.

    Raises:
        TokenExpiredError: If the token is past its ``exp``.
        TokenError: For any other validation failure (signature, type mismatch,
            malformed payload).
    """
    keys = _load_jwt_keys()
    try:
        payload = jwt.decode(
            token,
            keys.public_key,
            algorithms=["RS256"],
            audience=app_settings.auth.jwt_audience,
            issuer=app_settings.auth.jwt_issuer,
        )
    except ExpiredSignatureError as e:
        raise TokenExpiredError("Token has expired") from e
    except PyJWTError as e:
        raise TokenError(f"Invalid token: {e}") from e

    if payload.get("type") != expected_type:
        raise TokenError(f"Wrong token type: expected '{expected_type}', got '{payload.get('type')}'")
    return payload


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest used for refresh token storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# --------------------------- PKCE (RFC 7636) --------------------------------


def generate_pkce_verifier() -> str:
    """Generate a cryptographically random PKCE ``code_verifier`` (RFC 7636 §4.1).

    Produces 86 URL-safe base64 characters drawn from the unreserved set
    ``[A-Za-z0-9-._~]``, comfortably inside the 43-128 range required by
    the spec.
    """
    return secrets.token_urlsafe(64)


def compute_pkce_challenge(verifier: str) -> str:
    """Compute the S256 ``code_challenge`` for a PKCE verifier (RFC 7636 §4.2).

    ``code_challenge = BASE64URL-NOPAD(SHA256(ASCII(code_verifier)))``.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
