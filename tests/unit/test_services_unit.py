"""Unit tests for SQLAlchemyService layer using a mock repository.

These verify the read/write/upsert delegation, ResultConverter wiring,
and schema conversion paths without touching a database.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.schemas.base import BaseObjectSchema
from apps.core.services.base import (
    SQLAlchemyReadService,
    SQLAlchemyService,
    SQLAlchemyWriteService,
)
from apps.core.services.utils import ResultConverter


class _DummyModel:
    def __init__(self, id: uuid.UUID | None = None, name: str = "x", value: int = 0) -> None:
        self.id = id or uuid.uuid4()
        self.name = name
        self.value = value


class _DummySchema(BaseObjectSchema):
    id: uuid.UUID
    name: str
    value: int


@pytest.fixture
def repo() -> AsyncMock:
    """Mock repository covering every method the service touches."""
    r = AsyncMock()
    r.get_one_by_id = AsyncMock()
    r.get_one = AsyncMock()
    r.list_items = AsyncMock()
    r.list_and_count = AsyncMock()
    r.add = AsyncMock()
    r.add_many = AsyncMock()
    r.update = AsyncMock()
    r.delete = AsyncMock()
    r.delete_where = AsyncMock()
    r.get_or_upsert = AsyncMock()
    return r


@pytest.fixture
def session() -> MagicMock:
    """A spec'd AsyncSession that satisfies @transactional's isinstance check.

    `in_transaction()` returns True so the decorator joins the (fake) outer
    transaction instead of trying to open a real one against a mock.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    sess = MagicMock(spec=AsyncSession, name="AsyncSession")
    sess.in_transaction.return_value = True
    return sess


# -------------------------------- read --------------------------------------


async def test_get_by_id_returns_model_when_no_schema(repo, session) -> None:
    model = _DummyModel(name="alice")
    repo.get_one_by_id.return_value = model
    svc = SQLAlchemyReadService(repository=repo)

    result = await svc.get_by_id(session, item_id=model.id)

    assert result is model
    repo.get_one_by_id.assert_awaited_once_with(session, item_id=model.id, expunge=True)


async def test_get_by_id_converts_to_schema(repo, session) -> None:
    model = _DummyModel(name="alice", value=7)
    repo.get_one_by_id.return_value = model
    svc = SQLAlchemyReadService(repository=repo)

    result = await svc.get_by_id(session, item_id=model.id, schema_type=_DummySchema)

    assert isinstance(result, _DummySchema)
    assert result.name == "alice"
    assert result.value == 7


async def test_get_by_id_returns_none_when_repo_returns_none(repo, session) -> None:
    repo.get_one_by_id.return_value = None
    svc = SQLAlchemyReadService(repository=repo)

    assert await svc.get_by_id(session, item_id=uuid.uuid4(), schema_type=_DummySchema) is None


async def test_list_items_with_no_filters_passes_empty_list(repo, session) -> None:
    repo.list_items.return_value = [_DummyModel(name="a"), _DummyModel(name="b")]
    svc = SQLAlchemyReadService(repository=repo)

    result = await svc.list_items(session)

    assert len(result) == 2
    repo.list_items.assert_awaited_once_with(session)


async def test_list_items_with_sequence_filters_passes_through(repo, session) -> None:
    repo.list_items.return_value = []
    svc = SQLAlchemyReadService(repository=repo)
    sentinel = MagicMock(name="filter")

    await svc.list_items(session, filters=[sentinel])

    repo.list_items.assert_awaited_once_with(session, sentinel)


async def test_list_items_converts_to_schema(repo, session) -> None:
    repo.list_items.return_value = [
        _DummyModel(name="a", value=1),
        _DummyModel(name="b", value=2),
    ]
    svc = SQLAlchemyReadService(repository=repo)

    result = await svc.list_items(session, schema_type=_DummySchema)

    assert all(isinstance(item, _DummySchema) for item in result)
    assert [r.name for r in result] == ["a", "b"]


async def test_list_with_count_returns_tuple(repo, session) -> None:
    repo.list_and_count.return_value = ([_DummyModel(name="a", value=0)], 1)
    svc = SQLAlchemyReadService(repository=repo)

    items, total = await svc.list_with_count(session, schema_type=_DummySchema)

    assert total == 1
    assert items[0].name == "a"


# -------------------------------- write -------------------------------------


async def test_create_calls_repository_add_and_converts(repo, session) -> None:
    repo.add.return_value = _DummyModel(name="new", value=3)
    svc = SQLAlchemyWriteService(repository=repo)

    out = await svc.create(session, data={"name": "new", "value": 3}, schema_type=_DummySchema)

    repo.add.assert_awaited_once()
    assert isinstance(out, _DummySchema)
    assert out.name == "new"


async def test_create_many_calls_add_many(repo, session) -> None:
    models = [_DummyModel(name="a", value=1), _DummyModel(name="b", value=2)]
    repo.add_many.return_value = models
    svc = SQLAlchemyWriteService(repository=repo)

    out = await svc.create_many(
        session,
        data=[{"name": "a", "value": 1}, {"name": "b", "value": 2}],
        schema_type=_DummySchema,
    )

    repo.add_many.assert_awaited_once()
    assert len(out) == 2


async def test_update_returns_none_when_not_found(repo, session) -> None:
    repo.update.return_value = None
    svc = SQLAlchemyWriteService(repository=repo)

    result = await svc.update(session, item_id=uuid.uuid4(), data={"name": "x"})

    assert result is None


