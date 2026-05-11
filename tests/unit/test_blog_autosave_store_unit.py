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

from apps.blog.constants import (
    AUTOSAVE_DIRTY_SET,
    AUTOSAVE_KEY_PREFIX,
    AUTOSAVE_SWEEPER_LEADER_KEY,
    AUTOSAVE_TTL_SECONDS,
)
from apps.blog.store import (
    _LEADER_ACQUIRE_OR_RENEW_SCRIPT,
    _LOCK_RELEASE_SCRIPT,
    _MARK_FLUSHED_SCRIPT,
    _SAVE_SCRIPT,
    AutosaveSnapshot,
    AutosaveStore,
)

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
    async def test_save_evals_save_script_with_full_args(self) -> None:
        redis, inner = _make_redis_mock()
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

        inner.eval.assert_awaited_once()
        call = inner.eval.await_args
        # Positional args: script source, numkeys, then KEYS followed by ARGV.
        assert call.args[0] == _SAVE_SCRIPT
        assert call.args[1] == 2
        # KEYS
        assert call.args[2] == f"{AUTOSAVE_KEY_PREFIX}:{post_id}"
        assert call.args[3] == AUTOSAVE_DIRTY_SET
        # ARGV[1..9]
        assert call.args[4] == str(post_id)
        assert call.args[5] == str(AUTOSAVE_TTL_SECONDS)
        assert call.args[6] == str(post_id)
        assert call.args[7] == str(workspace_id)
        assert call.args[8] == str(author_id)
        # content_json (ARGV[6]) is the compact JSON serialization
        assert "hi" in call.args[9]
        assert call.args[10] == "abc"  # content_hash
        assert call.args[11] == "42"  # word_count

    @pytest.mark.asyncio
    async def test_save_runs_atomic_script(self) -> None:
        """``flushed_hash`` preservation is now a Lua-level guarantee.

        The Python wrapper no longer reads ``flushed_hash`` and writes it
        back; both happen inside ``_SAVE_SCRIPT`` via a single ``EVAL``.
        Real-Redis preservation is verified in the realdb integration
        suite (``test_blog_autosave_realdb.py``).
        """
        redis, inner = _make_redis_mock()
        store = AutosaveStore(redis_client=redis)

        await store.save(
            post_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={"type": "doc", "content": []},
            content_hash="new_hash",
            word_count=1,
        )

        # Crucially we do NOT call hget separately on the Python side.
        redis.hget.assert_not_awaited()
        inner.eval.assert_awaited_once()
        assert inner.eval.await_args.args[0] == _SAVE_SCRIPT


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
    async def test_mark_flushed_evals_cas_script(self) -> None:
        redis, inner = _make_redis_mock()
        # Mock returns 1 = CAS succeeded.
        inner.eval = AsyncMock(return_value=1)
        store = AutosaveStore(redis_client=redis)
        post_id = uuid.uuid4()

        result = await store.mark_flushed(post_id, content_hash="flushed-hash")

        assert result is True
        inner.eval.assert_awaited_once()
        call = inner.eval.await_args
        assert call.args[0] == _MARK_FLUSHED_SCRIPT
        assert call.args[1] == 2
        assert call.args[2] == f"{AUTOSAVE_KEY_PREFIX}:{post_id}"
        assert call.args[3] == AUTOSAVE_DIRTY_SET
        assert call.args[4] == str(post_id)
        assert call.args[5] == "flushed-hash"

    @pytest.mark.asyncio
    async def test_mark_flushed_returns_false_on_cas_rejection(self) -> None:
        redis, inner = _make_redis_mock()
        # 0 = newer save raced; CAS rejected.
        inner.eval = AsyncMock(return_value=0)
        store = AutosaveStore(redis_client=redis)

        result = await store.mark_flushed(uuid.uuid4(), content_hash="stale")

        assert result is False


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


class TestSweeperLeadership:
    """Cover :meth:`AutosaveStore.acquire_or_renew_sweeper_leadership` and
    :meth:`AutosaveStore.release_sweeper_leadership` — the two methods
    that gate the leader-elected sweeper loop."""

    @pytest.mark.asyncio
    async def test_acquire_calls_lua_with_leader_key_token_and_ttl(self) -> None:
        # Arrange
        redis, inner = _make_redis_mock()
        inner.eval = AsyncMock(return_value=1)
        store = AutosaveStore(redis_client=redis)

        # Act
        ok = await store.acquire_or_renew_sweeper_leadership(token="tok-A", ttl_seconds=7)

        # Assert
        assert ok is True
        inner.eval.assert_awaited_once()
        call = inner.eval.await_args
        assert call.args[0] == _LEADER_ACQUIRE_OR_RENEW_SCRIPT
        assert call.args[1] == 1  # numkeys
        assert call.args[2] == AUTOSAVE_SWEEPER_LEADER_KEY
        assert call.args[3] == "tok-A"
        assert call.args[4] == "7"

    @pytest.mark.asyncio
    async def test_acquire_returns_false_when_another_worker_holds_lock(self) -> None:
        # Arrange
        redis, inner = _make_redis_mock()
        inner.eval = AsyncMock(return_value=0)  # Lua: someone else's token
        store = AutosaveStore(redis_client=redis)

        # Act
        ok = await store.acquire_or_renew_sweeper_leadership(token="tok-B")

        # Assert
        assert ok is False

    @pytest.mark.asyncio
    async def test_acquire_short_circuits_when_redis_disabled(self) -> None:
        store = AutosaveStore(redis_client=None)
        ok = await store.acquire_or_renew_sweeper_leadership(token="tok")
        assert ok is False

    @pytest.mark.asyncio
    async def test_release_runs_compare_and_del_lua(self) -> None:
        # Arrange
        redis, inner = _make_redis_mock()
        store = AutosaveStore(redis_client=redis)

        # Act
        await store.release_sweeper_leadership(token="tok-A")

        # Assert
        inner.eval.assert_awaited_once()
        call = inner.eval.await_args
        assert call.args[0] == _LOCK_RELEASE_SCRIPT
        assert call.args[1] == 1
        assert call.args[2] == AUTOSAVE_SWEEPER_LEADER_KEY
        assert call.args[3] == "tok-A"

    @pytest.mark.asyncio
    async def test_release_swallows_eval_failure(self) -> None:
        """Shutdown must complete even if Redis briefly refuses the release."""
        # Arrange
        redis, inner = _make_redis_mock()
        inner.eval = AsyncMock(side_effect=RuntimeError("conn reset"))
        store = AutosaveStore(redis_client=redis)

        # Act / Assert — no exception leaks out
        await store.release_sweeper_leadership(token="tok-A")

    @pytest.mark.asyncio
    async def test_release_no_op_when_redis_disabled(self) -> None:
        store = AutosaveStore(redis_client=None)
        await store.release_sweeper_leadership(token="tok")  # no exception
