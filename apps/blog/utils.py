"""Tiptap content pipeline helpers shared across post services.

The pipeline runs in two paths:

* The cheap autosave path (text extract + word count + JSON hash) lives
  inline in :meth:`apps.blog.services.PostService.autosave` so it can
  short-circuit before touching Postgres.
* The full path (text + sanitized HTML + hash + word count + reading
  minutes) lives in :func:`compute_content_artifacts` below and runs at
  create / update / publish / flush_one time.

zstd compression for ``post_versions.content_json_compressed`` and the
line-based diff used by ``PostVersionService.compare`` also live here
so every post-content helper stays in one module.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import math
import uuid
from typing import Any

import orjson
import zstandard

from apps.blog.constants import (
    BLOG_SLUG_PATTERN,
    LARGE_CONTENT_BYTES,
    MIN_PUBLISH_BODY_CHARS,
    POST_RENDER_CACHE_KEY_PREFIX,
    POST_RENDER_CACHE_TTL_SECONDS,
    POST_VERSION_COMPRESSION_LEVEL,
    WORDS_PER_MINUTE,
)
from apps.blog.exceptions import (
    PostPublishContentError,
    PostVersionContentUnreadableError,
    PostVersionDiffTooLargeError,
)
from apps.blog.models import Post
from apps.blog.schemas import CompareVersionsHunk, CompareVersionsResult
from apps.core.database.utils import slugify
from apps.core.redis.cache import CacheManager
from apps.core.tiptap import extract_text, render_html, sanitize_html


def normalize_slug(slug: str) -> str:
    """Lowercase + strip; reject if it doesn't match the blog slug pattern."""
    candidate = slug.strip().lower()
    if BLOG_SLUG_PATTERN.fullmatch(candidate) is None:
        # Slug came from the schema's min/max length validation but the regex
        # didn't match — typically uppercase or punctuation. Re-slugify and try
        # again so user-supplied "Hello World!" becomes "hello-world".
        candidate = slugify(candidate)
    return candidate


def ensure_publish_ready(post: Post) -> None:
    """Raise :class:`PostPublishContentError` if the post is not ready.

    Readiness rules (kept minimal on purpose):

    * ``title`` must have at least one non-whitespace char.
    * ``content_text`` (the FTS plaintext extract) must be at least
      :data:`MIN_PUBLISH_BODY_CHARS` non-whitespace chars long. We use
      ``content_text`` rather than counting the JSON because it
      excludes Tiptap markup, image alt text, etc.
    """
    if not post.title or not post.title.strip():
        raise PostPublishContentError(message="Post title is required to publish.")

    content_text = post.content.content_text if post.content is not None else ""
    if len(content_text.strip()) < MIN_PUBLISH_BODY_CHARS:
        raise PostPublishContentError(
            message=(f"Post body must be at least {MIN_PUBLISH_BODY_CHARS} characters to publish."),
        )


