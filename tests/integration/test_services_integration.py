"""Integration tests for SQLAlchemyService against a real Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest_asyncio

from apps.core.database.filters import ComparisonFilter
from apps.core.schemas.base import BaseObjectSchema
from apps.core.services.base import SQLAlchemyService
from tests.integration._models import Widget, WidgetRepository


class WidgetSchema(BaseObjectSchema):
    id: uuid.UUID
    name: str
    quantity: int
    is_featured: bool
    created_at: datetime
    updated_at: datetime


class WidgetService(SQLAlchemyService[Widget]):
    """Concrete service for Widget."""


@pytest_asyncio.fixture
async def widget_service():
    return WidgetService(repository=WidgetRepository())


# Note: WriteService.create / create_many / upsert are wrapped with @transactional
# which calls the global scoped_session. We bypass them here and exercise the
# read paths plus update/delete which don't require the global session.


async def test_get_by_id_returns_schema(session, widget_service, widget_repo) -> None:
    item = await widget_repo.add(session, {"name": "abc", "quantity": 5}, expunge=False)
    await session.commit()

    result = await widget_service.get_by_id(session, item_id=item.id, schema_type=WidgetSchema)

    assert isinstance(result, WidgetSchema)
    assert result.name == "abc"
    assert result.quantity == 5


async def test_get_by_id_returns_none_when_missing(session, widget_service) -> None:
    result = await widget_service.get_by_id(session, item_id=uuid.uuid4())
    assert result is None


async def test_list_items_returns_schemas(session, widget_service, widget_repo) -> None:
    for i in range(3):
        await widget_repo.add(session, {"name": f"n{i}", "quantity": i}, expunge=False)
    await session.commit()

    items = await widget_service.list_items(session, schema_type=WidgetSchema)

    assert len(items) == 3
    assert all(isinstance(i, WidgetSchema) for i in items)


async def test_list_items_with_statement_filters(session, widget_service, widget_repo) -> None:
    for i in range(5):
        await widget_repo.add(session, {"name": f"n{i}", "quantity": i}, expunge=False)
    await session.commit()

    items = await widget_service.list_items(
        session,
        filters=[ComparisonFilter(field_name="quantity", operator="ge", value=3)],
        schema_type=WidgetSchema,
    )

    assert sorted(i.quantity for i in items) == [3, 4]


async def test_list_with_count(session, widget_service, widget_repo) -> None:
    for i in range(4):
        await widget_repo.add(session, {"name": f"n{i}", "quantity": i}, expunge=False)
    await session.commit()

    items, total = await widget_service.list_with_count(session, schema_type=WidgetSchema)

    assert total == 4
    assert len(items) == 4


async def test_update_returns_schema(session, widget_service, widget_repo) -> None:
    item = await widget_repo.add(session, {"name": "before", "quantity": 1}, expunge=False)
    await session.commit()

    result = await widget_service.update(session, item_id=item.id, data={"name": "after"}, schema_type=WidgetSchema)
    await session.commit()

    assert isinstance(result, WidgetSchema)
    assert result.name == "after"


async def test_delete_removes_row(session, widget_service, widget_repo) -> None:
    item = await widget_repo.add(session, {"name": "doomed"}, expunge=False)
    await session.commit()

    result = await widget_service.delete(session, item_id=item.id)
    await session.commit()

    assert result is not None
    assert await widget_repo.get_one_by_id(session, item_id=item.id) is None


async def test_delete_where_via_service(session, widget_service, widget_repo) -> None:
    for i in range(5):
        await widget_repo.add(session, {"name": f"n{i}", "quantity": i}, expunge=False)
    await session.commit()

    deleted = await widget_service.delete_where(
        session, ComparisonFilter(field_name="quantity", operator="lt", value=2)
    )
    await session.commit()

    assert deleted is not None
    assert len(deleted) == 2
    assert await widget_repo.count(session) == 3
