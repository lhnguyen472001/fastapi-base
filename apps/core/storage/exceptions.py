"""Storage-module exceptions.

These wrap the lowest-level boto3/aioboto3 errors so callers can react to
domain-meaningful failure modes (e.g. *object not found*) without having
to inspect botocore's :class:`ClientError` codes directly.
"""

from __future__ import annotations

import enum

from apps.core.exceptions.errors import InternalServerError, NotFoundError


class StorageErrorCodes(enum.StrEnum):
    """Stable error-code identifiers for the storage subsystem."""

    STORAGE001 = "STORAGE001"  # Generic storage failure
    STORAGE002 = "STORAGE002"  # Object not found in the bucket


class StorageError(InternalServerError):
    """Generic storage failure (network error, bucket misconfigured, etc.)."""

    code: str = StorageErrorCodes.STORAGE001

    def __init__(self, *, message: str = "Storage operation failed.") -> None:
        super().__init__(code=self.code, message=message)


class StorageObjectNotFoundError(NotFoundError):
    """Raised when a HEAD / GET against the bucket returns 404."""

    code: str = StorageErrorCodes.STORAGE002

    def __init__(self, *, message: str = "Storage object not found.") -> None:
        super().__init__(code=self.code, message=message)
