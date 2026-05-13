"""Unit tests for the large-content offload helpers in ``apps.blog.utils``.

Covers F-PERF-1: the Tiptap content pipeline runs on a worker thread via
``asyncio.to_thread`` when the input payload size is at or above the
configured threshold, and runs inline otherwise. Verifies the decision
helper ``_should_offload`` directly, and confirms the async wrappers
preserve byte-identical output regardless of which path they take.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import orjson
import pytest

from apps.blog.constants import LARGE_CONTENT_BYTES
from apps.blog.utils import (
    _should_offload,
    compress_content_json,
    compress_content_json_async,
    compute_content_artifacts,
    compute_content_artifacts_async,
    sanitize_html_async,
)
from apps.core.tiptap import sanitize_html

pytestmark = pytest.mark.unit


def _prosemirror_doc(paragraph_count: int, paragraph_text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": paragraph_text}]} for _ in range(paragraph_count)
        ],
    }


# ---------------------------------------------------------------------------
# _should_offload — pure decision helper
# ---------------------------------------------------------------------------


def test_should_offload_returns_false_for_zero_bytes() -> None:
    assert _should_offload(0, threshold_bytes=LARGE_CONTENT_BYTES) is False


def test_should_offload_returns_false_for_negative_size() -> None:
    # Defensive: callers should never pass negative sizes, but the helper
    # must not panic and must return False (no offload) just in case.
    assert _should_offload(-1, threshold_bytes=LARGE_CONTENT_BYTES) is False


def test_should_offload_returns_false_below_threshold() -> None:
    assert _should_offload(LARGE_CONTENT_BYTES - 1, threshold_bytes=LARGE_CONTENT_BYTES) is False


def test_should_offload_returns_true_at_threshold_boundary() -> None:
    # spec.md edge case: payload exactly at the threshold takes the offload
    # path (the >= side). Pin that behavior here.
    assert _should_offload(LARGE_CONTENT_BYTES, threshold_bytes=LARGE_CONTENT_BYTES) is True


def test_should_offload_returns_true_above_threshold() -> None:
    assert _should_offload(LARGE_CONTENT_BYTES + 1, threshold_bytes=LARGE_CONTENT_BYTES) is True


def test_should_offload_uses_custom_threshold() -> None:
    assert _should_offload(100, threshold_bytes=50) is True
    assert _should_offload(100, threshold_bytes=200) is False


# ---------------------------------------------------------------------------
# compute_content_artifacts_async — gating + identity
# ---------------------------------------------------------------------------


def test_compute_async_runs_inline_for_small_payload() -> None:
    """Small payload: asyncio.to_thread must NOT be called."""
    doc = _prosemirror_doc(paragraph_count=1, paragraph_text="hello")
    payload_size = len(orjson.dumps(doc))
    assert payload_size < LARGE_CONTENT_BYTES

    with patch("apps.blog.utils.asyncio.to_thread") as mock_to_thread:
        result = asyncio.run(compute_content_artifacts_async(doc))

    assert mock_to_thread.call_count == 0
    assert result == compute_content_artifacts(doc)


def test_compute_async_offloads_for_large_payload() -> None:
    """Payload >= threshold: asyncio.to_thread MUST be called exactly once."""
    doc = _prosemirror_doc(paragraph_count=10, paragraph_text="lorem ipsum dolor sit amet")
    payload_size = len(orjson.dumps(doc))
    threshold = max(1, payload_size - 1)

    async def _to_thread_passthrough(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    with patch(
        "apps.blog.utils.asyncio.to_thread",
        side_effect=_to_thread_passthrough,
    ) as mock_to_thread:
        result = asyncio.run(compute_content_artifacts_async(doc, threshold_bytes=threshold))

    assert mock_to_thread.call_count == 1
    assert result == compute_content_artifacts(doc)


def test_compute_async_empty_doc_takes_inline_path_at_default_threshold() -> None:
    """An empty doc is ~27 bytes — well below the default threshold, so inline."""
    empty = {"type": "doc", "content": []}
    assert len(orjson.dumps(empty)) < LARGE_CONTENT_BYTES  # sanity

    with patch("apps.blog.utils.asyncio.to_thread") as mock_to_thread:
        result = asyncio.run(compute_content_artifacts_async(empty))

    assert mock_to_thread.call_count == 0
    assert result == compute_content_artifacts(empty)


# ---------------------------------------------------------------------------
# compress_content_json_async — gating + identity
# ---------------------------------------------------------------------------


def test_compress_async_runs_inline_for_small_payload() -> None:
    doc = _prosemirror_doc(paragraph_count=1, paragraph_text="hi")

    with patch("apps.blog.utils.asyncio.to_thread") as mock_to_thread:
        result = asyncio.run(compress_content_json_async(doc))

    assert mock_to_thread.call_count == 0
    assert result == compress_content_json(doc)


def test_compress_async_offloads_for_large_payload() -> None:
    doc = _prosemirror_doc(paragraph_count=10, paragraph_text="lorem ipsum dolor sit amet")
    payload_size = len(orjson.dumps(doc))
    threshold = max(1, payload_size - 1)

    async def _to_thread_passthrough(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    with patch(
        "apps.blog.utils.asyncio.to_thread",
        side_effect=_to_thread_passthrough,
    ) as mock_to_thread:
        result = asyncio.run(compress_content_json_async(doc, threshold_bytes=threshold))

    assert mock_to_thread.call_count == 1
    assert result == compress_content_json(doc)


# ---------------------------------------------------------------------------
# sanitize_html_async — gating + identity
# ---------------------------------------------------------------------------


def test_sanitize_html_async_runs_inline_for_small_html() -> None:
    html = "<p>hello</p>"

    with patch("apps.blog.utils.asyncio.to_thread") as mock_to_thread:
        result = asyncio.run(sanitize_html_async(html))

    assert mock_to_thread.call_count == 0
    assert result == sanitize_html(html)


def test_sanitize_html_async_offloads_for_large_html() -> None:
    html = "<p>" + ("hello world " * 200) + "</p>"
    threshold = max(1, len(html.encode("utf-8")) - 1)

    async def _to_thread_passthrough(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    with patch(
        "apps.blog.utils.asyncio.to_thread",
        side_effect=_to_thread_passthrough,
    ) as mock_to_thread:
        result = asyncio.run(sanitize_html_async(html, threshold_bytes=threshold))

    assert mock_to_thread.call_count == 1
    assert result == sanitize_html(html)
