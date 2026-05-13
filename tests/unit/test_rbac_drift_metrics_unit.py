"""Unit tests for the RBAC drift-observability helper in ``apps.rbac._metrics``.

Covers F-SCALE-2 / FR-003 / FR-004 / SC-002 at the helper level:

* The counter receives ``add(1, {"kind", "outcome"})`` with the documented
  attribute keys (see ``contracts/metrics.md``).
* An ERROR-level loguru log is emitted with bound structured context:
  ``kind``, ``outcome``, ``target_id``, ``mutation``, ``cause``,
  ``subject_id``.
* Both the metric increment AND the log fire from a single helper call —
  the spec requires they happen together.

The integration test in ``tests/integration/realdb/test_rbac_drift_emit_realdb.py``
verifies the helper is actually invoked from the live ``_compensate_*``
methods; this test pins the helper's own contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from loguru import logger

from apps.rbac import _metrics

pytestmark = pytest.mark.unit


def _make_log_capture() -> tuple[list[dict], int]:
    """Install a loguru sink and return (captured_records, handler_id)."""
    records: list[dict] = []

    def _sink(message) -> None:  # type: ignore[no-untyped-def]
        records.append(message.record)

    handler_id = logger.add(_sink, level="ERROR", format="{message}")
    return records, handler_id


def test_record_drift_increments_counter_with_kind_and_outcome() -> None:
    cause = RuntimeError("simulated casbin outage")

    with patch.object(_metrics, "_drift_counter") as mock_counter:
        _metrics.record_compensation_drift(
            kind="user_group",
            outcome="compensated",
            target_id=42,
            mutation="add_user_to_group",
            cause=cause,
            subject_id="u:abc",
        )

    mock_counter.add.assert_called_once_with(1, {"kind": "user_group", "outcome": "compensated"})


def test_record_drift_emits_error_log_with_bound_context() -> None:
    records, handler_id = _make_log_capture()
    try:
        with patch.object(_metrics, "_drift_counter"):
            _metrics.record_compensation_drift(
                kind="object_permission",
                outcome="abandoned",
                target_id=99,
                mutation="grant_object_permission",
                cause=RuntimeError("boom"),
                subject_id="u:xyz",
            )
    finally:
        logger.remove(handler_id)

    drift_logs = [r for r in records if "RBAC compensation drift" in r["message"]]
    assert len(drift_logs) == 1, f"expected 1 drift log, got {len(drift_logs)}"
    extra = drift_logs[0]["extra"]
    assert extra["kind"] == "object_permission"
    assert extra["outcome"] == "abandoned"
    assert extra["target_id"] == 99
    assert extra["mutation"] == "grant_object_permission"
    assert extra["subject_id"] == "u:xyz"
    assert "boom" in extra["cause"]


def test_record_drift_accepts_each_documented_kind() -> None:
    """All four ``kind`` enum values from contracts/metrics.md are accepted."""
    cause = RuntimeError("x")
    with patch.object(_metrics, "_drift_counter") as mock_counter:
        for kind in ("user_group", "group_role", "role_permission", "object_permission"):
            _metrics.record_compensation_drift(
                kind=kind,  # type: ignore[arg-type]
                outcome="compensated",
                target_id=1,
                mutation="m",
                cause=cause,
            )
    assert mock_counter.add.call_count == 4


def test_record_drift_handles_missing_subject_id() -> None:
    """``subject_id=None`` is allowed for kinds where the concept is ambiguous."""
    records, handler_id = _make_log_capture()
    try:
        with patch.object(_metrics, "_drift_counter"):
            _metrics.record_compensation_drift(
                kind="group_role",
                outcome="compensated",
                target_id=7,
                mutation="assign_role_to_group",
                cause=RuntimeError("x"),
                subject_id=None,
            )
    finally:
        logger.remove(handler_id)

    drift_logs = [r for r in records if "RBAC compensation drift" in r["message"]]
    assert len(drift_logs) == 1
    assert drift_logs[0]["extra"]["subject_id"] is None
