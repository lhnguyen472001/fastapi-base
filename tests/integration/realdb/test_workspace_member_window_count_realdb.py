"""Integration test for the window-function refactor of list_members (F-PERF-2).

The pre-change ``WorkspaceMemberRepository.list_members`` ran two
separate queries — ``COUNT(*)`` then ``SELECT ... LIMIT/OFFSET``. After
the F-PERF-2 refactor it routes through
``BaseSQLAlchemyRepository.list_and_count(..., using_window_function=True)``
which collapses both into a single statement via ``COUNT(*) OVER ()``.

The assertion uses SQLAlchemy's ``after_cursor_execute`` event to count
statements executed on the session's connection during the call.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac import models as _rbac_models  # noqa: F401  (registers Casbin / Role tables)
from apps.user.repositories import UserRepository
from apps.workspace.enums import WorkspaceRole
from apps.workspace.repositories import (
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService


def _short() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_workspace_with_members(real_session: AsyncSession, member_count: int) -> uuid.UUID:
    user_repo = UserRepository()
    workspace_service = WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )

    suffix = _short()
    owner = await user_repo.add(
        real_session,
        {
            "email": f"win_owner_{suffix}@example.com",
            "username": f"win_owner_{suffix}",
            "hashed_password": "x" * 60,
            "is_active": True,
        },
        expunge=False,
    )
    await real_session.flush()
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=CreateWorkspaceRequest(slug=f"win-{suffix}", name=f"Win {suffix}", description=None),
    )
    await real_session.flush()

    member_repo = WorkspaceMemberRepository()
    for index in range(member_count):
        member_user = await user_repo.add(
            real_session,
            {
                "email": f"win_member_{suffix}_{index}@example.com",
                "username": f"win_member_{suffix}_{index}",
                "hashed_password": "x" * 60,
                "is_active": True,
            },
            expunge=False,
        )
        await real_session.flush()
        await member_repo.add(
            real_session,
            {
                "workspace_id": workspace.id,
                "user_id": member_user.id,
                "role": WorkspaceRole.EDITOR.value,
            },
            expunge=False,
        )
        await real_session.flush()
    return workspace.id


async def test_list_members_issues_exactly_one_statement(real_session: AsyncSession) -> None:
    """After F-PERF-2 the page + count fold into one SELECT (window function)."""
    workspace_id = await _seed_workspace_with_members(real_session, member_count=3)

    statements: list[str] = []
    connection = await real_session.connection()

    @event.listens_for(connection.sync_connection, "after_cursor_execute")
    def _capture(_conn, _cursor, statement: str, _params, _context, _executemany) -> None:
        # Only count SELECTs against the workspace_members table; ignore
        # SAVEPOINT / RELEASE / unrelated chatter.
        lowered = statement.lower()
        if "workspace_members" in lowered and "select" in lowered:
            statements.append(statement)

    member_repo = WorkspaceMemberRepository()
    # Filter by EDITOR so we count only the rows the seeder explicitly
    # inserted; create() also writes an implicit OWNER membership for
    # the workspace creator.
    rows, total = await member_repo.list_members(
        real_session,
        workspace_id=workspace_id,
        role=WorkspaceRole.EDITOR,
        limit=10,
        offset=0,
    )

    assert len(rows) == 3
    assert total == 3
    assert len(statements) == 1, (
        f"list_members must issue exactly one statement (got {len(statements)}): {[s[:120] for s in statements]}"
    )
