"""Security primitives: bcrypt password hashing + RS256 JWT + email OTP helpers.

All cryptographic configuration (key paths, TTLs, OTP length) is read from
``apps.settings.app_settings.auth``. The RSA keypair is loaded lazily via
``_load_jwt_keys()`` and cached for the process lifetime.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
import pyotp
from cryptography.fernet import Fernet
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


def create_oauth_state_token(*, state_id: str, code_verifier: str) -> str:
    """Sign a short-lived OAuth state token bound to a session cookie + PKCE verifier.

    The ``sid`` claim must match the value stored in the companion HttpOnly
    cookie set by ``/oauth/google/authorize``; the ``cv`` claim is the PKCE
    code_verifier used to redeem the authorization code on callback.
    """
    return _create_token(
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


# --------------------------- TOTP (2FA) -------------------------------------


_DEV_TOTP_KEY_SEED = b"dev-totp-fernet-key-DO-NOT-USE-IN-PROD"


@functools.lru_cache(maxsize=1)
def _load_totp_fernet() -> Fernet:
    """Build the Fernet instance used to encrypt TOTP secrets at rest.

    In production ``AUTH_TOTP_ENCRYPTION_KEY`` MUST be set (the settings
    validator already refuses to boot otherwise). In dev/test we derive a
    deterministic per-process key so the suite runs without forcing every
    contributor to mint and persist a real key.
    """
    raw = app_settings.auth.totp_encryption_key.get_secret_value()
    if raw:
        return Fernet(raw.encode("ascii"))
    derived = base64.urlsafe_b64encode(hashlib.sha256(_DEV_TOTP_KEY_SEED).digest())
    return Fernet(derived)


def encrypt_totp_secret(plaintext: str) -> str:
    """Encrypt a base32 TOTP secret with Fernet (AES-128-CBC + HMAC-SHA256).

    Returns the URL-safe base64 ciphertext (~100 chars) suitable for storage
    in ``users.totp_secret`` (varchar(255)).
    """
    return _load_totp_fernet().encrypt(plaintext.encode("ascii")).decode("ascii")


def decrypt_totp_secret(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted TOTP secret back to its base32 plaintext.

    Raises:
        cryptography.fernet.InvalidToken: If the ciphertext is corrupted,
            tampered, or was minted with a different key.
    """
    return _load_totp_fernet().decrypt(ciphertext.encode("ascii")).decode("ascii")


def verify_totp_with_replay_guard(
    *,
    secret: str,
    code: str,
    last_counter: int | None,
    valid_window: int = 1,
) -> int | None:
    """Verify a TOTP code AND ensure it has not been replayed.

    Walks the ``valid_window`` neighbourhood of the current 30-second time
    slice (per RFC 6238) and returns the matched counter when:
      1. The presented code matches one of the candidate counters, and
      2. That counter is strictly greater than ``last_counter`` (the
         counter recorded for the user's most recent successful verify).

    Returns ``None`` when the code does not match OR the matched counter
    has already been consumed (replay).
    """
    totp = pyotp.TOTP(secret)
    interval = totp.interval
    now = int(time.time())
    current_counter = now // interval
    for offset in range(-valid_window, valid_window + 1):
        candidate_counter = current_counter + offset
        candidate_time = candidate_counter * interval
        if pyotp.utils.strings_equal(code, totp.at(candidate_time)):
            if last_counter is not None and candidate_counter <= last_counter:
                return None
            return candidate_counter
    return None


# --------------------------- email OTP --------------------------------------


def generate_otp_code(length: int | None = None) -> str:
    """Generate a numeric OTP of the configured length (default 6)."""
    n = length or app_settings.auth.otp_length
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp_code(code: str) -> str:
    """SHA-256 hex digest used for OTP storage."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
