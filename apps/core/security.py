"""Security primitives: bcrypt password hashing + RS256 JWT + email OTP helpers.

All cryptographic configuration (key paths, TTLs, OTP length) is read from
``apps.settings.app_settings.auth``. The RSA keypair is loaded lazily via
``_load_jwt_keys()`` and cached for the process lifetime.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as PyJWTError

from apps.auth.enums import TokenType
from apps.settings import app_settings

_BCRYPT_ROUNDS = 12


# --------------------------- password hashing -------------------------------


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt and a fresh salt.

    Synchronous. Safe to call from scripts, seed helpers, and tests.
    In async request paths, prefer :func:`hash_password_async` so the
    bcrypt work (CPU-bound, ~200-500 ms at rounds=12) does not block
    the event loop.
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Synchronous counterpart of :func:`verify_password_async`. Use the
    async version on request paths.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


async def hash_password_async(plain_password: str) -> str:
    """Async wrapper around :func:`hash_password`.

    Runs the CPU-bound bcrypt work on the default thread-pool executor
    so the asyncio event loop stays responsive under concurrent logins
    and registrations.
    """
    return await asyncio.to_thread(hash_password, plain_password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Async wrapper around :func:`verify_password`."""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


# --------------------------- JWT (RS256) ------------------------------------


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
            "Run `uv run python scripts/generate_jwt_keys.py` to create a dev pair."
        )
        raise RuntimeError(msg)

    return _JWTKeyPair(
        private_key=private_path.read_bytes(),
        public_key=public_path.read_bytes(),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
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


def create_access_token(*, subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Sign a short-lived access token for the given user subject."""
    return _create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_in=timedelta(minutes=app_settings.auth.access_token_expire_minutes),
        extra_claims=extra_claims,
    )


def create_refresh_token(*, subject: str) -> tuple[str, datetime]:
    """Sign a long-lived refresh token; return (jwt, expires_at)."""
    expires_in = timedelta(days=app_settings.auth.refresh_token_expire_days)
    token = _create_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        expires_in=expires_in,
    )
    return token, _now() + expires_in


def create_challenge_token(*, subject: str) -> str:
    """Sign a short-lived 2FA challenge token (issued after step 1 of login)."""
    return _create_token(
        subject=subject,
        token_type=TokenType.CHALLENGE,
        expires_in=timedelta(minutes=app_settings.auth.challenge_token_expire_minutes),
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
            (``ACCESS`` / ``REFRESH`` / ``CHALLENGE``).

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


# --------------------------- email OTP --------------------------------------


def generate_otp_code(length: int | None = None) -> str:
    """Generate a numeric OTP of the configured length (default 6)."""
    n = length or app_settings.auth.otp_length
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp_code(code: str) -> str:
    """SHA-256 hex digest used for OTP storage."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
