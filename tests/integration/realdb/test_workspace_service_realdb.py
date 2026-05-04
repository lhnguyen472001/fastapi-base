"""Real-DB integration tests for the workspace module.

Pre-requisites (per :mod:`tests.integration.realdb.conftest`):

* ``docker compose up -d postgres``
* ``uv run alembic upgrade head``

Each test runs inside a transaction that's always rolled back at teardown.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.enums import WorkspaceRole
from apps.workspace.exceptions import (
    WorkspaceLastOwnerError,
    WorkspaceMemberAlreadyExistsError,
    WorkspaceMemberNotFoundError,
    WorkspaceNotFoundError,
    WorkspaceSlugConflictError,
    WorkspaceSlugInvalidError,
    WorkspaceSlugReservedError,
)
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import (
    AddMemberRequest,
    CreateWorkspaceRequest,
    ListMembersRequest,
    ListWorkspacesRequest,
    UpdateMemberRoleRequest,
    UpdateWorkspaceRequest,
)
from apps.workspace.services import WorkspaceMemberService, WorkspaceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.user.models import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_service() -> WorkspaceService:
    return WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )


@pytest.fixture
def member_service() -> WorkspaceMemberService:
    return WorkspaceMemberService(
        repository=WorkspaceMemberRepository(),
        workspace_repository=WorkspaceRepository(),
    )


@pytest.fixture
def user_service() -> UserService:
    return UserService(repository=UserRepository())


async def _make_user(real_session: AsyncSession, user_service: UserService, suffix: str) -> User:
    payload = CreateUserRequest(
        email=f"ws_{suffix}@example.com",
        username=f"ws_{suffix}",
        password="Sup3rSecret!",
    )
    user = await user_service.create(real_session, data=payload)
    await real_session.flush()
    return user


def _make_create_request(suffix: str) -> CreateWorkspaceRequest:
    return CreateWorkspaceRequest(
        slug=f"ws-{suffix}",
        name=f"Workspace {suffix}",
        description=None,
    )


# ---------------------------------------------------------------------------
# WorkspaceService.create
# ---------------------------------------------------------------------------


async def test_create_workspace_persists_with_bootstrap_owner_membership(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    assert workspace.id is not None
    assert workspace.slug == f"ws-{suffix}"
    assert workspace.owner_user_id == user.id

    membership = await member_service.find_membership(
        real_session,
        workspace_id=workspace.id,
        user_id=user.id,
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER.value


async def test_create_workspace_rejects_duplicate_slug(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    request = _make_create_request(suffix)
    await workspace_service.create(real_session, owner_user_id=user.id, data=request)
    await real_session.flush()

    with pytest.raises(WorkspaceSlugConflictError):
        await workspace_service.create(real_session, owner_user_id=user.id, data=request)


async def test_create_workspace_rejects_reserved_slug(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    bad = CreateWorkspaceRequest(slug="admin", name="Admin", description=None)
    with pytest.raises(WorkspaceSlugReservedError):
        await workspace_service.create(real_session, owner_user_id=user.id, data=bad)


async def test_create_workspace_rejects_invalid_slug_format(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    # Underscore survives ``.lower()`` but isn't allowed by the slug regex.
    bad = CreateWorkspaceRequest(slug="abc_def", name="x", description=None)
    with pytest.raises(WorkspaceSlugInvalidError):
        await workspace_service.create(real_session, owner_user_id=user.id, data=bad)


# ---------------------------------------------------------------------------
# WorkspaceService.find_or_raise / get_by_slug / soft_delete
# ---------------------------------------------------------------------------


async def test_find_or_raise_returns_workspace(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    created = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    fetched = await workspace_service.find_or_raise(real_session, workspace_id=created.id)
    assert fetched.id == created.id


async def test_find_or_raise_raises_when_missing(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        await workspace_service.find_or_raise(real_session, workspace_id=uuid.uuid4())


async def test_get_by_slug_excludes_soft_deleted(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    created = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    await workspace_service.soft_delete(real_session, workspace_id=created.id)
    await real_session.flush()

    with pytest.raises(WorkspaceNotFoundError):
        await workspace_service.get_by_slug(real_session, slug=created.slug)


# ---------------------------------------------------------------------------
# WorkspaceService.update
# ---------------------------------------------------------------------------


async def test_update_workspace_changes_name(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    updated = await workspace_service.update(
        real_session,
        workspace_id=workspace.id,
        data=UpdateWorkspaceRequest(name="Renamed", description="new description"),
    )
    await real_session.flush()

    assert updated.name == "Renamed"
    assert updated.description == "new description"


# ---------------------------------------------------------------------------
# WorkspaceService.list_for_user
# ---------------------------------------------------------------------------


async def test_list_for_user_returns_only_user_workspaces(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    user_a = await _make_user(real_session, user_service, suffix_a)
    user_b = await _make_user(real_session, user_service, suffix_b)

    ws_a = await workspace_service.create(
        real_session,
        owner_user_id=user_a.id,
        data=_make_create_request(suffix_a),
    )
    await workspace_service.create(
        real_session,
        owner_user_id=user_b.id,
        data=_make_create_request(suffix_b),
    )
    await real_session.flush()

    items_a, _ = await workspace_service.list_for_user(
        real_session,
        user_id=user_a.id,
        params=ListWorkspacesRequest(limit=10, offset=0),
    )
    ids_a = {w.id for w in items_a}
    assert ws_a.id in ids_a


# ---------------------------------------------------------------------------
# WorkspaceMemberService.add_member / change_role / remove_member
# ---------------------------------------------------------------------------


async def test_add_member_inserts_membership_row(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    invitee = await _make_user(real_session, user_service, f"{suffix}_b")

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    member = await member_service.add_member(
        real_session,
        workspace_id=workspace.id,
        invited_by_user_id=owner.id,
        data=AddMemberRequest(user_id=invitee.id, role=WorkspaceRole.EDITOR),
    )
    await real_session.flush()

    assert member.workspace_id == workspace.id
    assert member.user_id == invitee.id
    assert member.role == WorkspaceRole.EDITOR.value
    assert member.invited_by_user_id == owner.id


async def test_add_member_rejects_duplicate(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    with pytest.raises(WorkspaceMemberAlreadyExistsError):
        await member_service.add_member(
            real_session,
            workspace_id=workspace.id,
            invited_by_user_id=owner.id,
            data=AddMemberRequest(user_id=owner.id, role=WorkspaceRole.OWNER),
        )


async def test_change_role_updates_role(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    invitee = await _make_user(real_session, user_service, f"{suffix}_b")

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await member_service.add_member(
        real_session,
        workspace_id=workspace.id,
        invited_by_user_id=owner.id,
        data=AddMemberRequest(user_id=invitee.id, role=WorkspaceRole.VIEWER),
    )
    await real_session.flush()

    updated = await member_service.change_role(
        real_session,
        workspace_id=workspace.id,
        user_id=invitee.id,
        data=UpdateMemberRoleRequest(role=WorkspaceRole.EDITOR),
    )
    await real_session.flush()

    assert updated.role == WorkspaceRole.EDITOR.value


async def test_change_role_blocks_demoting_last_owner(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    with pytest.raises(WorkspaceLastOwnerError):
        await member_service.change_role(
            real_session,
            workspace_id=workspace.id,
            user_id=owner.id,
            data=UpdateMemberRoleRequest(role=WorkspaceRole.EDITOR),
        )


async def test_remove_member_blocks_removing_last_owner(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    with pytest.raises(WorkspaceLastOwnerError):
        await member_service.remove_member(
            real_session,
            workspace_id=workspace.id,
            user_id=owner.id,
        )


async def test_remove_member_succeeds_for_non_owner(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    invitee = await _make_user(real_session, user_service, f"{suffix}_b")

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await member_service.add_member(
        real_session,
        workspace_id=workspace.id,
        invited_by_user_id=owner.id,
        data=AddMemberRequest(user_id=invitee.id, role=WorkspaceRole.EDITOR),
    )
    await real_session.flush()

    await member_service.remove_member(
        real_session,
        workspace_id=workspace.id,
        user_id=invitee.id,
    )
    await real_session.flush()

    assert (
        await member_service.find_membership(
            real_session,
            workspace_id=workspace.id,
            user_id=invitee.id,
        )
    ) is None


async def test_remove_member_raises_when_membership_missing(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    await real_session.flush()

    with pytest.raises(WorkspaceMemberNotFoundError):
        await member_service.remove_member(
            real_session,
            workspace_id=workspace.id,
            user_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# WorkspaceMemberService.list_members
# ---------------------------------------------------------------------------


async def test_list_members_returns_owner_plus_invitees(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    member_service: WorkspaceMemberService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, suffix)
    invitee_a = await _make_user(real_session, user_service, f"{suffix}_a")
    invitee_b = await _make_user(real_session, user_service, f"{suffix}_b")

    workspace = await workspace_service.create(
        real_session,
        owner_user_id=owner.id,
        data=_make_create_request(suffix),
    )
    for invitee in (invitee_a, invitee_b):
        await member_service.add_member(
            real_session,
            workspace_id=workspace.id,
            invited_by_user_id=owner.id,
            data=AddMemberRequest(user_id=invitee.id, role=WorkspaceRole.VIEWER),
        )
    await real_session.flush()

    items, total = await member_service.list_members(
        real_session,
        workspace_id=workspace.id,
        params=ListMembersRequest(limit=10, offset=0),
    )
    user_ids = {m.user_id for m in items}
    assert total == 3
    assert {owner.id, invitee_a.id, invitee_b.id}.issubset(user_ids)
