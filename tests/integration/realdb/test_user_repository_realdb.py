"""Real-DB integration tests for the User repository against migrated tables."""

from __future__ import annotations

import uuid

import pytest

from apps.core.database.sql.filters import (
    ComparisonFilter,
    LimitOffsetPaginationFilter,
    OrderBy,
)
from apps.user.repositories import UserRepository


@pytest.fixture
def user_repo() -> UserRepository:
    return UserRepository()


def _user_payload(suffix: str) -> dict:
    return {
        "email": f"user_{suffix}@example.com",
        "username": f"user_{suffix}",
        "hashed_password": "x" * 60,
        "is_active": True,
    }


async def test_add_user_persists_row(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await user_repo.add(real_session, _user_payload(suffix), expunge=False)
    await real_session.flush()

    assert user.id is not None
    assert user.created_at is not None
    assert user.updated_at is not None

    fetched = await user_repo.get_one_by_id(real_session, item_id=user.id)
    assert fetched is not None
    assert fetched.username == f"user_{suffix}"


async def test_add_many_and_count(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    payloads = [_user_payload(f"{suffix}_{i}") for i in range(3)]
    await user_repo.add_many(real_session, payloads, expunge=False)
    await real_session.flush()

    total = await user_repo.count(real_session)
    assert total >= 3


async def test_find_by_email_or_username(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _user_payload(suffix)
    await user_repo.add(real_session, payload, expunge=False)
    await real_session.flush()

    by_email = await user_repo.find_by_email_or_username(real_session, email=payload["email"])
    by_username = await user_repo.find_by_email_or_username(real_session, username=payload["username"])

    assert by_email is not None and by_email.username == payload["username"]
    assert by_username is not None and by_username.email == payload["email"]


async def test_list_with_pagination_and_ordering(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    payloads = [_user_payload(f"{suffix}_{i}") for i in range(5)]
    await user_repo.add_many(real_session, payloads, expunge=False)
    await real_session.flush()

    items = await user_repo.list_items(
        real_session,
        ComparisonFilter(field_name="username", operator="like", value=f"user_{suffix}%"),
        OrderBy(field_name="username", direction="asc"),
        LimitOffsetPaginationFilter(limit=3, offset=0),
    )

    assert len(items) == 3
    assert all(i.username.startswith(f"user_{suffix}") for i in items)
    usernames = [i.username for i in items]
    assert usernames == sorted(usernames)


async def test_list_and_count_returns_total(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    payloads = [_user_payload(f"{suffix}_{i}") for i in range(4)]
    await user_repo.add_many(real_session, payloads, expunge=False)
    await real_session.flush()

    items, total = await user_repo.list_and_count(
        real_session,
        ComparisonFilter(field_name="username", operator="like", value=f"user_{suffix}%"),
        LimitOffsetPaginationFilter(limit=2, offset=0),
    )

    assert total == 4
    assert len(items) == 2


async def test_update_user(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await user_repo.add(real_session, _user_payload(suffix), expunge=False)
    await real_session.flush()

    updated = await user_repo.update(
        real_session, item_id=user.id, data={"is_active": False}
    )

    assert updated is not None
    assert updated.is_active is False

    refetched = await user_repo.get_one_by_id(real_session, item_id=user.id)
    assert refetched.is_active is False


async def test_get_or_upsert_inserts_then_updates(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _user_payload(suffix)

    obj1, created1 = await user_repo.get_or_upsert(
        real_session, match_fields="email", **payload
    )
    await real_session.flush()
    assert created1 is True
    assert obj1.email == payload["email"]

    payload["hashed_password"] = "y" * 60
    obj2, created2 = await user_repo.get_or_upsert(
        real_session, match_fields="email", upsert=True, **payload
    )
    await real_session.flush()

    assert created2 is False
    assert obj2.id == obj1.id
    assert obj2.hashed_password == "y" * 60


async def test_soft_delete_excluded_from_default_listing(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await user_repo.add(real_session, _user_payload(suffix), expunge=False)
    user.delete()
    await real_session.flush()

    items = await user_repo.list_items(
        real_session,
        ComparisonFilter(field_name="username", operator="eq", value=user.username),
    )
    assert items == []


async def test_hard_delete_removes_row(real_session, user_repo) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await user_repo.add(real_session, _user_payload(suffix), expunge=False)
    await real_session.flush()

    deleted = await user_repo.delete(real_session, item_id=user.id)
    await real_session.flush()

    assert deleted is not None
    assert await user_repo.get_one_by_id(real_session, item_id=user.id) is None
