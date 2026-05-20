"""RBAC-domain string constants.

The Casbin policy engine speaks plain strings — these constants are the
single source of truth for the prefixes embedded in subject and object
tokens. Module-level ``Final`` typing prevents accidental rebinding and
documents the wire format that the ``casbin_rule`` table is committed to.
"""

from __future__ import annotations

from typing import Final

# Subject prefixes
USER_PREFIX: Final[str] = "user:"
ROLE_PREFIX: Final[str] = "role:"

# Object token separator: ``<resource>:<object_id>`` for instance-level grants.
OBJECT_TOKEN_SEPARATOR: Final[str] = ":"  # noqa: S105 — Casbin token delimiter, not a password

# Page size for streaming group-membership lookups when fanning a role
# assignment out across every member of a group. Bounds the size of each
# DB roundtrip (and the per-page intermediate list) for groups with very
# large active memberships; the service accumulates the full rule list
# across pages before handing it to Casbin so policy-sync semantics are
# unchanged. See ``GroupService._db_assign_role_to_group``.
RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE: Final[int] = 500

# Heartbeat cadence for the periodic ``enforcer.load_policy()`` fallback
# that runs alongside the Redis pub/sub watcher. Even with a healthy
# watcher, this guarantees per-worker policy convergence within the
# interval if pub/sub messages are silently lost (network partition,
# Redis restart between subscribe + publish, etc.). Trade-off: one extra
# ``SELECT * FROM casbin_rule`` per worker per interval; at the default
# 300s that is ~12 reads / hour / worker.
RBAC_ENFORCER_HEARTBEAT_INTERVAL_SECONDS: Final[int] = 300

# Timeout for the boot-time PING against the watcher Redis URL. A missing
# or unreachable watcher is configured to fail-fast at startup so the
# operator sees the misconfiguration before stale-policy drift occurs.
RBAC_ENFORCER_WATCHER_PING_TIMEOUT_SECONDS: Final[float] = 2.0
