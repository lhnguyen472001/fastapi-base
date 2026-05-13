"""OpenTelemetry instruments + structured-log helpers for RBAC observability.

F-SCALE-2: every authorization-policy compensation event (a path where the
relational store committed but the Casbin policy store did not converge)
MUST emit a counter increment plus an ERROR-level structured log within
the same request, so silent drift between Postgres and the policy store
becomes operationally visible.

The instrument contract is documented at
``specs/002-code-quality-perf-improvements/contracts/metrics.md``:

* Name:        ``rbac_compensation_drift_total``
* Kind:        Counter (monotonic; cumulative per worker)
* Unit:        ``1``
* Attributes:  ``kind`` (one of ``user_group``, ``group_role``,
               ``role_permission``, ``object_permission``); ``outcome``
               (``compensated`` or ``abandoned``).

Call ``record_compensation_drift(...)`` from every ``_compensate_*`` site
in ``apps/rbac/services/``; it handles both the metric and the log.
"""

from __future__ import annotations

from typing import Final, Literal

from loguru import logger
from opentelemetry import metrics

DriftKind = Literal["user_group", "group_role", "role_permission", "object_permission"]
DriftOutcome = Literal["compensated", "abandoned"]

_METER_NAME: Final[str] = "apps.rbac"
_COUNTER_NAME: Final[str] = "rbac_compensation_drift_total"

_meter = metrics.get_meter(_METER_NAME)
_drift_counter = _meter.create_counter(
    name=_COUNTER_NAME,
    unit="1",
    description=(
        "Count of RBAC compensation events emitted from _compensate_* paths. "
        "Tagged by kind={user_group|group_role|role_permission|object_permission} "
        "and outcome={compensated|abandoned}. See contracts/metrics.md."
    ),
)


def record_compensation_drift(
    *,
    kind: DriftKind,
    outcome: DriftOutcome,
    target_id: int,
    mutation: str,
    cause: BaseException,
    subject_id: str | None = None,
) -> None:
    """Increment ``rbac_compensation_drift_total`` and emit a structured ERROR log.

    Both side effects MUST happen together — operators expect to see the
    log line for every counter increment, and vice versa. Failure of one
    must not skip the other.

    Args:
        kind: Compensation class (one of the four documented values).
        outcome: ``compensated`` when the relational rollback succeeded,
            ``abandoned`` when the compensation itself failed (persistent drift).
        target_id: The relational row id that committed (membership_id,
            link_id, grant_id depending on ``kind``).
        mutation: Name of the originating mutation method
            (``add_user_to_group``, ``grant_permission_to_role``, etc.).
        cause: The exception raised by the policy-store sync attempt.
        subject_id: Optional subject identifier (e.g. ``"u:<uuid>"``) for
            kinds where the subject is unambiguous; ``None`` otherwise.
    """
    _drift_counter.add(1, {"kind": kind, "outcome": outcome})
    logger.bind(
        kind=kind,
        outcome=outcome,
        target_id=target_id,
        mutation=mutation,
        cause=repr(cause),
        subject_id=subject_id,
    ).error("RBAC compensation drift")
