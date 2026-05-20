"""Redis-module constants."""

from __future__ import annotations

from typing import Final

INVALIDATE_BATCH_SIZE: Final[int] = 500

# One-shot retry budget for transient Redis errors (ConnectionError /
# TimeoutError) in hot paths. The default of 2 = "try once, retry once,
# then fall through to the caller's safe fallback". Anything higher would
# inflate p99 latency during a real outage; lower defeats the purpose of
# riding through a one-shot network blip.
REDIS_TRANSIENT_RETRY_ATTEMPTS: Final[int] = 2

# Backoff between the first failure and the single retry. 50 ms is short
# enough to disappear into normal request latency for a typical Redis
# call (sub-millisecond on the happy path) but long enough to clear most
# transient blips (TCP retransmit, broker failover handoff).
REDIS_TRANSIENT_RETRY_DELAY_SECONDS: Final[float] = 0.05
