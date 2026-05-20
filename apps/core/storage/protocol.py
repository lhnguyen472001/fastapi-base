"""Object-storage adapter protocol.

Captures the minimal async surface every storage backend must provide
so application code depends on this contract rather than the concrete
:class:`apps.core.storage.s3.S3Client`. Swapping S3 for another
provider (GCS, Azure Blob, or a test stub) is then a matter of writing
a class that satisfies this protocol — no service or DI-container
changes beyond rebinding.

Re-exported from :mod:`apps.core.storage` so consumers can write
``from apps.core.storage import StorageAdapterProtocol``, mirroring the
``apps/core/database/repository/protocol.py`` pattern.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

__all__ = ["StorageAdapterProtocol"]


class StorageAdapterProtocol(Protocol):
    """Object-storage surface every adapter must satisfy.

    Covers only what the blog feature actually needs — direct-to-S3
    browser uploads, short-lived GET URLs, HEAD for upload
    confirmation, and admin delete. Provider-specific features
    (multipart, versioning, object-lock) are intentionally absent so
    we don't accidentally couple application code to S3 semantics.
    """

    async def generate_presigned_post(
        self,
        *,
        key: str,
        content_type: str,
        max_bytes: int | None = None,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Return a presigned-POST payload (``{"url": ..., "fields": {...}}``).

        The browser feeds the result into a multipart form to upload
        directly to S3 without proxying through the application.
        Implementations must enforce the content type and an upload
        size cap via signed conditions so callers cannot exceed
        ``max_bytes``.
        """
        ...

    async def generate_presigned_get_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> str:
        """Return a short-lived GET URL for the stored object."""
        ...

    async def head_object(
        self,
        *,
        key: str,
        bucket: str | None = None,
    ) -> Mapping[str, Any]:
        """HEAD an object; raise :class:`StorageObjectNotFoundError` on 404."""
        ...

    async def delete_object(
        self,
        *,
        key: str,
        bucket: str | None = None,
    ) -> None:
        """Idempotent delete; missing key is treated as success."""
        ...
