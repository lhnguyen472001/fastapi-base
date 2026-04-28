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
