"""Workspace-membership role enum.

These four roles are the **per-workspace** authorization unit. They are
deliberately a flat enum (not a hierarchy table) because the matrix is
small, well-known, and changes only when product policy changes.
"""

from __future__ import annotations

import enum


class WorkspaceRole(enum.StrEnum):
    """Membership role within a single workspace.

    Permission matrix (enforced via :mod:`apps.workspace.dependencies`):
    """

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    COMMENTER = "commenter"
