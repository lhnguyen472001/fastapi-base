"""ORM models for RBAC + ABAC.

Layout:

* :mod:`._casbin` — :class:`CasbinRule`, adapter-managed policy rows.
* :mod:`._core` — :class:`Role`, :class:`Permission`, :class:`Group`
  (first-class entities with hierarchy and metadata blobs).
* :mod:`._assignments` — :class:`RolePermission`, :class:`UserRole`,
  :class:`UserGroup`, :class:`GroupRole` — link rows carrying assignment
  metadata (``granted_by``, ``expires_at``, ``conditions``, ``is_active``).
* :mod:`._object` — :class:`ObjectPermission`, per-object ABAC grants.

All FK columns referencing ``users.id`` use UUID to match
:class:`apps.user.models.User`.

Public API is preserved via re-exports so every consumer can keep using
``from apps.rbac.models import Role`` etc. SQLAlchemy picks up every model
at import time because this ``__init__`` imports them all, which keeps the
shared metadata registry complete for Alembic autogenerate.
"""

from __future__ import annotations

from apps.rbac.models._assignments import (
    GroupRole,
    RolePermission,
    UserGroup,
    UserRole,
)
from apps.rbac.models._casbin import CasbinRule
from apps.rbac.models._core import Group, Permission, Role
from apps.rbac.models._object import ObjectPermission

__all__ = [
    "CasbinRule",
    "Group",
    "GroupRole",
    "ObjectPermission",
    "Permission",
    "Role",
    "RolePermission",
    "UserGroup",
    "UserRole",
]