async def test_update_with_schema_dict_dump(repo, session) -> None:
    model = _DummyModel(name="updated", value=9)
    repo.update.return_value = model
    svc = SQLAlchemyWriteService(repository=repo)

    out = await svc.update(session, item_id=model.id, data={"name": "updated"}, schema_type=_DummySchema)

    assert isinstance(out, _DummySchema)
    assert out.name == "updated"


async def test_upsert_returns_was_created_flag(repo, session) -> None:
    model = _DummyModel(name="x", value=0)
    repo.get_or_upsert.return_value = (model, True)
    svc = SQLAlchemyWriteService(repository=repo)

    obj, was_created = await svc.upsert(
        session,
        data={"name": "x", "value": 0},
        match_fields="name",
        schema_type=_DummySchema,
    )

    assert was_created is True
    assert isinstance(obj, _DummySchema)


async def test_delete_passes_through(repo, session) -> None:
    model = _DummyModel(name="bye")
    repo.delete.return_value = model
    svc = SQLAlchemyWriteService(repository=repo)

    out = await svc.delete(session, item_id=model.id)

    assert out is model
    repo.delete.assert_awaited_once_with(session, model.id)


async def test_delete_where_passes_filters(repo, session) -> None:
    repo.delete_where.return_value = []
    svc = SQLAlchemyWriteService(repository=repo)
    sentinel = MagicMock()

    await svc.delete_where(session, sentinel)

    repo.delete_where.assert_awaited_once_with(session, sentinel)


# ----------------------------- combined service -----------------------------


async def test_sqlalchemy_service_supports_read_and_write(repo, session) -> None:
    repo.get_one_by_id.return_value = _DummyModel(name="combined", value=1)
    repo.add.return_value = _DummyModel(name="combined", value=1)
    svc = SQLAlchemyService(repository=repo)

    fetched = await svc.get_by_id(session, item_id=uuid.uuid4())
    created = await svc.create(session, data={"name": "combined", "value": 1})

    assert fetched.name == "combined"
    assert created.name == "combined"


# ------------------------------ ResultConverter -----------------------------


def test_result_converter_none_returns_none() -> None:
    rc = ResultConverter()
    assert rc.to_schema(None) is None


def test_result_converter_no_schema_returns_input() -> None:
    rc = ResultConverter()
    obj = _DummyModel(name="x")
    assert rc.to_schema(obj) is obj


def test_result_converter_single_object_to_schema() -> None:
    rc = ResultConverter()
    out = rc.to_schema(_DummyModel(name="a", value=1), schema_type=_DummySchema)
    assert isinstance(out, _DummySchema)
    assert out.name == "a"


def test_result_converter_bulk_to_schema() -> None:
    rc = ResultConverter()
    out = rc.to_schema(
        [_DummyModel(name="a", value=1), _DummyModel(name="b", value=2)],
        schema_type=_DummySchema,
    )
    assert len(out) == 2
    assert all(isinstance(item, _DummySchema) for item in out)


def test_result_converter_paginated_response() -> None:
    from apps.core.database.filters import LimitOffsetPaginationFilter
    from apps.core.schemas.response import PaginatedResponse

    rc = ResultConverter()
    paginated = rc.to_schema(
        [_DummyModel(name="a", value=1)],
        total=10,
        pagination_filter=LimitOffsetPaginationFilter(limit=5, offset=0),
        schema_type=_DummySchema,
    )
    assert isinstance(paginated, PaginatedResponse)
    assert paginated.total == 10
    assert paginated.limit == 5
    assert len(paginated.items) == 1


# --------------------- BaseSQLAlchemyService._get_or_raise ------------------


class _NotFoundError(Exception):
    """Domain-style error mirroring the BackendError contract for tests."""

    def __init__(self, *, code: str = "TEST001", status_code: int = 404, message: str) -> None:
        self.code = code
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _make_service_with_repo(found_value: object | None) -> SQLAlchemyService:
    repo = AsyncMock()
    repo.get_one_by_id = AsyncMock(return_value=found_value)
    return SQLAlchemyService(repository=repo)


@pytest.mark.asyncio
async def test_get_or_raise_returns_found_instance() -> None:
    target = _DummyModel(name="ok")
    service = _make_service_with_repo(target)

    result = await service._get_or_raise(
        AsyncMock(),
        item_id=target.id,
        error_cls=_NotFoundError,
    )

    assert result is target


@pytest.mark.asyncio
async def test_get_or_raise_raises_supplied_error_when_missing() -> None:
    service = _make_service_with_repo(None)

    with pytest.raises(_NotFoundError) as exc_info:
        await service._get_or_raise(
            AsyncMock(),
            item_id=uuid.uuid4(),
            error_cls=_NotFoundError,
            message="custom message",
        )

    assert exc_info.value.message == "custom message"


@pytest.mark.asyncio
async def test_get_or_raise_default_message_includes_id() -> None:
    service = _make_service_with_repo(None)
    fake_id = "abc"

    with pytest.raises(_NotFoundError) as exc_info:
        await service._get_or_raise(
            AsyncMock(),
            item_id=fake_id,
            error_cls=_NotFoundError,
        )

    assert "abc" in exc_info.value.message
    assert "not found" in exc_info.value.message
