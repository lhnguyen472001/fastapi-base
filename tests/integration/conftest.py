"""Integration test fixtures: real Postgres via Testcontainers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from apps.core.database.registry import orm_registry

# Importing the models registers them with the shared metadata.
from tests.integration import _models  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    """Spin up a Postgres 16 container for the test session."""
    container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="session")
async def engine(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[AsyncEngine]:
    """Create an async engine bound to the test container."""
    url = postgres_container.get_connection_url()
    eng = create_async_engine(url, future=True)

    async with eng.begin() as conn:
        await conn.run_sync(orm_registry.metadata.create_all)

    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(orm_registry.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Per-test session. Truncates test tables after each test for isolation."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
        await sess.rollback()

    # Clean rows between tests; faster than create_all/drop_all per test
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE _test_widgets, _test_soft_widgets RESTART IDENTITY CASCADE"))


@pytest.fixture
def widget_repo():
    from tests.integration._models import WidgetRepository

    return WidgetRepository()


@pytest.fixture
def soft_widget_repo():
    from tests.integration._models import SoftWidgetRepository

    return SoftWidgetRepository()


__all__ = ["engine", "postgres_container", "session", "soft_widget_repo", "widget_repo"]
_ = cast  # silence unused import warnings if any
