"""End-to-end regression for the RoutingSession flush bind.

The bug: a session that begins with a SELECT binds to the reader engine
for the rest of its flush-time INSERTs, because
``Session.flush()`` calls ``get_bind(mapper=..., clause=None)`` (no
clause). A later ``session.execute(Update(...))`` carries an Update
clause and dispatches to the writer — a different physical connection,
on a different transaction. UPDATEs whose new column values reference
rows the flush just inserted then fail with
``ForeignKeyViolationError``.

The realistic trigger is :meth:`TokenService.refresh`, which:
  1. SELECTs the incoming refresh token (reader),
  2. flushes a new refresh-token row (was reader: bug; fixed: writer),
  3. UPDATEs the old row's ``replaced_by_id`` to the new row's id
     (writer).

This test reproduces (1)-(3) using the production
:class:`RoutingSession` via :data:`async_session_factory` and asserts
the rotation completes without an FK violation.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import delete, select, text

import apps.user.models  # noqa: F401  (registers the User mapper)
from apps.auth.models import RefreshToken
from apps.auth.repository import RefreshTokenRepository
from apps.core.database.session import async_session_factory
from apps.user.models import User


def _expiry() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)


@pytest.mark.asyncio
async def test_flush_after_initial_select_routes_to_writer() -> None:
    repo = RefreshTokenRepository()
    tag = uuid.uuid4().hex
    user_id: uuid.UUID | None = None
    old_id: uuid.UUID | None = None

    try:
        async with async_session_factory() as seed_session:
            user = User(
                email=f"routing-{tag}@example.invalid",
                username=f"routing-{tag}",
                hashed_password="!",
            )
            seed_session.add(user)
            await seed_session.flush()
            user_id = user.id

            old = RefreshToken(
                user_id=user_id,
                token_hash=("r" + tag).ljust(64, "r")[:64],
                expires_at=_expiry(),
            )
            seed_session.add(old)
            await seed_session.flush()
            old_id = old.id
            await seed_session.commit()

        async with async_session_factory() as session:
            # 1. SELECT first — binds the session to the reader engine.
            loaded = (await session.execute(select(RefreshToken).where(RefreshToken.id == old_id))).scalar_one()
            assert loaded.id == old_id

            # 2. Flush an INSERT via the repository — the bug path.
            new_row = RefreshToken(
                user_id=loaded.user_id,
                token_hash=("s" + tag).ljust(64, "s")[:64],
                expires_at=_expiry(),
            )
            new_row = await repo.add(session, new_row, expunge=False)

            # 3. UPDATE the old row's FK to the just-inserted new row's id.
            #    Previously raised ForeignKeyViolationError because the
            #    INSERT lived on the reader connection while this UPDATE
            #    landed on a fresh writer connection.
            await repo.update(
                session,
                item_id=loaded.id,
                data={
                    "revoked_at": datetime.datetime.now(datetime.UTC),
                    "replaced_by_id": new_row.id,
                },
            )

            await session.commit()

        async with async_session_factory() as verify_session:
            row = (await verify_session.execute(select(RefreshToken).where(RefreshToken.id == old_id))).scalar_one()
            assert row.revoked_at is not None
            assert row.replaced_by_id is not None
    finally:
        async with async_session_factory() as cleanup_session:
            await cleanup_session.execute(delete(RefreshToken).where(RefreshToken.token_hash.like(f"%{tag}%")))
            if user_id is not None:
                await cleanup_session.execute(
                    text("DELETE FROM users WHERE id = :uid"),
                    {"uid": str(user_id)},
                )
            await cleanup_session.commit()
