"""Workspace-module constants.

Module-level tunables typed with :data:`typing.Final` so call sites import
a single named value instead of repeating literals.
"""

from __future__ import annotations

import re
from typing import Final

WORKSPACE_SLUG_MIN_LENGTH: Final[int] = 3
WORKSPACE_SLUG_MAX_LENGTH: Final[int] = 80
WORKSPACE_NAME_MAX_LENGTH: Final[int] = 150
WORKSPACE_DESCRIPTION_MAX_LENGTH: Final[int] = 500

# Slugs are URL-safe lowercase identifiers: letters, digits, hyphens.
# Must start and end with an alphanumeric to forbid leading/trailing hyphens.
WORKSPACE_SLUG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?$")

# Reserved slugs that would collide with API path segments or sound official.
# Kept conservative — adding more later is non-breaking.
WORKSPACE_RESERVED_SLUGS: Final[frozenset[str]] = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "blog",
        "docs",
        "health",
        "internal",
        "login",
        "logout",
        "media",
        "metrics",
        "oauth",
        "public",
        "rbac",
        "register",
        "settings",
        "signup",
        "status",
        "support",
        "system",
        "user",
        "users",
        "workspace",
        "workspaces",
        "www",
    }
)

# Soft cap so a single workspace cannot accumulate unbounded membership rows.
# Tune via product policy; raising it is a code change, not a config knob,
# because the cap shapes downstream pagination / billing assumptions.
WORKSPACE_MAX_MEMBERS: Final[int] = 1000
