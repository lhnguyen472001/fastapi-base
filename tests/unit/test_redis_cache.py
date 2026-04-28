"""Unit tests for ``apps.core.redis``.

The tests use ``AsyncMock`` to stand in for :class:`RedisClient` so we
can exercise :class:`CacheManager` and the ``cached`` decorator without
a real Redis. The integration / round-trip tests live elsewhere and
require ``REDIS_ENABLED=true`` plus a reachable Redis.
"""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.redis import CacheManager
from apps.core.redis.constants import INVALIDATE_BATCH_SIZE

pytestmark = pytest.mark.unit


def _make_redis_mock() -> MagicMock:
    """Return a MagicMock shaped like RedisClient with async methods."""
    mock = MagicMock(name="RedisClient")
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=0)
    mock.exists = AsyncMock(return_value=0)
    mock.scan_iter = MagicMock()
    return mock


class TestNoOpMode:
    """When the underlying client is None, every method is a safe no-op."""

    @pytest.mark.asyncio
    async def test_get_returns_none(self) -> None:
        cache = CacheManager(redis_client=None)
        assert await cache.get("any") is None

    @pytest.mark.asyncio
    async def test_set_returns_false(self) -> None:
        cache = CacheManager(redis_client=None)
        assert await cache.set("k", {"v": 1}) is False

    @pytest.mark.asyncio
    async def test_delete_returns_zero(self) -> None:
        cache = CacheManager(redis_client=None)
        assert await cache.delete("a", "b") == 0

    @pytest.mark.asyncio
    async def test_exists_returns_false(self) -> None:
        cache = CacheManager(redis_client=None)
        assert await cache.exists("a") is False

    @pytest.mark.asyncio
    async def test_invalidate_pattern_returns_zero(self) -> None:
        cache = CacheManager(redis_client=None)
        assert await cache.invalidate_pattern("user:*") == 0


class TestSerialization:
    @pytest.mark.asyncio
    async def test_set_serializes_uuid_via_default_str(self) -> None:
        redis = _make_redis_mock()
        cache = CacheManager(redis_client=redis)
        uid = uuid.uuid4()

        ok = await cache.set("k", {"id": uid})

        assert ok is True
        redis.set.assert_awaited_once()
        stored_value = redis.set.await_args.args[1]
        assert str(uid) in stored_value

    @pytest.mark.asyncio
    async def test_set_serializes_datetime(self) -> None:
        redis = _make_redis_mock()
        cache = CacheManager(redis_client=redis)
        when = dt.datetime(2026, 4, 29, 12, 0, 0, tzinfo=dt.UTC)

        ok = await cache.set("k", {"at": when})

        assert ok is True
        stored = redis.set.await_args.args[1]
        assert "2026-04-29" in stored

    @pytest.mark.asyncio
    async def test_set_returns_false_on_unserializable(self) -> None:
        redis = _make_redis_mock()
        cache = CacheManager(redis_client=redis)

        class _Bad:
            """``default=str`` falls through to ``str()`` which raises here."""

            def __str__(self) -> str:
                raise TypeError("not stringifiable")

            def __repr__(self) -> str:
                return "<Bad>"

        ok = await cache.set("k", _Bad())
        assert ok is False
        redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_treats_non_json_value_as_miss(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value="not json")
        cache = CacheManager(redis_client=redis)

        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_get_returns_deserialized_value(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value='{"a": 1}')
        cache = CacheManager(redis_client=redis)

        assert await cache.get("k") == {"a": 1}


class TestPresence:
    @pytest.mark.asyncio
    async def test_exists_true_only_when_all_present(self) -> None:
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=2)
        cache = CacheManager(redis_client=redis)

        assert await cache.exists("a", "b") is True

    @pytest.mark.asyncio
    async def test_exists_false_when_partial(self) -> None:
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=1)
        cache = CacheManager(redis_client=redis)

        assert await cache.exists("a", "b") is False

    @pytest.mark.asyncio
    async def test_delete_with_no_keys_skips_redis(self) -> None:
        redis = _make_redis_mock()
        cache = CacheManager(redis_client=redis)

        assert await cache.delete() == 0
        redis.delete.assert_not_awaited()