def compute_content_artifacts(content_json: dict[str, Any]) -> tuple[str, str, str, int, int]:
    """Run the full Tiptap pipeline. Returns ``(text, html, hash, words, minutes)``."""
    text = extract_text(content_json)
    html = sanitize_html(render_html(content_json))
    canonical = json.dumps(content_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    word_count = len(text.split()) if text else 0
    reading_minutes = max(1, math.ceil(word_count / WORDS_PER_MINUTE)) if word_count > 0 else 0
    return text, html, digest, word_count, reading_minutes


def compress_content_json(payload: dict[str, Any]) -> bytes:
    """Serialize ``payload`` to compact JSON and zstd-compress it.

    Used by the post-version save path to keep
    ``post_versions.content_json_compressed`` small. orjson produces a
    compact, deterministic byte string and zstd at level
    :data:`POST_VERSION_COMPRESSION_LEVEL` typically reduces a ProseMirror
    payload to under 40% of the raw size at < 5 ms on a modern x86 core.
    """
    serialized = orjson.dumps(payload)
    compressor = zstandard.ZstdCompressor(level=POST_VERSION_COMPRESSION_LEVEL)
    return compressor.compress(serialized)


def _should_offload(payload_bytes: int, *, threshold_bytes: int = LARGE_CONTENT_BYTES) -> bool:
    """Decide whether the Tiptap pipeline should run on a worker thread.

    Returns ``True`` when ``payload_bytes`` is at or above ``threshold_bytes``
    (and strictly positive). Below the threshold the synchronous pipeline
    runs inline, avoiding the ~50 µs thread hand-off cost. The threshold
    boundary is inclusive on the offload side so equality is deterministic.
    """
    if payload_bytes <= 0:
        return False
    return payload_bytes >= threshold_bytes


async def compute_content_artifacts_async(
    content_json: dict[str, Any],
    *,
    threshold_bytes: int = LARGE_CONTENT_BYTES,
) -> tuple[str, str, str, int, int]:
    """Async wrapper around :func:`compute_content_artifacts`.

    Runs the pipeline on a worker thread via ``asyncio.to_thread`` when
    the serialized payload is at or above ``threshold_bytes`` so the event
    loop stays free for other concurrent requests; otherwise runs inline.
    """
    payload = orjson.dumps(content_json)
    if _should_offload(len(payload), threshold_bytes=threshold_bytes):
        return await asyncio.to_thread(compute_content_artifacts, content_json)
    return compute_content_artifacts(content_json)


async def compress_content_json_async(
    payload: dict[str, Any],
    *,
    threshold_bytes: int = LARGE_CONTENT_BYTES,
) -> bytes:
    """Async wrapper around :func:`compress_content_json` with size gating."""
    raw = orjson.dumps(payload)
    if _should_offload(len(raw), threshold_bytes=threshold_bytes):
        return await asyncio.to_thread(compress_content_json, payload)
    return compress_content_json(payload)


async def sanitize_html_async(
    html: str,
    *,
    threshold_bytes: int = LARGE_CONTENT_BYTES,
) -> str:
    """Async wrapper around :func:`sanitize_html` with size gating.

    Size is measured on the UTF-8 byte length of ``html``.
    """
    if _should_offload(len(html.encode("utf-8")), threshold_bytes=threshold_bytes):
        return await asyncio.to_thread(sanitize_html, html)
    return sanitize_html(html)


def _render_cache_key(post_id: uuid.UUID, content_hash: str) -> str:
    """Cache-key shape for a single (post, content_hash) rendered HTML entry."""
    return f"{POST_RENDER_CACHE_KEY_PREFIX}:{post_id}:{content_hash}"


async def render_html_cached(
    cache: CacheManager,
    *,
    post_id: uuid.UUID,
    content_json: dict[str, Any],
    content_hash: str,
) -> str:
    """Render + sanitize Tiptap content with a hash-keyed Redis cache.

    Cache key: ``blog:render:v1:<post_id>:<content_hash>``. Every
    distinct ``content_hash`` produces its own entry, so a keystroke
    on a draft naturally rolls to a fresh key without explicit
    invalidation. Entries age out after
    :data:`POST_RENDER_CACHE_TTL_SECONDS` of inactivity.

    On a cache miss the function falls through to the standard
    ``sanitize_html(render_html(content_json))`` pipeline (offloaded to
    a worker thread above :data:`LARGE_CONTENT_BYTES`) and stores the
    result. With Redis disabled (``cache.redis is None``) every call
    is a miss-and-render — same cost as the un-cached path.

    Args:
        cache: The shared :class:`CacheManager` (typically
            ``self.cache`` on a service).
        post_id: The post owning this rendered HTML; included in the
            key so :func:`invalidate_render_cache_for_post` can drop
            every cached render for a single post on persisted update.
        content_json: The ProseMirror document to render.
        content_hash: SHA-256 hex digest of the canonical-JSON
            serialization of ``content_json`` — already computed by
            :func:`compute_content_artifacts`.

    Returns:
        Sanitized HTML string, byte-identical to what the un-cached
        pipeline produces.
    """
    key = _render_cache_key(post_id, content_hash)
    cached = await cache.get(key)
    if cached is not None:
        return cached
    html = await sanitize_html_async(render_html(content_json))
    await cache.set(key, html, ttl=POST_RENDER_CACHE_TTL_SECONDS)
    return html


async def invalidate_render_cache_for_post(
    cache: CacheManager,
    *,
    post_id: uuid.UUID,
) -> int:
    """Drop every cached render for ``post_id``.

    Called from :meth:`PostService.update` so a persisted edit forces
    the next fetch to re-render from the new authoritative content.
    Returns the number of keys actually deleted (0 when Redis is off
    or no cached renders existed).
    """
    return await cache.invalidate_pattern(f"{POST_RENDER_CACHE_KEY_PREFIX}:{post_id}:*")


def decompress_content_json(blob: bytes) -> dict[str, Any]:
    """Inverse of :func:`compress_content_json`.

    Raises:
        PostVersionContentUnreadableError: when the bytes are not a valid
            zstd frame or the decoded payload is not a JSON object.
    """
    try:
        decompressor = zstandard.ZstdDecompressor()
        raw = decompressor.decompress(blob)
        decoded = orjson.loads(raw)
    except (zstandard.ZstdError, orjson.JSONDecodeError, ValueError) as exc:
        raise PostVersionContentUnreadableError(
            message=f"Cannot decode post-version payload: {exc.__class__.__name__}",
        ) from exc
    if not isinstance(decoded, dict):
        raise PostVersionContentUnreadableError(
            message="Post-version payload is not a JSON object.",
        )
    return decoded


def diff_versions(
    *,
    post_id: uuid.UUID,
    from_version: int,
    from_title: str,
    from_text: str,
    to_version: int,
    to_title: str,
    to_text: str,
    max_bytes: int,
) -> CompareVersionsResult:
    """Return a structured line diff from ``from_text`` to ``to_text``.

    Computes hunks via :class:`difflib.SequenceMatcher` opcodes over the
    *plaintext* extraction (``content_text``) of each version — diffing
    structured ProseMirror docs is out of scope for v1.

    The diff is symmetric: ``diff_versions(a, b)`` followed by
    ``diff_versions(b, a)`` swaps every ``added`` / ``removed`` op,
    which is what an editor showing a "swap from/to" toggle needs.

    Args:
        post_id: The post both versions belong to (echoed in the result).
        from_version: Numeric version on the source side.
        from_title: Title of the source version (frozen at save time).
        from_text: Plain-text body of the source version.
        to_version: Numeric version on the target side.
        to_title: Title of the target version.
        to_text: Plain-text body of the target version.
        max_bytes: Hard cap on combined UTF-8 byte size of the two
            payloads. Over the cap raises
            :class:`PostVersionDiffTooLargeError` (POSTV005 / 413).

    Returns:
        :class:`CompareVersionsResult` with one hunk per line — every
        line of either side appears exactly once, tagged ``added``,
        ``removed``, or ``context``.

    Raises:
        PostVersionDiffTooLargeError: combined input exceeds ``max_bytes``.
    """
    _enforce_diff_size_cap(from_text, to_text, max_bytes=max_bytes)

    from_lines = from_text.splitlines()
    to_lines = to_text.splitlines()

    hunks = _build_diff_hunks(from_lines, to_lines)
    return CompareVersionsResult(
        post_id=post_id,
        from_version=from_version,
        to_version=to_version,
        title_changed=from_title != to_title,
        from_title=from_title,
        to_title=to_title,
        hunks=hunks,
    )


def _enforce_diff_size_cap(from_text: str, to_text: str, *, max_bytes: int) -> None:
    """Reject inputs whose combined UTF-8 size exceeds ``max_bytes``."""
    combined = len(from_text.encode("utf-8")) + len(to_text.encode("utf-8"))
    if combined > max_bytes:
        raise PostVersionDiffTooLargeError(
            message=f"Combined version content is {combined} bytes; cap is {max_bytes} bytes.",
        )


def _build_diff_hunks(from_lines: list[str], to_lines: list[str]) -> list[CompareVersionsHunk]:
    """Convert SequenceMatcher opcodes into a flat list of hunks.

    Each output hunk represents exactly one line. ``op='context'``
    populates both ``from_line_no`` and ``to_line_no``; ``op='removed'``
    leaves ``to_line_no=None``; ``op='added'`` leaves
    ``from_line_no=None``. Line numbers are 1-based to match what an
    editor diff UI typically displays.
    """
    matcher = difflib.SequenceMatcher(a=from_lines, b=to_lines, autojunk=False)
    hunks: list[CompareVersionsHunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset, line in enumerate(from_lines[i1:i2]):
                hunks.append(
                    CompareVersionsHunk(
                        op="context",
                        line=line,
                        from_line_no=i1 + offset + 1,
                        to_line_no=j1 + offset + 1,
                    ),
                )
        elif tag == "delete":
            for offset, line in enumerate(from_lines[i1:i2]):
                hunks.append(
                    CompareVersionsHunk(
                        op="removed",
                        line=line,
                        from_line_no=i1 + offset + 1,
                        to_line_no=None,
                    ),
                )
        elif tag == "insert":
            for offset, line in enumerate(to_lines[j1:j2]):
                hunks.append(
                    CompareVersionsHunk(
                        op="added",
                        line=line,
                        from_line_no=None,
                        to_line_no=j1 + offset + 1,
                    ),
                )
        elif tag == "replace":
            # Emit removed-then-added so the order in the response matches
            # what a textual reader expects (delete old, then introduce new).
            for offset, line in enumerate(from_lines[i1:i2]):
                hunks.append(
                    CompareVersionsHunk(
                        op="removed",
                        line=line,
                        from_line_no=i1 + offset + 1,
                        to_line_no=None,
                    ),
                )
            for offset, line in enumerate(to_lines[j1:j2]):
                hunks.append(
                    CompareVersionsHunk(
                        op="added",
                        line=line,
                        from_line_no=None,
                        to_line_no=j1 + offset + 1,
                    ),
                )
    return hunks
