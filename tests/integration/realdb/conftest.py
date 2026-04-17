"""Fixtures targeting the real Postgres in compose.yml.

Pre-requisites:
    docker compose up -d postgres
    uv run alembic upgrade head

Tables (`users`, `refresh_tokens`) must already exist via Alembic migrations.
Each test runs inside a transaction that is rolled back at teardown so the
database stays clean across runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from apps.auth import models as _auth_models  # noqa: F401  (registers RefreshToken)
from apps.settings import app_settings
from apps.user import models as _user_models  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest_asyncio.fixture(scope="session")
async def real_engine() -> AsyncGenerator[AsyncEngine]:
    """Async engine pointing to the live compose Postgres."""
    url = app_settings.db.database_uri.render_as_string(hide_password=False)
    eng = create_async_engine(url, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def real_session(real_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Open a session bound to a savepoint that is always rolled back."""
    connection = await real_engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
    sess = factory()
    try:
        yield sess
    finally:
        await sess.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