class TestInvalidatePattern:
    @pytest.mark.asyncio
    async def test_no_matching_keys_returns_zero(self) -> None:
        redis = _make_redis_mock()

        async def _empty():
            return
            yield  # pragma: no cover  # makes this an async generator

        redis.scan_iter = MagicMock(return_value=_empty())
        cache = CacheManager(redis_client=redis)

        assert await cache.invalidate_pattern("foo:*") == 0
        redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self) -> None:
        redis = _make_redis_mock()

        async def _three():
            for k in ["a", "b", "c"]:
                yield k

        redis.scan_iter = MagicMock(return_value=_three())
        redis.delete = AsyncMock(return_value=3)
        cache = CacheManager(redis_client=redis)

        deleted = await cache.invalidate_pattern("foo:*")

        assert deleted == 3
        redis.delete.assert_awaited_once_with("a", "b", "c")

    @pytest.mark.asyncio
    async def test_batches_when_over_threshold(self) -> None:
        redis = _make_redis_mock()
        keys = [f"k{i}" for i in range(INVALIDATE_BATCH_SIZE + 5)]

        async def _gen():
            for k in keys:
                yield k

        redis.scan_iter = MagicMock(return_value=_gen())
        redis.delete = AsyncMock(return_value=INVALIDATE_BATCH_SIZE)
        cache = CacheManager(redis_client=redis)

        await cache.invalidate_pattern("k*")

        assert redis.delete.await_count == 2


class TestCachedDecorator:
    @pytest.mark.asyncio
    async def test_rejects_sync_functions(self) -> None:
        cache = CacheManager(redis_client=None)

        with pytest.raises(TypeError, match="async functions"):

            @cache.cached()
            def sync_fn() -> int:
                return 1

    @pytest.mark.asyncio
    async def test_miss_then_hit_round_trip(self) -> None:
        redis = _make_redis_mock()
        store: dict[str, str] = {}
        redis.get = AsyncMock(side_effect=store.get)
        redis.set = AsyncMock(
            side_effect=lambda k, v, ex=None: store.update({k: v}) or True,
        )
        cache = CacheManager(redis_client=redis)

        calls = 0

        @cache.cached(ttl=60, key_prefix="t")
        async def slow(uid: str) -> dict:
            nonlocal calls
            calls += 1
            return {"uid": uid}

        first = await slow("abc")
        second = await slow("abc")

        assert first == {"uid": "abc"}
        assert second == {"uid": "abc"}
        assert calls == 1, "second call should be served from cache"

    @pytest.mark.asyncio
    async def test_uses_custom_key_builder(self) -> None:
        redis = _make_redis_mock()
        cache = CacheManager(redis_client=redis)

        @cache.cached(key_builder=lambda uid: f"custom:{uid}")
        async def fn(uid: str) -> str:
            return uid.upper()

        await fn("xyz")
        assert redis.set.await_args.args[0] == "custom:xyz"

    @pytest.mark.asyncio
    async def test_no_op_passthrough_when_redis_disabled(self) -> None:
        cache = CacheManager(redis_client=None)
        calls = 0

        @cache.cached()
        async def fn(x: int) -> int:
            nonlocal calls
            calls += 1
            return x * 2

        assert await fn(3) == 6
        assert await fn(3) == 6
        assert calls == 2


class TestBuildCacheKey:
    def test_uuid_args_produce_stable_key(self) -> None:
        async def _f(uid: uuid.UUID) -> None: ...  # pragma: no cover

        uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        k1 = CacheManager._build_cache_key(_f, (uid,), {}, prefix="p")
        k2 = CacheManager._build_cache_key(_f, (uid,), {}, prefix="p")
        assert k1 == k2
        assert k1.startswith("p:")

    def test_different_args_produce_different_keys(self) -> None:
        async def _f(x: int) -> None: ...  # pragma: no cover

        assert CacheManager._build_cache_key(_f, (1,), {}) != CacheManager._build_cache_key(_f, (2,), {})

    def test_no_prefix_produces_two_part_key(self) -> None:
        async def _f() -> None: ...  # pragma: no cover

        key = CacheManager._build_cache_key(_f, (), {})
        assert key.count(":") == 1


class TestGetRedisClient:
    def test_returns_none_when_disabled(self) -> None:
        from apps.core.redis import client as rc  # noqa: PLC0415 — needed to mutate the singleton state

        rc._redis_client = None
        rc.app_settings.redis.enabled = False
        try:
            assert rc.get_redis_client() is None
        finally:
            rc.app_settings.redis.enabled = False
