"""Unit tests for MED-2: hash-keyed render cache.

Pins the contract:

* ``render_html_cached`` returns identical HTML to the un-cached
  pipeline, byte-for-byte.
* Cache MISS path renders once and stores under
  ``<prefix>:<post_id>:<content_hash>``.
* Cache HIT path returns the stored value without re-rendering.
* Different ``content_hash`` produces a different key (a keystroke
  rolls naturally to a fresh entry).
* ``invalidate_render_cache_for_post`` clears every entry for one
  post and leaves entries for sibling posts intact.
* With Redis off (``cache.redis is None``) the function still works
  — every call is a miss-and-render, no exceptions.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.blog.constants import (
    POST_RENDER_CACHE_KEY_PREFIX,
    POST_RENDER_CACHE_TTL_SECONDS,
)
from apps.blog.utils import (
    invalidate_render_cache_for_post,
    render_html_cached,
)
from apps.core.redis.cache import CacheManager
from apps.core.tiptap import render_html, sanitize_html


class _FakeCacheManager:
    """In-memory stand-in for :class:`CacheManager`.

    Implements the surface the cache helpers actually use: ``get``,
    ``set`` (TTL is recorded but never enforced — tests don't simulate
    time), and ``invalidate_pattern`` (glob-style ``*`` suffix only,
    which is all the helpers ever ask for).
    """

    def __init__(self, *, redis_enabled: bool = True) -> None:
        # ``redis is None`` is the documented short-circuit that the
        # cache helpers honour; reproducing that flag on the fake lets
        # us assert the degraded path without spinning up Redis.
        self.redis: object | None = object() if redis_enabled else None
        self.store: dict[str, Any] = {}
        self.recorded_ttls: dict[str, int] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> Any:
        self.get_calls += 1
        if self.redis is None:
            return None
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        self.set_calls += 1
        if self.redis is None:
            return False
        self.store[key] = value
        self.recorded_ttls[key] = ttl
        return True

    async def invalidate_pattern(self, pattern: str) -> int:
        if self.redis is None:
            return 0
        # Helpers always pass ``<literal>:*`` — translate to a prefix match.
        assert pattern.endswith("*"), f"unexpected pattern shape: {pattern!r}"
        prefix = pattern[:-1]
        keys = [k for k in self.store if k.startswith(prefix)]
        for k in keys:
            del self.store[k]
            self.recorded_ttls.pop(k, None)
        return len(keys)


def _sample_doc() -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello, world!"}]},
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Section"}],
            },
        ],
    }


@pytest.mark.asyncio
async def test_cache_hit_does_not_re_render() -> None:
    """Second call with same args must return the stored value, no second render."""
    cache: CacheManager = _FakeCacheManager()  # type: ignore[assignment]
    post_id = uuid.uuid4()
    doc = _sample_doc()
    content_hash = "abc123"

    html_first = await render_html_cached(
        cache, post_id=post_id, content_json=doc, content_hash=content_hash
    )
    # Direct un-cached pipeline reference; the cache must produce the same bytes.
    expected = sanitize_html(render_html(doc))
    assert html_first == expected

    # Mutate the underlying doc so a re-render would produce different output;
    # the cache must still serve the original.
    doc["content"].append({"type": "paragraph", "content": [{"type": "text", "text": "INJECTED"}]})

    html_second = await render_html_cached(
        cache, post_id=post_id, content_json=doc, content_hash=content_hash
    )
    assert html_second == html_first
    assert "INJECTED" not in html_second


@pytest.mark.asyncio
async def test_cache_key_includes_post_id_and_content_hash() -> None:
    cache = _FakeCacheManager()
    post_id = uuid.uuid4()
    content_hash = "deadbeef"

    await render_html_cached(
        cache,  # type: ignore[arg-type]
        post_id=post_id,
        content_json=_sample_doc(),
        content_hash=content_hash,
    )

    expected_key = f"{POST_RENDER_CACHE_KEY_PREFIX}:{post_id}:{content_hash}"
    assert expected_key in cache.store
    # TTL is the project-wide constant — verify no per-call drift.
    assert cache.recorded_ttls[expected_key] == POST_RENDER_CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_different_content_hash_rolls_to_fresh_entry() -> None:
    """Keystroke = new content_hash = new key. Old entry survives until
    invalidation or TTL expiry; new entry holds the fresh render."""
    cache = _FakeCacheManager()
    post_id = uuid.uuid4()
    doc_v1 = _sample_doc()
    doc_v2 = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "edited"}]}],
    }

    html_v1 = await render_html_cached(
        cache,  # type: ignore[arg-type]
        post_id=post_id,
        content_json=doc_v1,
        content_hash="hash-v1",
    )
    html_v2 = await render_html_cached(
        cache,  # type: ignore[arg-type]
        post_id=post_id,
        content_json=doc_v2,
        content_hash="hash-v2",
    )

    assert html_v1 != html_v2
    assert len(cache.store) == 2
    assert any(k.endswith(":hash-v1") for k in cache.store)
    assert any(k.endswith(":hash-v2") for k in cache.store)


@pytest.mark.asyncio
async def test_invalidate_only_drops_target_post_entries() -> None:
    """Invalidation for post A must NOT drop cached renders for post B."""
    cache = _FakeCacheManager()
    post_a = uuid.uuid4()
    post_b = uuid.uuid4()
    doc = _sample_doc()

    await render_html_cached(cache, post_id=post_a, content_json=doc, content_hash="a")  # type: ignore[arg-type]
    await render_html_cached(cache, post_id=post_a, content_json=doc, content_hash="aa")  # type: ignore[arg-type]
    await render_html_cached(cache, post_id=post_b, content_json=doc, content_hash="b")  # type: ignore[arg-type]
    assert len(cache.store) == 3

    deleted = await invalidate_render_cache_for_post(cache, post_id=post_a)  # type: ignore[arg-type]

    assert deleted == 2
    remaining_keys = list(cache.store)
    assert len(remaining_keys) == 1
    assert str(post_b) in remaining_keys[0]


@pytest.mark.asyncio
async def test_redis_off_falls_through_to_uncached_render() -> None:
    """With Redis disabled the helper must still return correct HTML and
    must not raise — it just becomes the un-cached pipeline."""
    cache = _FakeCacheManager(redis_enabled=False)
    doc = _sample_doc()
    expected = sanitize_html(render_html(doc))

    html = await render_html_cached(
        cache,  # type: ignore[arg-type]
        post_id=uuid.uuid4(),
        content_json=doc,
        content_hash="any",
    )

    assert html == expected
    assert cache.store == {}


@pytest.mark.asyncio
async def test_invalidate_with_redis_off_returns_zero() -> None:
    cache = _FakeCacheManager(redis_enabled=False)
    deleted = await invalidate_render_cache_for_post(cache, post_id=uuid.uuid4())  # type: ignore[arg-type]
    assert deleted == 0


@pytest.mark.asyncio
async def test_cache_returns_byte_identical_html_to_uncached_path() -> None:
    """Cache layer must not silently alter the output. Compare against the
    direct pipeline for a representative document."""
    cache = _FakeCacheManager()
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Title"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Bold + italic",
                                        "marks": [{"type": "bold"}, {"type": "italic"}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            {"type": "horizontalRule"},
            {
                "type": "image",
                "attrs": {"src": "https://example.com/a.png", "alt": "alt text"},
            },
        ],
    }
    direct = sanitize_html(render_html(doc))
    via_cache = await render_html_cached(
        cache,  # type: ignore[arg-type]
        post_id=uuid.uuid4(),
        content_json=doc,
        content_hash="rep",
    )
    assert via_cache == direct
