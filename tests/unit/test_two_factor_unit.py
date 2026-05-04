"""Unit tests for TOTP encryption + replay-guard logic.

Exercises ``apps.core.security`` Fernet helpers and the
``apps.auth.services.TwoFactorService._consume_code`` replay guard
without requiring a real DB. The user is modelled as a plain object so
attribute writes are observable.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pyotp
import pytest

from apps.auth.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    verify_totp_with_replay_guard,
)
from apps.auth.services._two_factor import TwoFactorService

# ----------------------------- Fernet helpers -------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    plaintext = pyotp.random_base32()

    ciphertext = encrypt_totp_secret(plaintext)

    assert ciphertext != plaintext
    assert len(ciphertext) > 64  # Fernet output is ~100 chars
    assert decrypt_totp_secret(ciphertext) == plaintext


def test_encrypt_two_calls_produce_distinct_ciphertexts() -> None:
    """Fernet is non-deterministic (random IV), so two encryptions of the
    same plaintext must differ — otherwise the at-rest column leaks
    information about identical secrets.
    """
    plaintext = "JBSWY3DPEHPK3PXP"

    a = encrypt_totp_secret(plaintext)
    b = encrypt_totp_secret(plaintext)

    assert a != b
    assert decrypt_totp_secret(a) == plaintext
    assert decrypt_totp_secret(b) == plaintext


def test_decrypt_rejects_tampered_ciphertext() -> None:
    ciphertext = encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    tampered = ciphertext[:-4] + "AAAA"

    with pytest.raises(Exception):  # noqa: B017 — InvalidToken or similar
        decrypt_totp_secret(tampered)


# ------------------------ replay-guard counter helper -----------------------


def test_replay_guard_accepts_fresh_code_with_no_history() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()

    matched = verify_totp_with_replay_guard(secret=secret, code=code, last_counter=None)

    assert matched is not None
    assert matched > 0


def test_replay_guard_rejects_already_consumed_counter() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    matched_first = verify_totp_with_replay_guard(secret=secret, code=code, last_counter=None)
    assert matched_first is not None

    matched_replay = verify_totp_with_replay_guard(
        secret=secret,
        code=code,
        last_counter=matched_first,
    )

    assert matched_replay is None


def test_replay_guard_rejects_obviously_wrong_code() -> None:
    secret = pyotp.random_base32()

    matched = verify_totp_with_replay_guard(secret=secret, code="000000", last_counter=None)

    # Could theoretically collide with the genuine code 1-in-1M, but the
    # probability is negligible for a unit-test smoke check.
    if matched is not None:
        # Re-roll once if we hit the unlucky collision.
        secret = pyotp.random_base32()
        matched = verify_totp_with_replay_guard(secret=secret, code="000000", last_counter=None)
    assert matched is None


def test_replay_guard_rejects_code_outside_window() -> None:
    """A code from far in the past must not validate."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    earlier_counter = (now // totp.interval) - 5
    earlier_code = totp.at(earlier_counter)

    assert verify_totp_with_replay_guard(secret=secret, code=earlier_code, last_counter=None) is None


# --------------------- TwoFactorService._consume_code -----------------------


def _fake_user(
    secret_plaintext: str | None, *, last_counter: int | None = None, enabled: bool = True
) -> SimpleNamespace:
    """In-memory user mimicking the User ORM shape used by the service."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        totp_secret=encrypt_totp_secret(secret_plaintext) if secret_plaintext else None,
        is_2fa_enabled=enabled,
        last_totp_counter=last_counter,
    )


def _fake_session() -> AsyncMock:
    return AsyncMock()


def _make_service() -> tuple[TwoFactorService, AsyncMock]:
    """Build a TwoFactorService with a mocked UserRepository.

    The mock's ``update`` reflects the new ``last_totp_counter`` back onto
    the in-memory user so tests that issue multiple verify calls observe
    replay-guard advancement.
    """
    user_repo = AsyncMock()

    return TwoFactorService(user_repository=user_repo), user_repo


@pytest.mark.asyncio
async def test_verify_accepts_fresh_code_and_persists_counter() -> None:
    service, user_repo = _make_service()
    secret = pyotp.random_base32()
    user = _fake_user(secret)
    session = _fake_session()
    code = pyotp.TOTP(secret).now()

    ok = await service.verify(session, user=user, totp_code=code)

    assert ok is True
    user_repo.update.assert_awaited_once()
    persisted = user_repo.update.await_args.kwargs["data"]
    assert "last_totp_counter" in persisted
    assert persisted["last_totp_counter"] is not None
    assert persisted["last_totp_counter"] > 0


@pytest.mark.asyncio
async def test_verify_rejects_replay_of_same_code() -> None:
    service, user_repo = _make_service()
    secret = pyotp.random_base32()
    user = _fake_user(secret)
    session = _fake_session()
    code = pyotp.TOTP(secret).now()

    first = await service.verify(session, user=user, totp_code=code)
    # Reflect the persisted counter so the second verify sees it as already-consumed.
    user.last_totp_counter = user_repo.update.await_args.kwargs["data"]["last_totp_counter"]
    second = await service.verify(session, user=user, totp_code=code)

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_verify_returns_false_when_2fa_disabled() -> None:
    service, user_repo = _make_service()
    secret = pyotp.random_base32()
    user = _fake_user(secret, enabled=False)
    session = _fake_session()
    code = pyotp.TOTP(secret).now()

    ok = await service.verify(session, user=user, totp_code=code)

    assert ok is False
    user_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_returns_false_when_secret_missing() -> None:
    service, user_repo = _make_service()
    user = _fake_user(None, enabled=True)
    session = _fake_session()

    ok = await service.verify(session, user=user, totp_code="000000")

    assert ok is False
    user_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_rejects_wrong_code_without_advancing_counter() -> None:
    service, user_repo = _make_service()
    secret = pyotp.random_base32()
    user = _fake_user(secret)
    session = _fake_session()

    ok = await service.verify(session, user=user, totp_code="000000")

    if ok:
        # 1-in-1M chance of accidental match — re-roll once.
        secret = pyotp.random_base32()
        user = _fake_user(secret)
        user_repo.update.reset_mock()
        ok = await service.verify(session, user=user, totp_code="000000")
    assert ok is False
    user_repo.update.assert_not_awaited()
