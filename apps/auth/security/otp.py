"""Email OTP + TOTP encryption + replay guard.

Two distinct one-time-code concerns share this module:

* **Email OTP** — short numeric codes mailed for email-verification.
  Random-generated and stored as SHA-256 hashes in the
  ``email_verifications`` table.
* **TOTP** (RFC 6238) — authenticator-app codes for 2FA. The base32
  secret is encrypted at rest with Fernet so a DB read does not yield a
  permanent 2FA bypass. ``verify_totp_with_replay_guard`` walks the
  current 30-second time window and rejects already-consumed counters
  to prevent shoulder-surf replay within the same window.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import secrets
import time

import pyotp
from cryptography.fernet import Fernet

from apps.settings import app_settings


def generate_otp_code(length: int | None = None) -> str:
    """Generate a numeric OTP of the configured length (default 6)."""
    n = length or app_settings.auth.otp_length
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp_code(code: str) -> str:
    """SHA-256 hex digest used for OTP storage."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=1)
def _load_totp_fernet() -> Fernet:
    """Build the Fernet instance used to encrypt TOTP secrets at rest."""
    raw = app_settings.auth.totp_encryption_key.get_secret_value()

    if raw:
        return Fernet(raw.encode("ascii"))

    derived = base64.urlsafe_b64encode(hashlib.sha256(secrets.token_bytes(32)).digest())
    return Fernet(derived.decode("ascii"))


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
