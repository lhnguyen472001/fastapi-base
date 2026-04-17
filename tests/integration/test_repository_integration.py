"""Integration tests for BaseSQLAlchemyRepository against a real Postgres."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from apps.core.database.filters import (
    CollectionFilter,
    ComparisonFilter,
    LimitOffsetPaginationFilter,
    NotInCollectionFilter,
    OrderBy,
)

if TYPE_CHECKING:
    from tests.integration._models import Widget, WidgetRepository

# ------------------------------ helpers -------------------------------------


async def _seed(session, repo: WidgetRepository, n: int = 5) -> list[Widget]:
    items = []
    for i in range(n):
        items.append(
            await repo.add(
                session,
                {"name": f"w{i}", "quantity": i, "is_featured": i % 2 == 0},
                expunge=False,
            )
        )
    await session.commit()
    return items


# --------------------------------- add --------------------------------------


async def test_add_persists_row(session, widget_repo) -> None:
    item = await widget_repo.add(session, {"name": "alpha", "quantity": 3}, expunge=False)
    await session.commit()

    assert item.id is not None
    assert item.created_at is not None

    fetched = await widget_repo.get_one_by_id(session, item_id=item.id)
    assert fetched is not None
    assert fetched.name == "alpha"
    assert fetched.quantity == 3


async def test_add_many_persists_rows(session, widget_repo) -> None:
    items = await widget_repo.add_many(
        session,
        [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        expunge=False,
    )
    await session.commit()

    total = await widget_repo.count(session)
    assert total == 3
    assert {i.name for i in items} == {"a", "b", "c"}


# -------------------------- get / get_by_id ---------------------------------


async def test_get_one_by_id_returns_none_for_missing(session, widget_repo) -> None:
    result = await widget_repo.get_one_by_id(session, item_id=uuid.uuid4())
    assert result is None


async def test_get_one_with_kwargs_filter(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=3)

    result = await widget_repo.get_one(session, name="w1")
    assert result is not None
    assert result.quantity == 1


# -------------------------- list / list_and_count ---------------------------


async def test_list_items_returns_all(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=4)

    items = await widget_repo.list_items(session)
    assert len(items) == 4


async def test_list_with_pagination_filter(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=10)

    items = await widget_repo.list_items(
        session,
        LimitOffsetPaginationFilter(limit=3, offset=2),
        OrderBy(field_name="quantity", direction="asc"),
    )
    assert [i.quantity for i in items] == [2, 3, 4]


async def test_list_and_count_returns_total(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=7)

    items, total = await widget_repo.list_and_count(
        session,
        LimitOffsetPaginationFilter(limit=3, offset=0),
        OrderBy(field_name="quantity", direction="asc"),
    )
    assert total == 7
    assert len(items) == 3


async def test_list_and_count_window_function(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)

    items, total = await widget_repo.list_and_count(
        session,
        OrderBy(field_name="quantity", direction="asc"),
        using_window_function=True,
    )
    assert total == 5
    assert len(items) == 5


async def test_list_and_count_zero(session, widget_repo) -> None:
    items, total = await widget_repo.list_and_count(session)
    assert items == []
    assert total == 0


# ---------------------------- comparison filter -----------------------------


async def test_comparison_filter_gt(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)  # quantities 0..4

    items = await widget_repo.list_items(session, ComparisonFilter(field_name="quantity", operator="gt", value=2))
    assert sorted(i.quantity for i in items) == [3, 4]


async def test_comparison_filter_between(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)

    items = await widget_repo.list_items(
        session,
        ComparisonFilter(field_name="quantity", operator="between", value=(1, 3)),
    )
    assert sorted(i.quantity for i in items) == [1, 2, 3]


async def test_collection_filter_in(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)

    items = await widget_repo.list_items(session, CollectionFilter(field_name="name", values=["w0", "w2"]))
    assert sorted(i.name for i in items) == ["w0", "w2"]


async def test_collection_filter_empty_returns_no_rows(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=3)

    items = await widget_repo.list_items(session, CollectionFilter(field_name="name", values=[]))
    assert items == []


async def test_not_in_collection_filter(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=4)

    items = await widget_repo.list_items(session, NotInCollectionFilter(field_name="name", values=["w0", "w1"]))
    assert sorted(i.name for i in items) == ["w2", "w3"]


# -------------------------------- count -------------------------------------


async def test_count_with_filter(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)

    total = await widget_repo.count(session, is_featured=True)
    # quantities 0,2,4 -> is_featured=True
    assert total == 3


# -------------------------------- update ------------------------------------


async def test_update_dict_changes_fields(session, widget_repo) -> None:
    seeded = await _seed(session, widget_repo, n=1)
    item = seeded[0]

    updated = await widget_repo.update(session, item_id=item.id, data={"name": "renamed", "quantity": 99})
    await session.commit()

    assert updated is not None
    assert updated.name == "renamed"
    assert updated.quantity == 99

    refetched = await widget_repo.get_one_by_id(session, item_id=item.id)
    assert refetched.name == "renamed"
    assert refetched.quantity == 99


async def test_update_returns_none_for_missing_id(session, widget_repo) -> None:
    result = await widget_repo.update(session, item_id=uuid.uuid4(), data={"name": "x"})
    assert result is None


# -------------------------- get_or_upsert -----------------------------------


async def test_get_or_upsert_inserts_when_missing(session, widget_repo) -> None:
    obj, created = await widget_repo.get_or_upsert(
        session,
        match_fields="name",
        name="brand_new",
        quantity=1,
    )
    await session.commit()

    assert created is True
    assert obj.name == "brand_new"
    assert await widget_repo.count(session) == 1


async def test_get_or_upsert_updates_when_exists(session, widget_repo) -> None:
    seeded = await _seed(session, widget_repo, n=1)
    original = seeded[0]

    obj, created = await widget_repo.get_or_upsert(
        session,
        match_fields="name",
        upsert=True,
        name=original.name,
        quantity=999,
    )
    await session.commit()

    assert created is False
    assert obj.quantity == 999


# -------------------------------- delete ------------------------------------


async def test_delete_removes_row(session, widget_repo) -> None:
    seeded = await _seed(session, widget_repo, n=2)
    target = seeded[0]

    deleted = await widget_repo.delete(session, item_id=target.id)
    await session.commit()

    assert deleted is not None
    assert await widget_repo.count(session) == 1
    assert await widget_repo.get_one_by_id(session, item_id=target.id) is None


async def test_delete_where_returns_deleted(session, widget_repo) -> None:
    await _seed(session, widget_repo, n=5)

    deleted = await widget_repo.delete_where(session, ComparisonFilter(field_name="quantity", operator="ge", value=3))
    await session.commit()

    assert deleted is not None
    assert len(deleted) == 2
    assert await widget_repo.count(session) == 3


# ------------------------------- soft delete --------------------------------


async def test_soft_delete_filter_excludes_deleted_rows(session, soft_widget_repo) -> None:
    a = await soft_widget_repo.add(session, {"name": "live"}, expunge=False)
    b = await soft_widget_repo.add(session, {"name": "ghost"}, expunge=False)
    b.delete()  # mark soft-deleted
    await session.commit()

    # default list filters out deleted rows via _get_soft_delete_filter
    items = await soft_widget_repo.list_items(session)
    names = [i.name for i in items]

    assert "live" in names
    assert "ghost" not in names
    _ = a  # silence unused
