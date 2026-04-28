"""Shared helpers for the RBAC service package.

Subject / object token formatters used by both the write services and the
read-side :class:`AccessService`. Kept private (underscore-prefixed) because
they are implementation details of the Casbin mapping — callers should go
through the service methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.rbac.constants import OBJECT_TOKEN_SEPARATOR, ROLE_PREFIX, USER_PREFIX

if TYPE_CHECKING:
    import uuid


def role_sub(role_id: int) -> str:
    return f"{ROLE_PREFIX}{role_id}"


def user_sub(user_id: uuid.UUID) -> str:
    return f"{USER_PREFIX}{user_id}"


def instance_obj(resource: str, object_id: str) -> str:
    """Casbin object token for an instance-level grant."""
    return f"{resource}{OBJECT_TOKEN_SEPARATOR}{object_id}"


def read_attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
