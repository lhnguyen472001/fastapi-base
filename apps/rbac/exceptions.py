"""Exceptions for the RBAC module."""

from __future__ import annotations

import enum

from apps.core.exceptions.errors import ConflictError, ForbiddenError, NotFoundError


class RBACErrorCodes(enum.StrEnum):
    """RBAC module error codes."""

    RBAC001 = "RBAC001"  # Group not found
    RBAC002 = "RBAC002"  # Role not found
    RBAC003 = "RBAC003"  # Permission not found
    RBAC004 = "RBAC004"  # Duplicate
    RBAC005 = "RBAC005"  # Access denied


class GroupNotFoundError(NotFoundError):
    code: str = RBACErrorCodes.RBAC001

    def __init__(self, *, message: str = "Group not found.") -> None:
        super().__init__(code=self.code, message=message)


class RoleNotFoundError(NotFoundError):
    code: str = RBACErrorCodes.RBAC002

    def __init__(self, *, message: str = "Role not found.") -> None:
        super().__init__(code=self.code, message=message)


class PermissionNotFoundError(NotFoundError):
    code: str = RBACErrorCodes.RBAC003

    def __init__(self, *, message: str = "Permission not found.") -> None:
        super().__init__(code=self.code, message=message)


class RBACConflictError(ConflictError):
    code: str = RBACErrorCodes.RBAC004

    def __init__(self, *, message: str = "RBAC entity already exists.") -> None:
        super().__init__(code=self.code, message=message)


class AccessDeniedError(ForbiddenError):
    code: str = RBACErrorCodes.RBAC005

    def __init__(self, *, message: str = "Access denied.") -> None:
        super().__init__(code=self.code, message=message)
