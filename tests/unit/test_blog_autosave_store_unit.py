"""Unit tests for :class:`apps.blog.store.AutosaveStore`.

Stand in for :class:`apps.core.redis.RedisClient` with ``AsyncMock`` —
the same pattern as :mod:`tests.unit.test_redis_cache`. Real-Redis
behavior is exercised in the realdb integration suite.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.blog.constants import AUTOSAVE_DIRTY_SET, AUTOSAVE_KEY_PREFIX, AUTOSAVE_TTL_SECONDS
from apps.blog.store import AutosaveSnapshot, AutosaveStore

pytestmark = pytest.mark.unit


def _make_redis_mock() -> tuple[MagicMock, MagicMock]:
    """Return ``(redis_client_mock, inner_aioredis_mock)``."""
    inner = MagicMock(name="aioredis.Redis")
    inner.sadd = AsyncMock(return_value=1)
    inner.srem = AsyncMock(return_value=1)
    inner.sscan = AsyncMock(return_value=(0, []))
    inner.eval = AsyncMock(return_value=1)

    client = MagicMock(name="RedisClient")
    client.client = inner
    client.hget = AsyncMock(return_value=None)
    client.hset = AsyncMock(return_value=1)
    client.hgetall = AsyncMock(return_value={})
    client.expire = AsyncMock(return_value=True)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    return client, inner


def _snapshot_payload(
    *,
    post_id: uuid.UUID,
    workspace_id: uuid.UUID,
    author_id: uuid.UUID,
    content_hash: str,
    flushed_hash: str = "",
    word_count: int = 5,
) -> dict[str, str]:
    return {
        "post_id": str(post_id),
        "workspace_id": str(workspace_id),
        "author_id": str(author_id),
        "content_json": json.dumps({"type": "doc", "content": []}),
        "content_hash": content_hash,
        "flushed_hash": flushed_hash,
        "word_count": str(word_count),
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
    }


class TestDisabledMode:
    """When the underlying client is None every method short-circuits."""

    def test_enabled_flag_is_false(self) -> None:
        store = AutosaveStore(redis_client=None)
        assert store.enabled is False

    @pytest.mark.asyncio
    async def test_save_returns_false(self) -> None:
        store = AutosaveStore(redis_client=None)
        ok = await store.save(
            post_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={"type": "doc", "content": []},
            content_hash="h",
            word_count=0,
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_get_returns_none(self) -> None:
        store = AutosaveStore(redis_client=None)
        assert await store.get(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_iter_dirty_yields_nothing(self) -> None:
        store = AutosaveStore(redis_client=None)
        items = [item async for item in store.iter_dirty()]
        assert items == []

    @pytest.mark.asyncio
    async def test_acquire_lock_yields_false(self) -> None:
        store = AutosaveStore(redis_client=None)
        async with store.acquire_flush_lock(uuid.uuid4()) as got_lock:
            assert got_lock is False


class TestSave:
    @pytest.mark.asyncio
    async def test_save_hsets_full_mapping_and_marks_dirty(self) -> None:
        redis, inner = _make_redis_mock()
        redis.hget = AsyncMock(return_value=None)  # no existing flushed_hash
        store = AutosaveStore(redis_client=redis)

        post_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        author_id = uuid.uuid4()

        ok = await store.save(
            post_id=post_id,
            workspace_id=workspace_id,
            author_id=author_id,
            content_json={"type": "doc", "content": [{"type": "text", "text": "hi"}]},
            content_hash="abc",
            word_count=42,
        )

        assert ok is True

        redis.hset.assert_awaited_once()
        hset_call = redis.hset.await_args
        assert hset_call.args[0] == f"{AUTOSAVE_KEY_PREFIX}:{post_id}"
        mapping = hset_call.kwargs["mapping"]
        assert mapping["content_hash"] == "abc"
        assert mapping["flushed_hash"] == ""
        assert mapping["word_count"] == "42"
        assert mapping["post_id"] == str(post_id)

        redis.expire.assert_awaited_once_with(f"{AUTOSAVE_KEY_PREFIX}:{post_id}", AUTOSAVE_TTL_SECONDS)
        inner.sadd.assert_awaited_once_with(AUTOSAVE_DIRTY_SET, str(post_id))

    @pytest.mark.asyncio
    async def test_save_preserves_existing_flushed_hash(self) -> None:
        redis, _ = _make_redis_mock()
        redis.hget = AsyncMock(return_value="prior_flushed_hash")
        store = AutosaveStore(redis_client=redis)

        await store.save(
            post_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={"type": "doc", "content": []},
            content_hash="new_hash",
            word_count=1,
        )

        mapping = redis.hset.await_args.kwargs["mapping"]
        assert mapping["flushed_hash"] == "prior_flushed_hash"


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_parsed_snapshot(self) -> None:
        redis, _ = _make_redis_mock()
        post_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        author_id = uuid.uuid4()
        redis.hgetall = AsyncMock(
            return_value=_snapshot_payload(
                post_id=post_id,
                workspace_id=workspace_id,
                author_id=author_id,
                content_hash="h1",
            ),
        )
        store = AutosaveStore(redis_client=redis)

        snap = await store.get(post_id)

        assert isinstance(snap, AutosaveSnapshot)
        assert snap.post_id == post_id
        assert snap.workspace_id == workspace_id
        assert snap.author_id == author_id
        assert snap.content_hash == "h1"
        assert snap.is_dirty is True

    @pytest.mark.asyncio
    async def test_get_returns_none_for_empty_hash(self) -> None:
        redis, _ = _make_redis_mock()
        redis.hgetall = AsyncMock(return_value={})
        store = AutosaveStore(redis_client=redis)
        assert await store.get(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_returns_none_for_corrupt_payload(self) -> None:
        redis, _ = _make_redis_mock()
        redis.hgetall = AsyncMock(return_value={"post_id": "not-a-uuid"})
        store = AutosaveStore(redis_client=redis)
        assert await store.get(uuid.uuid4()) is None


class TestMarkFlushed:
    @pytest.mark.asyncio
    async def test_mark_flushed_sets_field_and_clears_dirty(self) -> None:
        redis, inner = _make_redis_mock()
        store = AutosaveStore(redis_client=redis)
        post_id = uuid.uuid4()

        await store.mark_flushed(post_id, content_hash="flushed-hash")

        redis.hset.assert_awaited_once_with(f"{AUTOSAVE_KEY_PREFIX}:{post_id}", "flushed_hash", "flushed-hash")
        inner.srem.assert_awaited_once_with(AUTOSAVE_DIRTY_SET, str(post_id))


class TestIsDirty:
    def test_snapshot_is_dirty_when_hashes_differ(self) -> None:
        snap = AutosaveSnapshot(
            post_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={},
            content_hash="a",
            flushed_hash="b",
            word_count=0,
            updated_at=dt.datetime.now(dt.UTC),
        )
        assert snap.is_dirty is True

    def test_snapshot_is_clean_when_hashes_match(self) -> None:
        snap = AutosaveSnapshot(
            post_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={},
            content_hash="a",
            flushed_hash="a",
            word_count=0,
            updated_at=dt.datetime.now(dt.UTC),
        )
        assert snap.is_dirty is False


class TestAcquireFlushLock:
    @pytest.mark.asyncio
    async def test_acquire_returns_true_on_set_nx_success(self) -> None:
        redis, inner = _make_redis_mock()
        redis.set = AsyncMock(return_value=True)
        store = AutosaveStore(redis_client=redis)

        async with store.acquire_flush_lock(uuid.uuid4()) as got_lock:
            assert got_lock is True

        inner.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_returns_false_when_locked(self) -> None:
        redis, inner = _make_redis_mock()
        redis.set = AsyncMock(return_value=False)
        store = AutosaveStore(redis_client=redis)

        async with store.acquire_flush_lock(uuid.uuid4()) as got_lock:
            assert got_lock is False

        inner.eval.assert_not_awaited()
