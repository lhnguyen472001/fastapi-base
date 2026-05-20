"""Unit tests for CRITICAL-2: group-role fan-out pages through membership.

``UserGroupRepository.list_active_user_ids`` was unbounded; a 100k-member
group would allocate the full id list in worker memory inside the
transaction. The fix makes the method opt-in paginated and pages the
fan-out caller (``GroupService._db_assign_role_to_group``) through the
membership in batches of ``RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE`` rows.

These tests pin the new behaviour:

* Default ``limit=None`` preserves the historical fetch-all contract.
* When called with ``limit`` it adds ``LIMIT/OFFSET`` to the SELECT.
* The fan-out caller iterates with paginated kwargs and accumulates
  every member into the final Casbin rule list — so the policy-sync
  semantics are unchanged for any group size.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac.constants import RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE
from apps.rbac.repositories import UserGroupRepository
from apps.rbac.services._group import GroupService


def _fake_session() -> MagicMock:
    """``@transactional`` checks ``isinstance(session, AsyncSession)`` and then
    ``await session.in_transaction()`` / ``async with session.begin()``. A
    ``spec=AsyncSession`` mock satisfies the isinstance check; we explicitly
    short-circuit ``in_transaction`` to True so the wrapper does not try to
    open a real transaction."""
    session = MagicMock(spec=AsyncSession)
    session.in_transaction = MagicMock(return_value=True)
    return session


def test_repository_signature_is_opt_in_paginated() -> None:
    sig = inspect.signature(UserGroupRepository.list_active_user_ids)
    assert sig.parameters["limit"].default is None
    assert sig.parameters["offset"].default == 0


def test_constant_is_positive_int() -> None:
    assert isinstance(RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE, int)
    assert RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE > 0


def _make_group_service(*, paginated_batches: list[list[uuid.UUID]]) -> tuple[GroupService, AsyncMock, MagicMock]:
    """Build a ``GroupService`` whose ``user_group_repository.list_active_user_ids``
    returns each successive batch in ``paginated_batches`` per call."""
    repository = MagicMock(name="GroupRepository")
    repository.get_one_by_id = AsyncMock(return_value=MagicMock(name="Group", id=42))

    role_repository = MagicMock(name="RoleRepository")
    role_repository.get_one_by_id = AsyncMock(return_value=MagicMock(name="Role", id=7))

    user_group_repository = MagicMock(name="UserGroupRepository")
    list_calls = AsyncMock(side_effect=paginated_batches)
    user_group_repository.list_active_user_ids = list_calls

    group_role_repository = MagicMock(name="GroupRoleRepository")
    group_role_repository.add = AsyncMock(return_value=MagicMock(name="GroupRole", id=999))

    enforcer = MagicMock(name="Enforcer")

    service = GroupService(
        repository=repository,
        role_repository=role_repository,
        user_group_repository=user_group_repository,
        group_role_repository=group_role_repository,
        enforcer=enforcer,
    )
    return service, list_calls, group_role_repository


@pytest.mark.asyncio
async def test_db_assign_role_to_group_pages_through_membership() -> None:
    """A 3-page result set must produce exactly 3 paginated calls and a
    rules list that covers every member across the pages."""
    batch_size = RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE
    page_1 = [uuid.uuid4() for _ in range(batch_size)]
    page_2 = [uuid.uuid4() for _ in range(batch_size)]
    page_3 = [uuid.uuid4() for _ in range(7)]  # short page → loop exits

    service, list_calls, _ = _make_group_service(paginated_batches=[page_1, page_2, page_3])

    session = _fake_session()
    _, rules = await service._db_assign_role_to_group(
        session,
        group_id=42,
        role_id=7,
        assigned_by=None,
    )

    assert list_calls.await_count == 3
    expected_offsets = [0, batch_size, 2 * batch_size]
    actual_offsets = [call.kwargs["offset"] for call in list_calls.await_args_list]
    assert actual_offsets == expected_offsets

    expected_total = len(page_1) + len(page_2) + len(page_3)
    assert len(rules) == expected_total
    # Every rule is a ``[user_sub(member_id), role_sub(role_id)]`` pair.
    assert all(len(pair) == 2 for pair in rules)


@pytest.mark.asyncio
async def test_db_assign_role_to_group_exits_on_empty_first_page() -> None:
    """Empty group: zero rules, zero unnecessary follow-up calls."""
    service, list_calls, _ = _make_group_service(paginated_batches=[[]])

    session = _fake_session()
    _, rules = await service._db_assign_role_to_group(
        session,
        group_id=42,
        role_id=7,
        assigned_by=None,
    )

    assert rules == []
    assert list_calls.await_count == 1


@pytest.mark.asyncio
async def test_db_assign_role_to_group_exits_on_exact_page() -> None:
    """A group whose member count is exactly ``BATCH_SIZE`` should still
    trigger a follow-up call (returns empty, loop exits cleanly)."""
    page = [uuid.uuid4() for _ in range(RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE)]
    service, list_calls, _ = _make_group_service(paginated_batches=[page, []])

    session = _fake_session()
    _, rules = await service._db_assign_role_to_group(
        session,
        group_id=42,
        role_id=7,
        assigned_by=None,
    )

    assert len(rules) == RBAC_GROUP_ROLE_FANOUT_BATCH_SIZE
    assert list_calls.await_count == 2
