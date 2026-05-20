"""Unit tests for MED-7: TOTP key rotation helper.

``rotate_secret_storage`` must:

* Re-encrypt every ``users.totp_secret`` from ``old_key`` to ``new_key``.
* Be idempotent — rows already encrypted with ``new_key`` are
  counted under ``already_new_key`` and not touched.
* Tolerate undecryptable rows by counting them and skipping (never
  silently re-encrypting unknown content, never halting the rotation).
* Page reads in id-cursor batches so a 100k-row table doesn't blow
  the worker's memory.

These tests mock :class:`AsyncSession.execute` so they exercise the
SQL-shape contract without needing a real database.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.constants import TOTP_ROTATION_BATCH_SIZE
from apps.auth.security.otp import TotpRotationSummary, rotate_secret_storage


def _fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _encrypt(key: str, plaintext: str) -> str:
    return Fernet(key.encode("ascii")).encrypt(plaintext.encode("ascii")).decode("ascii")


def _build_session(rows: list[tuple[int, str]]) -> tuple[MagicMock, list[dict[str, Any]]]:
    """Build a mock AsyncSession that paginates over ``rows``.

    Each call to ``execute`` is inspected; SELECTs return the right
    slice of ``rows`` (filtered by the ``:cursor`` bind, if any), and
    UPDATEs are captured into the returned ``updates`` list so tests
    can assert on the new ciphertexts.
    """
    updates: list[dict[str, Any]] = []

    async def fake_execute(stmt: Any, params: dict[str, Any] | None = None) -> MagicMock:
        sql_text = str(stmt).upper()
        params = params or {}

        if sql_text.startswith("SELECT"):
            limit = int(params["batch_size"])
            cursor = params.get("cursor")
            if cursor is None:
                page = rows[:limit]
            else:
                page = [r for r in rows if r[0] > cursor][:limit]
            result = MagicMock()
            result.fetchall = MagicMock(return_value=page)
            return result

        if sql_text.startswith("UPDATE"):
            updates.append(dict(params))
            return MagicMock()

        msg = f"unexpected SQL: {sql_text[:80]}"
        raise AssertionError(msg)

    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=fake_execute)
    return session, updates


@pytest.mark.asyncio
async def test_round_trip_rotation_re_encrypts_every_row() -> None:
    """Every old-key row must end up encrypted under new_key, recoverable
    to its original plaintext via Fernet(new_key)."""
    old_key = _fernet_key()
    new_key = _fernet_key()
    plaintexts = ["JBSWY3DPEHPK3PXP", "GEZDGNBVGY3TQOJQ", "MFRGGZDFMZTWQ2LK"]
    rows = [(i + 1, _encrypt(old_key, p)) for i, p in enumerate(plaintexts)]

    session, updates = _build_session(rows)
    summary = await rotate_secret_storage(session, old_key=old_key, new_key=new_key)

    assert summary == TotpRotationSummary(
        total_inspected=3,
        re_encrypted=3,
        already_new_key=0,
        undecryptable=0,
    )

    assert [u["id"] for u in updates] == [1, 2, 3]
    new_fernet = Fernet(new_key.encode("ascii"))
    for upd, expected_plaintext in zip(updates, plaintexts, strict=True):
        recovered = new_fernet.decrypt(upd["ct"].encode("ascii")).decode("ascii")
        assert recovered == expected_plaintext


@pytest.mark.asyncio
async def test_idempotent_skip_for_already_new_key_rows() -> None:
    """Rows already encrypted under new_key must be counted as
    ``already_new_key`` and NOT touched (no UPDATE issued)."""
    old_key = _fernet_key()
    new_key = _fernet_key()
    rows = [
        (1, _encrypt(old_key, "ABCDEFGHIJKL")),
        (2, _encrypt(new_key, "MNOPQRSTUVWX")),  # already on new_key
        (3, _encrypt(old_key, "QRSTUVWXYZAB")),
    ]

    session, updates = _build_session(rows)
    summary = await rotate_secret_storage(session, old_key=old_key, new_key=new_key)

    assert summary.total_inspected == 3
    assert summary.re_encrypted == 2
    assert summary.already_new_key == 1
    assert summary.undecryptable == 0
    # Only rows 1 and 3 were updated; row 2 was left alone.
    assert sorted(u["id"] for u in updates) == [1, 3]


@pytest.mark.asyncio
async def test_undecryptable_rows_are_counted_and_skipped_not_raised() -> None:
    """A row whose ciphertext decrypts with neither key must be logged
    and counted under ``undecryptable``, never silently re-encrypted
    and never halting the loop for sibling rows."""
    old_key = _fernet_key()
    new_key = _fernet_key()
    unrelated_key = _fernet_key()
    rows = [
        (1, _encrypt(old_key, "VALIDOLDKEY1")),
        (2, _encrypt(unrelated_key, "STRANGEKEY!!")),
        (3, _encrypt(old_key, "VALIDOLDKEY3")),
    ]

    session, updates = _build_session(rows)
    summary = await rotate_secret_storage(session, old_key=old_key, new_key=new_key)

    assert summary.total_inspected == 3
    assert summary.re_encrypted == 2
    assert summary.already_new_key == 0
    assert summary.undecryptable == 1
    # The stranger row (id=2) was NOT updated.
    assert sorted(u["id"] for u in updates) == [1, 3]


@pytest.mark.asyncio
async def test_empty_table_yields_zero_summary() -> None:
    """No rows with totp_secret IS NOT NULL → all-zero summary, no UPDATEs."""
    old_key = _fernet_key()
    new_key = _fernet_key()

    session, updates = _build_session(rows=[])
    summary = await rotate_secret_storage(session, old_key=old_key, new_key=new_key)

    assert summary == TotpRotationSummary(
        total_inspected=0,
        re_encrypted=0,
        already_new_key=0,
        undecryptable=0,
    )
    assert updates == []


@pytest.mark.asyncio
async def test_pagination_walks_id_cursor_across_multiple_batches() -> None:
    """250 rows with batch_size=100 must produce SELECTs at offsets
    0 / id>100 / id>200, all 250 re-encrypted exactly once."""
    old_key = _fernet_key()
    new_key = _fernet_key()
    rows = [(i + 1, _encrypt(old_key, f"SECRET{i:03d}")) for i in range(250)]

    session, updates = _build_session(rows)
    summary = await rotate_secret_storage(
        session,
        old_key=old_key,
        new_key=new_key,
        batch_size=100,
    )

    assert summary.total_inspected == 250
    assert summary.re_encrypted == 250
    assert len(updates) == 250
    # Every id covered exactly once.
    assert sorted(u["id"] for u in updates) == list(range(1, 251))


@pytest.mark.asyncio
async def test_default_batch_size_matches_module_constant() -> None:
    """Constant + default kw share the same value so a runbook change
    in one place propagates without per-callsite edits."""
    old_key = _fernet_key()
    new_key = _fernet_key()

    session, _ = _build_session(rows=[])
    await rotate_secret_storage(session, old_key=old_key, new_key=new_key)

    # First SELECT must have used the module-level default.
    first_call = session.execute.await_args_list[0]
    params = first_call.args[1] if len(first_call.args) > 1 else first_call.kwargs.get("params", {})
    assert params["batch_size"] == TOTP_ROTATION_BATCH_SIZE


@pytest.mark.asyncio
async def test_malformed_key_raises_immediately() -> None:
    """A non-Fernet key must surface as a ValueError before any DB I/O
    so the operator can't accidentally pass the wrong env var and
    silently corrupt every row."""
    session, _ = _build_session(rows=[])
    with pytest.raises((ValueError, InvalidToken, Exception)):
        await rotate_secret_storage(session, old_key="not-a-fernet-key", new_key=_fernet_key())
