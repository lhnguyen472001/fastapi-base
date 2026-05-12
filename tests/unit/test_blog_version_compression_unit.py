"""Unit tests for the post-version compression helpers in ``apps.blog.utils``.

Covers FR-023 (compression at rest) and the contract that
:func:`compress_content_json` / :func:`decompress_content_json` form an
exact round-trip for ProseMirror-shaped payloads.
"""

from __future__ import annotations

import orjson
import pytest
import zstandard

from apps.blog.exceptions import PostVersionContentUnreadableError
from apps.blog.utils import compress_content_json, decompress_content_json

pytestmark = pytest.mark.unit


def _prosemirror_doc(paragraph_count: int, paragraph_text: str) -> dict:
    """Build a ProseMirror-shaped doc with N identical paragraphs."""
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": paragraph_text}],
            }
            for _ in range(paragraph_count)
        ],
    }


def test_round_trip_small_payload_is_identity() -> None:
    original = _prosemirror_doc(paragraph_count=3, paragraph_text="hello world")
    blob = compress_content_json(original)
    assert isinstance(blob, bytes)
    assert blob, "compressed blob must be non-empty"
    restored = decompress_content_json(blob)
    assert restored == original


def test_round_trip_preserves_unicode() -> None:
    original = _prosemirror_doc(paragraph_count=2, paragraph_text="café — schön — 日本語")
    blob = compress_content_json(original)
    restored = decompress_content_json(blob)
    assert restored == original


def test_repetitive_payload_compresses_to_less_than_forty_percent() -> None:
    """100 KB of repetitive ProseMirror JSON must compress to <= 40 % at level 3.

    Repetitive paragraphs are the realistic shape for a long-form blog
    post; this is the loose lower bound that justifies storing
    ``content_json_compressed`` instead of the raw payload (FR-023).
    """
    original = _prosemirror_doc(
        paragraph_count=500,
        paragraph_text="Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    )
    raw_size = len(orjson.dumps(original))
    assert raw_size > 50_000, "fixture should be sized like a real post"
    compressed = compress_content_json(original)
    ratio = len(compressed) / raw_size
    assert ratio < 0.40, f"expected compression to <0.40, got {ratio:.3f}"


def test_decompress_rejects_garbage_bytes() -> None:
    with pytest.raises(PostVersionContentUnreadableError):
        decompress_content_json(b"this-is-not-zstd")


def test_decompress_rejects_zstd_of_non_object() -> None:
    """A valid zstd frame whose decoded payload is not a JSON object is invalid input."""
    bogus = zstandard.ZstdCompressor().compress(b'"a string, not an object"')
    with pytest.raises(PostVersionContentUnreadableError):
        decompress_content_json(bogus)
