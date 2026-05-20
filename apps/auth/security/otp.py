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

Operational tooling:

* :func:`rotate_secret_storage` re-encrypts every ``users.totp_secret``
  from an old Fernet key to a new one. Used during scheduled key
  rotation per the dual-key procedure in
  ``docs/runbooks/auth-totp-rotation.md``. Idempotent.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import pyotp
import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.constants import TOTP_ROTATION_BATCH_SIZE
from apps.settings import app_settings

# Deterministic dev-mode Fernet key. NEVER trips in production because
# ``apps.settings._enforce_production_safety`` raises at startup when
# ``totp_encryption_key`` is empty AND ``ENVIRONMENT=production``.
# A constant key (vs ``secrets.token_bytes`` per process) means TOTP
# secrets encrypted in dev survive process restarts and tests stay
# deterministic. Loud warning is emitted once per process via lru_cache.
_DEV_FALLBACK_FERNET_KEY: bytes = base64.urlsafe_b64encode(b"\x00" * 32)


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

    logger.warning(
        "_load_totp_fernet - AUTH_TOTP_ENCRYPTION_KEY is empty; falling back "
        "to deterministic dev key. NEVER use this in production — generate one "
        "with `uv run python scripts/generate_totp_key.py` and set "
        "AUTH_TOTP_ENCRYPTION_KEY in the environment."
    )
    return Fernet(_DEV_FALLBACK_FERNET_KEY)


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


@dataclass(slots=True, kw_only=True, frozen=True)
class TotpRotationSummary:
    """Outcome of a :func:`rotate_secret_storage` run.

    Returned to the operator so the runbook's verification step can
    confirm the expected number of rows moved and that no row was
    silently dropped.
    """

    total_inspected: int
    re_encrypted: int
    already_new_key: int
    undecryptable: int


async def rotate_secret_storage(
    session: AsyncSession,
    *,
    old_key: str,
    new_key: str,
    batch_size: int = TOTP_ROTATION_BATCH_SIZE,
) -> TotpRotationSummary:
    """Re-encrypt every ``users.totp_secret`` from ``old_key`` to ``new_key``.

    Offline rotation helper. The caller owns the session and the
    surrounding transaction; this function performs raw SQL reads in
    batches of ``batch_size`` (id-ordered cursor pagination so a
    concurrent INSERT during rotation doesn't shift rows already
    processed) and per-row UPDATEs.

    Idempotency:

    * Rows that already decrypt cleanly with ``new_key`` are left
      untouched (counted under ``already_new_key``). Re-running the
      rotation after a partial outage therefore picks up only the
      rows that still need to move.
    * Rows that decrypt with neither key are logged as
      ``undecryptable`` (corrupted ciphertext, wrong key pair, or a
      stray plaintext from before the encryption migration) and
      skipped. Operators must hand-fix these out of band — silently
      re-encrypting unknown content would mask data loss.

    NOT a steady-state runtime API: the live app must keep using
    :func:`_load_totp_fernet`. This helper is intended for one-off
    maintenance windows; see ``docs/runbooks/auth-totp-rotation.md``
    for the full procedure.

    Args:
        session: An open ``AsyncSession`` bound to the writer engine.
            The caller is responsible for transaction management.
        old_key: URL-safe base64 Fernet key currently used at rest.
        new_key: URL-safe base64 Fernet key to rotate to. Generate one
            via ``cryptography.fernet.Fernet.generate_key()`` or
            ``scripts/generate_totp_key.py``.
        batch_size: Per-batch row count. Default
            :data:`TOTP_ROTATION_BATCH_SIZE`.

    Returns:
        :class:`TotpRotationSummary` with row counts the runbook
        verification step compares against expectations.

    Raises:
        ValueError: When either key is empty or malformed (Fernet
            constructor rejects it).
    """
    old_fernet = Fernet(old_key.encode("ascii"))
    new_fernet = Fernet(new_key.encode("ascii"))

    total = 0
    re_encrypted = 0
    already_new = 0
    undecryptable = 0
    cursor: str | None = None

    while True:
        if cursor is None:
            stmt = sa.text(
                "SELECT id, totp_secret FROM users "
                "WHERE totp_secret IS NOT NULL "
                "ORDER BY id ASC "
                "LIMIT :batch_size"
            )
            rows = (await session.execute(stmt, {"batch_size": batch_size})).fetchall()
        else:
            stmt = sa.text(
                "SELECT id, totp_secret FROM users "
                "WHERE totp_secret IS NOT NULL AND id > :cursor "
                "ORDER BY id ASC "
                "LIMIT :batch_size"
            )
            rows = (
                await session.execute(stmt, {"cursor": cursor, "batch_size": batch_size})
            ).fetchall()

        if not rows:
            break

        for row_id, ciphertext in rows:
            total += 1
            ct_bytes = ciphertext.encode("ascii")
            try:
                new_fernet.decrypt(ct_bytes)
                already_new += 1
                continue
            except InvalidToken:
                pass

            try:
                plaintext_bytes = old_fernet.decrypt(ct_bytes)
            except InvalidToken:
                undecryptable += 1
                logger.warning(
                    "rotate_secret_storage - row id={id} not decryptable with either key; "
                    "skipping (operator must hand-fix)",
                    id=row_id,
                )
                continue

            new_ciphertext = new_fernet.encrypt(plaintext_bytes).decode("ascii")
            await session.execute(
                sa.text("UPDATE users SET totp_secret = :ct WHERE id = :id"),
                {"ct": new_ciphertext, "id": row_id},
            )
            re_encrypted += 1

        cursor = rows[-1][0]
        if len(rows) < batch_size:
            break

    logger.info(
        "rotate_secret_storage - finished: total={total} re_encrypted={re} "
        "already_new={new} undecryptable={bad}",
        total=total,
        re=re_encrypted,
        new=already_new,
        bad=undecryptable,
    )
    return TotpRotationSummary(
        total_inspected=total,
        re_encrypted=re_encrypted,
        already_new_key=already_new,
        undecryptable=undecryptable,
    )


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
        if hmac.compare_digest(code, totp.at(candidate_time)):
            if last_counter is not None and candidate_counter <= last_counter:
                return None
            return candidate_counter
    return None
