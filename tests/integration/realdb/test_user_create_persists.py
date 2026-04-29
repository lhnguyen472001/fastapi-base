"""Regression test for the request-scoped session commit contract.

A previous version of the codebase ran ``scoped_session.remove()`` from a
``BaseHTTPMiddleware.dispatch`` finally block, which fired BEFORE FastAPI
tore down the ``session_factory`` generator dependency. The session was
closed (and the connection rolled back by the asyncpg pool reset) before
the dependency could commit, so successful POSTs returned 201 with an ``id``
yet the row was never persisted.

This test drives the real FastAPI app through ``httpx.ASGITransport`` and
then opens a fresh ``AsyncSession`` to confirm the row is visible. A test
that shared a session with the request would not detect the bug.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.factory import app
from apps.user.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_post_users_persists_visible_from_fresh_session(
    real_engine: AsyncEngine,
) -> None:
    """POST /api/v1/users → row must be visible from a fresh session."""
    suffix = uuid.uuid4().hex[:10]
    payload = {
        "email": f"persist-{suffix}@example.com",
        "username": f"persist{suffix}",
        "password": "Pwd12345!",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/users", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    created_id = uuid.UUID(body["data"]["id"])

    factory = async_sessionmaker(real_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as fresh:
        row = await fresh.scalar(select(User).where(User.id == created_id))
        try:
            assert row is not None, "user row was never committed"
            assert row.email == payload["email"]
            assert row.username == payload["username"]
        finally:
            if row is not None:
                await fresh.delete(row)
                await fresh.commit()


@pytest.mark.asyncio
async def test_post_users_rolls_back_on_duplicate_username(
    real_engine: AsyncEngine,
) -> None:
    """A second POST with the same username must not leave a partial row.

    Locks in the rollback half of the commit contract: when the service
    raises after the first row is created, the duplicate request must not
    persist.
    """
    suffix = uuid.uuid4().hex[:10]
    payload = {
        "email": f"dup-{suffix}@example.com",
        "username": f"dup{suffix}",
        "password": "Pwd12345!",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/users", json=payload)
        assert first.status_code == 201, first.text

        second_payload = {**payload, "email": f"other-{suffix}@example.com"}
        second = await client.post("/api/v1/users", json=second_payload)

    assert second.status_code in {409, 400, 422}, second.text

    factory = async_sessionmaker(real_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as fresh:
        count = await fresh.scalar(
            select(func.count()).select_from(User).where(User.username == payload["username"]),
        )
        assert count == 1, f"expected exactly one row for username, got {count}"

        row = await fresh.scalar(select(User).where(User.username == payload["username"]))
        if row is not None:
            await fresh.delete(row)
            await fresh.commit()
