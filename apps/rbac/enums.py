"""RBAC-domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class ObjectAction(StrEnum):
    """Canonical action verbs accepted by the RBAC enforcer.

    Routes pass these to :func:`apps.rbac.dependencies.access_required` and
    to ``access_required(resource, action)``-style decorators. Because
    ``StrEnum`` members are plain strings at runtime, callers can keep
    passing ``"read"`` / ``"write"`` literals and gradually migrate to
    typed members without a breaking change.
    """

    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    CREATE = "create"
    DELETE = "delete"
    MANAGE = "manage"
