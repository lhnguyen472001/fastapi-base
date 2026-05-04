"""Unit tests for :mod:`apps.core.storage.s3`.

The aioboto3 S3 client is patched so these tests run without any network
or LocalStack dependency.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from apps.core.storage.exceptions import StorageError, StorageObjectNotFoundError
from apps.core.storage.s3 import S3Client
from apps.settings import StorageSettings


def _make_client(*, monkeypatch: pytest.MonkeyPatch, mock_s3: AsyncMock) -> S3Client:
    """Build an :class:`S3Client` whose ``_client`` returns a mocked async ctx."""
    client = S3Client(StorageSettings())
    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=mock_s3)
    ctx_manager.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(client, "_client", lambda: ctx_manager)
    return client


# ---------------------------------------------------------------------------
# generate_presigned_post
# ---------------------------------------------------------------------------


async def test_generate_presigned_post_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_post.return_value = {
        "url": "https://s3.example.com/bucket",
        "fields": {"Content-Type": "image/png", "key": "k"},
    }
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    payload = await client.generate_presigned_post(key="post/1.png", content_type="image/png")

    assert payload["url"] == "https://s3.example.com/bucket"
    assert payload["fields"]["Content-Type"] == "image/png"

    call_kwargs = mock_s3.generate_presigned_post.await_args.kwargs
    assert call_kwargs["Key"] == "post/1.png"
    assert call_kwargs["Bucket"] == "fastapi-base-blog"
    cond_types = {c[0] if isinstance(c, list) else next(iter(c.keys())) for c in call_kwargs["Conditions"]}
    assert "content-length-range" in cond_types
    assert "Content-Type" in cond_types


async def test_generate_presigned_post_wraps_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_post.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "boom"}}, "GeneratePresignedPost"
    )
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    with pytest.raises(StorageError):
        await client.generate_presigned_post(key="x", content_type="image/png")


# ---------------------------------------------------------------------------
# generate_presigned_get_url
# ---------------------------------------------------------------------------


async def test_generate_presigned_get_url_returns_string(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url.return_value = "https://signed.example.com/x?sig=abc"
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    url = await client.generate_presigned_get_url(key="x.png")

    assert url == "https://signed.example.com/x?sig=abc"
    args, kwargs = mock_s3.generate_presigned_url.call_args
    assert args[0] == "get_object"
    assert kwargs["Params"]["Key"] == "x.png"


# ---------------------------------------------------------------------------
# head_object
# ---------------------------------------------------------------------------


async def test_head_object_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.head_object.return_value = {"ContentLength": 1024, "ContentType": "image/png"}
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    meta: Any = await client.head_object(key="x.png")
    assert meta["ContentLength"] == 1024


async def test_head_object_raises_not_found_for_404(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    with pytest.raises(StorageObjectNotFoundError):
        await client.head_object(key="missing.png")


async def test_head_object_wraps_other_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "HeadObject")
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    with pytest.raises(StorageError):
        await client.head_object(key="x.png")


# ---------------------------------------------------------------------------
# delete_object
# ---------------------------------------------------------------------------


async def test_delete_object_calls_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    await client.delete_object(key="x.png")

    mock_s3.delete_object.assert_awaited_once()
    kwargs = mock_s3.delete_object.await_args.kwargs
    assert kwargs["Key"] == "x.png"
    assert kwargs["Bucket"] == "fastapi-base-blog"


async def test_delete_object_wraps_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_s3 = AsyncMock()
    mock_s3.delete_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObject"
    )
    client = _make_client(monkeypatch=monkeypatch, mock_s3=mock_s3)

    with pytest.raises(StorageError):
        await client.delete_object(key="x.png")


# ---------------------------------------------------------------------------
# Settings-driven config wiring
# ---------------------------------------------------------------------------


def test_client_kwargs_include_endpoint_url_for_localstack() -> None:
    client = S3Client(StorageSettings())
    kwargs = client._client_kwargs()
    assert kwargs["endpoint_url"] == "http://localhost:4566"
    assert kwargs["config"].s3["addressing_style"] == "path"


def test_client_kwargs_drop_endpoint_when_unset() -> None:
    client = S3Client(StorageSettings(s3_endpoint_url=None, use_path_style=False))
    kwargs = client._client_kwargs()
    assert "endpoint_url" not in kwargs
    assert kwargs["config"].s3["addressing_style"] == "auto"
