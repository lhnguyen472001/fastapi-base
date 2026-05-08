"""Unit tests for BaseSQLAlchemyRepository using mocked AsyncSession.

These tests verify statement construction and dispatch logic without
touching a real database. Real-DB behavior is covered by integration tests.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import Select

from apps.core.database.filters import (
    BeforeAfter,
    CollectionFilter,
    ComparisonFilter,
    LimitOffsetPaginationFilter,
    NotInCollectionFilter,
    OrderBy,
)
from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.repository.base import BaseSQLAlchemyRepository


class _Item(UUIDAuditBase):
    """Throwaway model for unit tests (UUID PK + timestamps)."""

    __tablename__ = "_unit_items"

    name: Mapped[str] = mapped_column()
    value: Mapped[int] = mapped_column(default=0)


class _ItemRepository(BaseSQLAlchemyRepository[_Item]):
    model_type = _Item


def _make_session(
    scalar_one_or_none: Any = None,
    scalars_all: list[Any] | None = None,
    scalar_one: Any = 0,
) -> AsyncMock:
    """Build an AsyncMock AsyncSession."""
    session = AsyncMock()
    result = MagicMock()
    result.unique.return_value = result
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.scalar_one.return_value = scalar_one
    scalars = MagicMock()
    scalars.all.return_value = scalars_all or []
    result.scalars.return_value = scalars
    # iterator yields (instance,) tuples — used by _list_with_count_basic
    result.__iter__ = lambda self: iter([(i,) for i in (scalars_all or [])])
    session.execute.return_value = result
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.merge = AsyncMock(side_effect=lambda obj, load=True: obj)
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.expunge = MagicMock()
    return session


# ----------------------------- construction ---------------------------------


def test_default_statement_is_select_of_model() -> None:
    repo = _ItemRepository()
    assert isinstance(repo.statement, Select)
    compiled = str(repo.statement.compile())
    assert "_unit_items" in compiled


def test_model_property_returns_model_type() -> None:
    assert _ItemRepository().model is _Item


# --------------------------------- add --------------------------------------


async def test_add_with_dict_creates_model_instance() -> None:
    repo = _ItemRepository()
    session = _make_session()

    item = await repo.add(session, {"name": "x", "value": 1}, expunge=False)

    assert isinstance(item, _Item)
    assert item.name == "x"
    assert item.value == 1
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    session.expunge.assert_not_called()


async def test_add_with_expunge_calls_expunge() -> None:
    repo = _ItemRepository()
    session = _make_session()

    item = await repo.add(session, _Item(name="y"), expunge=True)

    session.flush.assert_awaited_once()
    session.expunge.assert_called_once_with(item)


async def test_add_many_calls_add_all_and_optional_expunge() -> None:
    repo = _ItemRepository()
    session = _make_session()

    items = await repo.add_many(session, [{"name": "a"}, {"name": "b"}], expunge=True)

    assert len(items) == 2
    session.add_all.assert_called_once()
    session.flush.assert_awaited_once()
    assert session.expunge.call_count == 2


# --------------------------- get_one / get_one_by_id -------------------------


async def test_get_one_returns_none_when_no_record() -> None:
    repo = _ItemRepository()
    session = _make_session(scalar_one_or_none=None)

    result = await repo.get_one(session)

    assert result is None
    session.execute.assert_awaited_once()


async def test_get_one_returns_instance_and_expunges() -> None:
    expected = _Item(name="found")
    repo = _ItemRepository()
    session = _make_session(scalar_one_or_none=expected)

    result = await repo.get_one(session, expunge=True)

    assert result is expected
    session.expunge.assert_called_once_with(expected)


async def test_get_one_by_id_builds_filter_for_id_attribute() -> None:
    repo = _ItemRepository()
    session = _make_session(scalar_one_or_none=None)
    item_id = uuid.uuid4()

    await repo.get_one_by_id(session, item_id=item_id)

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": False}))
    assert "_unit_items.id" in compiled


# --------------------------------- count ------------------------------------


async def test_count_returns_scalar_one() -> None:
    repo = _ItemRepository()
    session = _make_session(scalar_one=42)

    total = await repo.count(session)

    assert total == 42


# ------------------------------ list_items ----------------------------------


async def test_list_items_returns_scalars_all() -> None:
    items = [_Item(name="a"), _Item(name="b")]
    repo = _ItemRepository()
    session = _make_session(scalars_all=items)

    result = await repo.list_items(session)

    assert list(result) == items
    assert session.expunge.call_count == 2


async def test_list_items_with_order_by_includes_order_clause() -> None:
    repo = _ItemRepository()
    session = _make_session(scalars_all=[])

    await repo.list_items(session, order_by=("name", True))

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile())
    assert "ORDER BY" in compiled
    assert "DESC" in compiled.upper()


# ---------------------------- list_and_count --------------------------------


async def test_list_and_count_short_circuits_on_zero() -> None:
    repo = _ItemRepository()
    session = _make_session(scalar_one=0, scalars_all=[])

    items, total = await repo.list_and_count(session)

    assert items == []
    assert total == 0
    # one execute for the count query, none for the list
    assert session.execute.await_count == 1


# -------------------------------- update ------------------------------------


async def test_update_returns_none_when_missing() -> None:
    """``update(dict)`` fast-path: a single ``UPDATE ... RETURNING`` that
    yields no rows must return ``None``."""
    repo = _ItemRepository()
    session = _make_session()
    empty_scalars = MagicMock()
    empty_scalars.one_or_none.return_value = None
    session.scalars = AsyncMock(return_value=empty_scalars)

    result = await repo.update(session, item_id=uuid.uuid4(), data={"name": "z"})

    assert result is None
    session.scalars.assert_awaited_once()
    # No load-mutate-merge round-trips should have fired on the fast path.
    session.merge.assert_not_awaited()
    session.flush.assert_not_awaited()


async def test_update_applies_dict_fields() -> None:
    """``update(dict)`` fast-path: returns the row from ``UPDATE ... RETURNING``
    in a single statement (no SELECT, no merge, no flush)."""
    existing = _Item(name="old", value=1)
    repo = _ItemRepository()
    session = _make_session()
    populated = MagicMock()
    populated.one_or_none.return_value = existing
    session.scalars = AsyncMock(return_value=populated)

    result = await repo.update(session, item_id=uuid.uuid4(), data={"name": "new", "value": 99})

    assert result is existing
    session.scalars.assert_awaited_once()
    session.merge.assert_not_awaited()
    session.flush.assert_not_awaited()


# -------------------------------- delete ------------------------------------


async def test_delete_returns_none_when_missing() -> None:
    repo = _ItemRepository()
    session = _make_session(scalar_one_or_none=None)

    result = await repo.delete(session, item_id=uuid.uuid4())

    assert result is None
    session.delete.assert_not_called()


async def test_delete_calls_session_delete_when_found() -> None:
    existing = _Item(name="bye")
    repo = _ItemRepository()
    session = _make_session(scalar_one_or_none=existing)

    result = await repo.delete(session, item_id=uuid.uuid4())

    assert result is existing
    session.delete.assert_awaited_once_with(existing)


# ---------------------- _build_match_filter helpers -------------------------


def test_build_match_filter_with_string_field() -> None:
    repo = _ItemRepository()
    out = repo._build_match_filter("name", {"name": "x", "value": 1})
    assert out == {"name": "x"}


def test_build_match_filter_drops_none_values() -> None:
    repo = _ItemRepository()
    out = repo._build_match_filter(["name", "value"], {"name": None, "value": 5})
    assert out == {"value": 5}


def test_build_match_filter_returns_kwargs_when_no_fields() -> None:
    repo = _ItemRepository()
    kwargs = {"a": 1, "b": 2}
    assert repo._build_match_filter(None, kwargs) == kwargs


# ------------------------- filter composition tests -------------------------


@pytest.mark.parametrize(
    "filter_obj,expected_fragment",
    [
        (LimitOffsetPaginationFilter(limit=5, offset=10), "LIMIT"),
        (OrderBy(field_name="name", direction="desc"), "ORDER BY"),
        (
            ComparisonFilter(field_name="value", operator="gt", value=3),
            "_unit_items.value >",
        ),
        (
            CollectionFilter(field_name="name", values=["a", "b"]),
            "IN (",
        ),
        (
            NotInCollectionFilter(field_name="name", values=["a"]),
            "NOT IN",
        ),
        (
            BeforeAfter(field_name="created_at", before=None, after=None),
            "_unit_items",
        ),
    ],
)
def test_apply_filter_composes_supported_filters(filter_obj, expected_fragment) -> None:
    repo = _ItemRepository()
    statement = repo.apply_filter(repo.statement, filter_obj)
    compiled = str(statement.compile())
    assert expected_fragment in compiled


def test_comparison_filter_invalid_operator_raises() -> None:
    repo = _ItemRepository()
    bad = ComparisonFilter(field_name="value", operator="bogus", value=1)
    with pytest.raises(ValueError, match="Invalid operator"):
        repo.apply_filter(repo.statement, bad)
