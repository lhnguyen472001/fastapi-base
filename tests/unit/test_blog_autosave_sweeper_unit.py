"""Unit tests for :mod:`apps.blog.sweeper`.

These tests drive the leader-election loop in :func:`autosave_sweeper`
with mocks for the :class:`AutosaveStore` and :class:`PostService`
collaborators. Real-Redis behaviour is exercised in the realdb
integration suite.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.blog.store import AutosaveSnapshot
from apps.blog.sweeper import autosave_sweeper, sweep_once

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _make_store_mock(*, enabled: bool = True) -> MagicMock:
    """Return an :class:`AutosaveStore` mock wired to the leader API."""
    store = MagicMock(name="AutosaveStore")
    store.enabled = enabled
    store.acquire_or_renew_sweeper_leadership = AsyncMock(return_value=False)
    store.release_sweeper_leadership = AsyncMock(return_value=None)

    async def _empty_iter(*_args: Any, **_kwargs: Any):
        return
        yield  # unreachable — makes this an async generator

    store.iter_dirty = _empty_iter
    store.get = AsyncMock(return_value=None)
    return store


def _make_snapshot(*, post_id: uuid.UUID, age_seconds: float = 1.5) -> AutosaveSnapshot:
    return AutosaveSnapshot(
        post_id=post_id,
        workspace_id=uuid.uuid4(),
        author_id=uuid.uuid4(),
        content_json={"type": "doc", "content": []},
        content_hash="h-new",
        flushed_hash="",
        word_count=3,
        updated_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=age_seconds),
    )


@asynccontextmanager
async def _session_cm():
    yield MagicMock(name="AsyncSession")


def _session_factory():
    return _session_cm()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestDisabledMode:
    @pytest.mark.asyncio
    async def test_sweeper_exits_early_when_redis_disabled(self) -> None:
        # Arrange
        store = _make_store_mock(enabled=False)
        post_service = MagicMock(name="PostService")

        # Act — should return immediately, not loop forever.
        await asyncio.wait_for(
            autosave_sweeper(_session_factory, post_service, store, interval=0.01),
            timeout=1.0,
        )

        # Assert — never tried to take leadership.
        store.acquire_or_renew_sweeper_leadership.assert_not_awaited()


class TestLeaderElection:
    @pytest.mark.asyncio
    async def test_follower_does_not_run_sweep(self) -> None:
        """If acquire_or_renew returns False the loop skips sweep_once."""
        # Arrange
        store = _make_store_mock()
        store.acquire_or_renew_sweeper_leadership = AsyncMock(return_value=False)
        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock(return_value=None)

        # Act — run the loop for a brief slice then cancel.
        task = asyncio.create_task(
            autosave_sweeper(
                _session_factory,
                post_service,
                store,
                interval=0.01,
                heartbeat_every_ticks=1000,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Assert — followers must not touch Postgres.
        post_service.flush_one.assert_not_awaited()
        # And there is no drain pass on cancel because we were never leader.
        store.release_sweeper_leadership.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_leader_runs_sweep_and_drains_on_cancel(self) -> None:
        """Leader path: each tick runs sweep; cancel triggers a final drain
        plus release of the leader lock with the worker's own token."""
        # Arrange
        post_id = uuid.uuid4()
        snapshot = _make_snapshot(post_id=post_id, age_seconds=0.5)

        store = _make_store_mock()
        store.acquire_or_renew_sweeper_leadership = AsyncMock(return_value=True)

        async def _iter_with_post(*_args: Any, **_kwargs: Any):
            yield post_id

        store.iter_dirty = _iter_with_post
        store.get = AsyncMock(return_value=snapshot)

        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock(return_value=MagicMock(name="Post"))

        # Act
        task = asyncio.create_task(
            autosave_sweeper(
                _session_factory,
                post_service,
                store,
                interval=0.01,
                heartbeat_every_ticks=1000,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Assert — leader did the work and gave the lock back cleanly.
        assert post_service.flush_one.await_count >= 1
        store.release_sweeper_leadership.assert_awaited_once()
        # The release call must use the same token used for acquire so it
        # can't accidentally clear another worker's lock after takeover.
        release_token = store.release_sweeper_leadership.await_args.kwargs["token"]
        acquire_token = store.acquire_or_renew_sweeper_leadership.await_args.kwargs["token"]
        assert release_token == acquire_token

    @pytest.mark.asyncio
    async def test_lost_leadership_emits_warning_and_skips_sweep(self) -> None:
        """When leadership flips from True -> False the loop must stop
        sweeping on that tick (no flush) but keep retrying."""
        # Arrange — alternating: leader, follower, follower, ...
        post_id = uuid.uuid4()
        snapshot = _make_snapshot(post_id=post_id)

        store = _make_store_mock()
        leadership_calls = {"n": 0}

        async def _flip_leadership(**_kwargs: Any) -> bool:
            # Leader on the first call only; follower forever after.
            leadership_calls["n"] += 1
            return leadership_calls["n"] == 1

        store.acquire_or_renew_sweeper_leadership = AsyncMock(side_effect=_flip_leadership)

        async def _iter_with_post(*_args: Any, **_kwargs: Any):
            yield post_id

        store.iter_dirty = _iter_with_post
        store.get = AsyncMock(return_value=snapshot)

        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock(return_value=MagicMock(name="Post"))

        # Act
        task = asyncio.create_task(
            autosave_sweeper(
                _session_factory,
                post_service,
                store,
                interval=0.01,
                heartbeat_every_ticks=1000,
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Assert — flush_one called exactly once (for the single leader
        # tick); follower ticks must not flush anything.
        assert post_service.flush_one.await_count == 1
        # And because the loop ended in follower state, no drain release.
        store.release_sweeper_leadership.assert_not_awaited()


class TestSweepOnce:
    @pytest.mark.asyncio
    async def test_sweep_once_returns_flush_count(self) -> None:
        # Arrange
        post_id = uuid.uuid4()
        snapshot = _make_snapshot(post_id=post_id, age_seconds=2.1)

        store = _make_store_mock()

        async def _iter_with_post(*_args: Any, **_kwargs: Any):
            yield post_id

        store.iter_dirty = _iter_with_post
        store.get = AsyncMock(return_value=snapshot)

        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock(return_value=MagicMock(name="Post"))

        # Act
        flushed = await sweep_once(_session_factory, post_service, store, batch_size=10)

        # Assert
        assert flushed == 1
        post_service.flush_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sweep_once_skips_clean_snapshots(self) -> None:
        """A snapshot whose ``is_dirty`` is False must not trigger a flush."""
        # Arrange
        post_id = uuid.uuid4()
        clean = AutosaveSnapshot(
            post_id=post_id,
            workspace_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            content_json={"type": "doc", "content": []},
            content_hash="h",
            flushed_hash="h",  # matches => is_dirty is False
            word_count=0,
            updated_at=dt.datetime.now(dt.UTC),
        )

        store = _make_store_mock()

        async def _iter_with_post(*_args: Any, **_kwargs: Any):
            yield post_id

        store.iter_dirty = _iter_with_post
        store.get = AsyncMock(return_value=clean)

        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock()

        # Act
        flushed = await sweep_once(_session_factory, post_service, store, batch_size=10)

        # Assert
        assert flushed == 0
        post_service.flush_one.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_once_continues_on_per_post_exception(self) -> None:
        """One failing post must not abort the rest of the batch."""
        # Arrange
        post_a = uuid.uuid4()
        post_b = uuid.uuid4()
        snap_a = _make_snapshot(post_id=post_a)
        snap_b = _make_snapshot(post_id=post_b)

        store = _make_store_mock()

        async def _iter_two(*_args: Any, **_kwargs: Any):
            yield post_a
            yield post_b

        store.iter_dirty = _iter_two
        store.get = AsyncMock(side_effect=[snap_a, snap_b])

        post_service = MagicMock(name="PostService")
        post_service.flush_one = AsyncMock(
            side_effect=[RuntimeError("transient"), MagicMock(name="Post")],
        )

        # Act
        flushed = await sweep_once(_session_factory, post_service, store, batch_size=10)

        # Assert — only the second post counted as flushed; loop did not abort.
        assert flushed == 1
        assert post_service.flush_one.await_count == 2
