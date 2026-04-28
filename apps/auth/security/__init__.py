"""Auth-domain crypto primitives.

Replaces the legacy ``apps.core.security`` module. The package splits the
original mixed file into three cohesive submodules:

* :mod:`apps.auth.security.passwords` — bcrypt password hashing.
* :mod:`apps.auth.security.jwt` — RS256 JWT minting / verification + PKCE.
* :mod:`apps.auth.security.otp` — email OTP + TOTP encryption + replay guard.

Each submodule is independently importable; this package's ``__init__``
re-exports the public surface so callers may also write
``from apps.auth.security import hash_password``.
"""

from __future__ import annotations

from apps.auth.security.jwt import (
    TokenError,
    TokenExpiredError,
    compute_pkce_challenge,
    decode_token,
    generate_access_token,
    generate_challenge_token,
    generate_oauth_state_token,
    generate_pkce_verifier,
    generate_refresh_token,
    hash_token,
)
from apps.auth.security.otp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_otp_code,
    hash_otp_code,
    verify_totp_with_replay_guard,
)
from apps.auth.security.passwords import (
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)

__all__ = [
    "TokenError",
    "TokenExpiredError",
    "compute_pkce_challenge",
    "decode_token",
    "decrypt_totp_secret",
    "encrypt_totp_secret",
    "generate_access_token",
    "generate_challenge_token",
    "generate_oauth_state_token",
    "generate_otp_code",
    "generate_pkce_verifier",
    "generate_refresh_token",
    "hash_otp_code",
    "hash_password",
    "hash_password_async",
    "hash_token",
    "verify_password",
    "verify_password_async",
    "verify_totp_with_replay_guard",
]
