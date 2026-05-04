"""Async S3 client built on ``aioboto3``.

A thin wrapper that exposes only the operations the blog feature needs:

* :meth:`S3Client.generate_presigned_post` — direct-to-S3 browser upload.
* :meth:`S3Client.generate_presigned_get_url` — short-lived download URL.
* :meth:`S3Client.head_object` — verify an upload landed (used by the
  ``/media/confirm`` endpoint after the browser PUT).
* :meth:`S3Client.delete_object` — admin / cleanup path.

Type hints come from ``types-aiobotocore-s3`` so the client surface is
fully checkable without importing the runtime stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError
from loguru import logger

from apps.core.storage.exceptions import StorageError, StorageObjectNotFoundError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from types_aiobotocore_s3.client import S3Client as AioS3Client

    from apps.settings import StorageSettings

# botocore "404"-equivalent codes returned by HEAD on a missing object.
_NOT_FOUND_CODES: frozenset[str] = frozenset({"404", "NoSuchKey", "NotFound"})


class S3Client:
    """Async, settings-driven wrapper around ``aioboto3``.

    The wrapper does not hold a long-lived client; each call opens an
    aioboto3 client context manager (cheap — connections are pooled by
    aiohttp under the hood) and returns the result. This keeps the
    blast radius of a stale connection limited to a single operation.
    """

    def __init__(self, settings: StorageSettings) -> None:
        self._settings = settings
        self._session = aioboto3.Session(
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name=settings.s3_region,
        )

    # ------------------------------------------------------------------
    # client factory (pluggable for tests)
    # ------------------------------------------------------------------

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if self._settings.use_path_style else "auto"},
            ),
        }
        if self._settings.s3_endpoint_url:
            kwargs["endpoint_url"] = self._settings.s3_endpoint_url
        return kwargs

    def _client(self) -> Any:
        """Return an aioboto3 S3 client async context manager.

        Returns ``Any`` because aioboto3's runtime client is dynamically
        constructed; type-checkers should rely on the ``AioS3Client`` cast
        inside each method instead.
        """
        return self._session.client("s3", **self._client_kwargs())

    # ------------------------------------------------------------------
    # operations
    # ------------------------------------------------------------------

    async def generate_presigned_post(
        self,
        *,
        key: str,
        content_type: str,
        max_bytes: int | None = None,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Build a presigned-POST payload the browser can use to upload directly.

        Returns a ``{"url": ..., "fields": {...}}`` dict ready for the
        client to feed into a multipart form. The conditions enforce the
        content type and (optionally) a server-side size cap.
        """
        bucket_name = bucket or self._settings.s3_bucket
        size_cap = max_bytes if max_bytes is not None else self._settings.max_upload_bytes
        ttl = expires_in if expires_in is not None else self._settings.presign_expires_seconds

        conditions: list[Any] = [
            ["content-length-range", 1, size_cap],
            {"Content-Type": content_type},
        ]
        fields: dict[str, str] = {"Content-Type": content_type}

        try:
            async with self._client() as client_ctx:
                client: AioS3Client = client_ctx
                payload = await client.generate_presigned_post(
                    Bucket=bucket_name,
                    Key=key,
                    Fields=fields,
                    Conditions=conditions,
                    ExpiresIn=ttl,
                )
        except ClientError as exc:
            logger.error(f"S3Client - generate_presigned_post - failed for key '{key}': {exc}")
            raise StorageError(message=f"Failed to presign upload for key '{key}'.") from exc
        return dict(payload)

    async def generate_presigned_get_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        bucket: str | None = None,
    ) -> str:
        """Build a short-lived GET URL for a stored object."""
        bucket_name = bucket or self._settings.s3_bucket
        ttl = expires_in if expires_in is not None else self._settings.presign_expires_seconds
        try:
            async with self._client() as client_ctx:
                client: AioS3Client = client_ctx
                return await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket_name, "Key": key},
                    ExpiresIn=ttl,
                )
        except ClientError as exc:
            logger.error(f"S3Client - generate_presigned_get_url - failed for key '{key}': {exc}")
            raise StorageError(message=f"Failed to presign GET for key '{key}'.") from exc

    async def head_object(
        self,
        *,
        key: str,
        bucket: str | None = None,
    ) -> Mapping[str, Any]:
        """HEAD an object; raise :class:`StorageObjectNotFoundError` on 404."""
        bucket_name = bucket or self._settings.s3_bucket
        try:
            async with self._client() as client_ctx:
                client: AioS3Client = client_ctx
                return await client.head_object(Bucket=bucket_name, Key=key)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in _NOT_FOUND_CODES:
                raise StorageObjectNotFoundError(
                    message=f"Object '{key}' not found in bucket '{bucket_name}'.",
                ) from exc
            logger.error(f"S3Client - head_object - failed for key '{key}': {exc}")
            raise StorageError(message=f"Failed to HEAD object '{key}'.") from exc

    async def delete_object(
        self,
        *,
        key: str,
        bucket: str | None = None,
    ) -> None:
        """Delete an object. Idempotent — missing key is treated as success."""
        bucket_name = bucket or self._settings.s3_bucket
        try:
            async with self._client() as client_ctx:
                client: AioS3Client = client_ctx
                await client.delete_object(Bucket=bucket_name, Key=key)
        except ClientError as exc:
            logger.error(f"S3Client - delete_object - failed for key '{key}': {exc}")
            raise StorageError(message=f"Failed to delete object '{key}'.") from exc
