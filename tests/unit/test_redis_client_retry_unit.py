"""Unit tests for MED-6: RedisClient retries transient errors once via tenacity.

Hot helpers (``get`` / ``set`` / ``delete`` / ``exists`` / ``expire`` /
``ttl`` / hash + list ops) used to fall straight through to the safe
fallback on any ``ConnectionError`` / ``TimeoutError``. With the
``@tenacity.retry`` decorator they now retry once after a short delay,
so one-shot network blips no longer translate into lost requests.
Programmer errors (``DataError``, ``ResponseError``) must NOT retry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from redis import exceptions as redis_exceptions

from apps.core.redis.client import RedisClient


def _make_client(method_name: str, side_effect) -> tuple[RedisClient, AsyncMock]:
    """Build a RedisClient whose underlying aioredis method is mocked."""
    client = RedisClient.__new__(RedisClient)
    client._pool = None
    client._client = AsyncMock()
    method = AsyncMock(side_effect=side_effect)
    setattr(client._client, method_name, method)
    return client, method


@pytest.mark.asyncio
async def test_get_retries_once_on_transient_then_succeeds() -> None:
    """First attempt raises ConnectionError, second returns a value."""
    client, get_mock = _make_client(
        "get", side_effect=[redis_exceptions.ConnectionError("blip"), "hello"]
    )

    value = await client.get("k")

    assert value == "hello"
    assert get_mock.await_count == 2


@pytest.mark.asyncio
async def test_get_returns_none_after_retry_budget_exhausted() -> None:
    """Both attempts raise → fallback ``None`` returned, no exception escapes."""
    client, get_mock = _make_client(
        "get",
        side_effect=[
            redis_exceptions.ConnectionError("blip 1"),
            redis_exceptions.ConnectionError("blip 2"),
        ],
    )

    value = await client.get("k")

    assert value is None
    assert get_mock.await_count == 2


@pytest.mark.asyncio
async def test_get_does_not_retry_on_non_transient_error() -> None:
    """``DataError`` is a programmer mistake; retrying just wastes time."""
    client, get_mock = _make_client(
        "get", side_effect=redis_exceptions.DataError("bad type")
    )

    with pytest.raises(redis_exceptions.DataError):
        await client.get("k")
    assert get_mock.await_count == 1


@pytest.mark.asyncio
async def test_set_falls_back_to_false_after_retries() -> None:
    client, set_mock = _make_client(
        "set",
        side_effect=[
            redis_exceptions.TimeoutError("t1"),
            redis_exceptions.TimeoutError("t2"),
        ],
    )

    ok = await client.set("k", "v", ex=10)

    assert ok is False
    assert set_mock.await_count == 2


@pytest.mark.asyncio
async def test_delete_falls_back_to_zero_after_retries() -> None:
    client, delete_mock = _make_client(
        "delete",
        side_effect=[
            redis_exceptions.ConnectionError("x"),
            redis_exceptions.ConnectionError("x"),
        ],
    )

    n = await client.delete("k1", "k2")

    assert n == 0
    assert delete_mock.await_count == 2


@pytest.mark.asyncio
async def test_hgetall_falls_back_to_empty_dict() -> None:
    client, hgetall_mock = _make_client(
        "hgetall",
        side_effect=[
            redis_exceptions.ConnectionError("x"),
            redis_exceptions.ConnectionError("x"),
        ],
    )

    result = await client.hgetall("h")

    assert result == {}
    assert hgetall_mock.await_count == 2


@pytest.mark.asyncio
async def test_lrange_falls_back_to_empty_list() -> None:
    client, lrange_mock = _make_client(
        "lrange",
        side_effect=[
            redis_exceptions.ConnectionError("x"),
            redis_exceptions.ConnectionError("x"),
        ],
    )

    result = await client.lrange("l", 0, -1)

    assert result == []
    assert lrange_mock.await_count == 2


@pytest.mark.asyncio
async def test_ttl_falls_back_to_minus_two() -> None:
    client, ttl_mock = _make_client(
        "ttl",
        side_effect=[
            redis_exceptions.TimeoutError("t"),
            redis_exceptions.TimeoutError("t"),
        ],
    )

    result = await client.ttl("k")

    assert result == -2
    assert ttl_mock.await_count == 2


@pytest.mark.asyncio
async def test_delete_no_keys_short_circuits_without_calling_redis() -> None:
    """The early-return ``if not keys: return 0`` guard must still fire so
    we don't hit Redis with a malformed empty-args DELETE."""
    client, delete_mock = _make_client("delete", side_effect=[])

    n = await client.delete()

    assert n == 0
    assert delete_mock.await_count == 0


@pytest.mark.asyncio
async def test_ping_widens_retry_to_any_redis_error_and_falls_back_to_false() -> None:
    """``ping`` historically caught the broader ``RedisError`` family; the
    decorator preserves that by widening ``retry_on``."""
    client, ping_mock = _make_client(
        "ping",
        side_effect=[
            redis_exceptions.RedisError("first"),
            redis_exceptions.RedisError("second"),
        ],
    )

    result = await client.ping()

    assert result is False
    assert ping_mock.await_count == 2
