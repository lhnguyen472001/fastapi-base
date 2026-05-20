"""Pytest fixtures for the statistical-timing test suite.

The :func:`statistical_timing_run` fixture drives N paired requests at two
endpoints (or two variants of the same endpoint) and returns aggregate
timing statistics — mean, variance, delta, and the raw samples. Tests
assert on the delta-of-means.

Default sample size is 10,000 (SC-005). Override via ``--timing-samples``
on the pytest invocation for local development.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

import pytest

T = TypeVar("T")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Allow the sample size to be tuned per run."""
    parser.addoption(
        "--timing-samples",
        action="store",
        type=int,
        default=10_000,
        help="Number of paired samples for statistical-timing tests.",
    )


@dataclass(slots=True)
class TimingResult:
    """Aggregate statistics for a paired-request timing run."""

    branch_a_label: str
    branch_b_label: str
    samples_a: list[float] = field(default_factory=list)
    samples_b: list[float] = field(default_factory=list)

    @property
    def mean_a(self) -> float:
        return statistics.mean(self.samples_a) if self.samples_a else 0.0

    @property
    def mean_b(self) -> float:
        return statistics.mean(self.samples_b) if self.samples_b else 0.0

    @property
    def delta_ms(self) -> float:
        return abs(self.mean_a - self.mean_b) * 1000.0

    @property
    def stdev_a(self) -> float:
        return statistics.stdev(self.samples_a) if len(self.samples_a) > 1 else 0.0

    @property
    def stdev_b(self) -> float:
        return statistics.stdev(self.samples_b) if len(self.samples_b) > 1 else 0.0


@pytest.fixture
def statistical_timing_run(
    request: pytest.FixtureRequest,
) -> Callable[..., Awaitable[TimingResult]]:
    """Return an async helper that runs paired timing measurements.

    Usage::

        async def test_login_timing_indistinguishable(statistical_timing_run):
            result = await statistical_timing_run(
                branch_a=lambda: client.post("/login", json={"email": "unknown@x"}),
                branch_b=lambda: client.post("/login", json={"email": "known@x"}),
                label_a="unknown",
                label_b="known",
            )
            assert result.delta_ms < 15.0, (
                f"timing delta {result.delta_ms:.2f}ms exceeds budget"
            )
    """
    sample_size: int = request.config.getoption("--timing-samples")

    async def _run(
        *,
        branch_a: Callable[[], Awaitable[T]],
        branch_b: Callable[[], Awaitable[T]],
        label_a: str = "A",
        label_b: str = "B",
        samples: int | None = None,
    ) -> TimingResult:
        n = samples if samples is not None else sample_size
        result = TimingResult(branch_a_label=label_a, branch_b_label=label_b)
        for _ in range(n):
            start_a = time.perf_counter()
            await branch_a()
            result.samples_a.append(time.perf_counter() - start_a)
            start_b = time.perf_counter()
            await branch_b()
            result.samples_b.append(time.perf_counter() - start_b)
        return result

    return _run
