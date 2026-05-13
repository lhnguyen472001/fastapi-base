"""Real-DB integration tests for RBAC compensation observability (F-SCALE-2).

Asserts that every ``_compensate_*`` path in ``apps/rbac/services/`` routes
through ``apps.rbac._metrics.record_compensation_drift(...)`` with the
correct ``kind``, ``outcome``, ``target_id``, ``mutation``, and ``cause``
arguments — and that the happy path emits nothing.

The helper's internals (counter increment + structured log) are pinned in
``tests/unit/test_rbac_drift_metrics_unit.py``; this test verifies the
call sites are wired.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio

from apps.rbac.enforcer import enforcer_factory
from apps.rbac.exceptions import RBACPolicySyncError
from apps.rbac.repositories import (
    GroupRepository,
    GroupRoleRepository,
    ObjectPermissionRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserGroupRepository,
    UserRoleRepository,
)
from apps.rbac.services import (
    GroupService,
    ObjectPermissionService,
    PermissionService,
    RBACService,
    RoleService,
)
from apps.settings import app_settings
from apps.user.repositories import UserRepository


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _user_payload(suffix: str) -> dict:
    return {
        "email": f"drift_{suffix}@example.com",
        "username": f"drift_{suffix}",
        "hashed_password": "x" * 60,
        "is_active": True,
    }


@pytest_asyncio.fixture
async def enforcer():
    url = app_settings.db.database_uri.render_as_string(hide_password=False)
    return await enforcer_factory(url)


@pytest_asyncio.fixture
async def rbac_service(enforcer) -> RBACService:
    role_repo = RoleRepository()
    permission_repo = PermissionRepository()
    group_repo = GroupRepository()
    role_permission_repo = RolePermissionRepository()
    user_role_repo = UserRoleRepository()
    user_group_repo = UserGroupRepository()
    group_role_repo = GroupRoleRepository()
    object_permission_repo = ObjectPermissionRepository()

    role_service = RoleService(
        repository=role_repo,
        user_role_repository=user_role_repo,
        enforcer=enforcer,
    )
    permission_service = PermissionService(
        repository=permission_repo,
        role_repository=role_repo,
        role_permission_repository=role_permission_repo,
        enforcer=enforcer,
    )
    group_service = GroupService(
        repository=group_repo,
        role_repository=role_repo,
        user_group_repository=user_group_repo,
        group_role_repository=group_role_repo,
        enforcer=enforcer,
    )
    object_permission_service = ObjectPermissionService(
        repository=object_permission_repo,
        enforcer=enforcer,
    )
    return RBACService(
        role_service=role_service,
        permission_service=permission_service,
        group_service=group_service,
        object_permission_service=object_permission_service,
    )


@pytest_asyncio.fixture
async def seeded_user(real_session):
    repo = UserRepository()
    user = await repo.add(real_session, _user_payload(_short()), expunge=False)
    await real_session.flush()
    return user


# ---------------------------------------------------------------------------
# F-SCALE-2: every compensation path emits a drift record.
# ---------------------------------------------------------------------------


async def test_happy_path_does_not_emit_drift(real_session, rbac_service) -> None:
    """Successful grant must NOT call record_compensation_drift."""
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"happy_role_{s}", display_name="Happy")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"happy_perm_{s}",
        display_name="Happy",
        resource=f"happy_{s}",
        action="read",
    )

    with patch("apps.rbac._metrics.record_compensation_drift") as spy:
        await rbac_service.grant_permission_to_role(
            real_session,
            role_id=role.id,
            permission_id=perm.id,
        )

    assert spy.call_count == 0


async def test_role_permission_drift_emits_compensated_outcome(real_session, rbac_service, enforcer) -> None:
    """When Casbin sync fails but compensation succeeds, outcome='compensated'."""
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"drift_role_{s}", display_name="Drift")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"drift_perm_{s}",
        display_name="Drift",
        resource=f"drift_{s}",
        action="read",
    )

    original_add_policy = enforcer.add_policy

    async def boom(*_args, **_kwargs) -> bool:
        msg = "simulated casbin outage"
        raise RuntimeError(msg)

    enforcer.add_policy = boom
    try:
        with patch("apps.rbac._metrics.record_compensation_drift") as spy, pytest.raises(RBACPolicySyncError):
            await rbac_service.grant_permission_to_role(
                real_session,
                role_id=role.id,
                permission_id=perm.id,
            )
    finally:
        enforcer.add_policy = original_add_policy

    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs["kind"] == "role_permission"
    assert kwargs["outcome"] == "compensated"
    assert kwargs["mutation"] == "grant_permission_to_role"
    assert kwargs["target_id"] is not None
    assert isinstance(kwargs["cause"], RuntimeError)


async def test_object_permission_drift_emits_compensated_outcome(
    real_session,
    rbac_service,
    enforcer,
    seeded_user,
) -> None:
    """object-permission grant failure emits kind='object_permission'."""
    s = _short()
    obj_id = str(uuid.uuid4())

    original_add_policy = enforcer.add_policy

    async def boom(*_args, **_kwargs) -> bool:
        msg = "simulated casbin outage"
        raise RuntimeError(msg)

    enforcer.add_policy = boom
    try:
        with patch("apps.rbac._metrics.record_compensation_drift") as spy, pytest.raises(RBACPolicySyncError):
            await rbac_service.grant_object_permission(
                real_session,
                user_id=seeded_user.id,
                resource=f"obj_drift_{s}",
                object_id=obj_id,
                action="edit",
            )
    finally:
        enforcer.add_policy = original_add_policy

    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs["kind"] == "object_permission"
    assert kwargs["outcome"] == "compensated"
    assert kwargs["mutation"] == "grant_object_permission"
    assert isinstance(kwargs["cause"], RuntimeError)


async def test_user_group_drift_emits_when_grouping_policy_fails(
    real_session,
    rbac_service,
    enforcer,
    seeded_user,
) -> None:
    """User-group membership compensation emits kind='user_group'."""
    s = _short()
    group = await rbac_service.create_group(
        real_session,
        name=f"drift_group_{s}",
        display_name=f"Drift Group {s}",
    )
    # Need at least one group_role link so add_user_to_group generates rules
    # to push into Casbin (otherwise the sync path is a no-op and never fails).
    role = await rbac_service.create_role(real_session, name=f"drift_grp_role_{s}", display_name="Grp")
    await rbac_service.assign_role_to_group(real_session, group_id=group.id, role_id=role.id)

    original_add_grouping = enforcer.add_grouping_policies

    async def boom(*_args, **_kwargs) -> bool:
        msg = "simulated casbin outage"
        raise RuntimeError(msg)

    enforcer.add_grouping_policies = boom
    try:
        with patch("apps.rbac._metrics.record_compensation_drift") as spy, pytest.raises(RBACPolicySyncError):
            await rbac_service.add_user_to_group(
                real_session,
                user_id=seeded_user.id,
                group_id=group.id,
            )
    finally:
        enforcer.add_grouping_policies = original_add_grouping

    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs["kind"] == "user_group"
    assert kwargs["outcome"] == "compensated"
    assert kwargs["mutation"] == "add_user_to_group"
    assert isinstance(kwargs["cause"], RuntimeError)
