"""Workspace module exceptions.

Each error code is a stable, greppable identifier the UI / clients can map
to localized copy. Status codes piggy-back on the generic
:class:`apps.core.exceptions.errors` subclasses (404 / 409 / 403 / 400).
"""

from __future__ import annotations

import enum

from apps.core.exceptions.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)


class WorkspaceErrorCodes(enum.StrEnum):
    """Stable error-code identifiers for the workspace module."""

    WS001 = "WS001"  # Workspace not found
    WS002 = "WS002"  # Workspace slug already exists
    WS003 = "WS003"  # Workspace slug is reserved
    WS004 = "WS004"  # Workspace slug format invalid
    WS005 = "WS005"  # Workspace member not found
    WS006 = "WS006"  # Workspace member already exists
    WS007 = "WS007"  # Workspace member limit exceeded
    WS008 = "WS008"  # Workspace must retain at least one owner
    WS009 = "WS009"  # Caller is not a member of the workspace
    WS010 = "WS010"  # Caller's role is insufficient for the requested action


class WorkspaceNotFoundError(NotFoundError):
    """Raised when a workspace cannot be resolved (or the caller has no access).

    The same error is intentionally raised for true 404 and for cross-workspace
    access attempts so existence cannot be probed by unauthorized callers.
    """

    code: str = WorkspaceErrorCodes.WS001

    def __init__(self, *, message: str = "Workspace not found.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceSlugConflictError(ConflictError):
    """Raised when the requested workspace slug is already taken."""

    code: str = WorkspaceErrorCodes.WS002

    def __init__(self, *, message: str = "Workspace slug already exists.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceSlugReservedError(BadRequestError):
    """Raised when the requested workspace slug is on the reserved list."""

    code: str = WorkspaceErrorCodes.WS003

    def __init__(self, *, message: str = "Workspace slug is reserved.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceSlugInvalidError(BadRequestError):
    """Raised when the requested workspace slug fails the format pattern."""

    code: str = WorkspaceErrorCodes.WS004

    def __init__(self, *, message: str = "Workspace slug format is invalid.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceMemberNotFoundError(NotFoundError):
    """Raised when a workspace member row cannot be located."""

    code: str = WorkspaceErrorCodes.WS005

    def __init__(self, *, message: str = "Workspace member not found.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceMemberAlreadyExistsError(ConflictError):
    """Raised when adding a user that already has a membership row."""

    code: str = WorkspaceErrorCodes.WS006

    def __init__(self, *, message: str = "Workspace member already exists.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceMemberLimitExceededError(ConflictError):
    """Raised when the workspace already holds the maximum number of members."""

    code: str = WorkspaceErrorCodes.WS007

    def __init__(self, *, message: str = "Workspace member limit exceeded.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceLastOwnerError(ConflictError):
    """Raised when removing or demoting the last owner of a workspace.

    Every workspace must have at least one ``owner`` member; otherwise nobody
    could re-grant ownership without a system administrator's intervention.
    """

    code: str = WorkspaceErrorCodes.WS008

    def __init__(self, *, message: str = "Workspace must retain at least one owner.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceNotMemberError(ForbiddenError):
    """Raised when the authenticated caller is not a member of the workspace."""

    code: str = WorkspaceErrorCodes.WS009

    def __init__(self, *, message: str = "Caller is not a member of the workspace.") -> None:
        super().__init__(code=self.code, message=message)


class WorkspaceRoleForbiddenError(ForbiddenError):
    """Raised when the caller's role is too weak for the requested action."""

    code: str = WorkspaceErrorCodes.WS010

    def __init__(self, *, message: str = "Caller's role is insufficient for this action.") -> None:
        super().__init__(code=self.code, message=message)
