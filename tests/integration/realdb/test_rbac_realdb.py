"""Real-DB integration tests for RBAC + ABAC."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from apps.rbac.decorators import require_access, require_ownership
from apps.rbac.enforcer import create_enforcer
from apps.rbac.exceptions import AccessDeniedError
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
    AccessService,
    GroupService,
    ObjectPermissionService,
    PermissionService,
    RBACService,
    RoleService,
)
from apps.settings import app_settings
from apps.user.repositories import UserRepository


def _user_payload(suffix: str) -> dict:
    return {
        "email": f"rbac_{suffix}@example.com",
        "username": f"rbac_{suffix}",
        "hashed_password": "x" * 60,
        "is_active": True,
    }


def _short() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def enforcer():
    url = app_settings.db.database_uri.render_as_string(hide_password=False)
    return await create_enforcer(url)


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
async def access_service(enforcer) -> AccessService:
    return AccessService(enforcer=enforcer)


@pytest_asyncio.fixture
async def seeded_user(real_session):
    repo = UserRepository()
    user = await repo.add(real_session, _user_payload(_short()), expunge=False)
    await real_session.flush()
    return user


# ----- service-level --------------------------------------------------------


async def test_create_role_persists(real_session, rbac_service) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"editor_{s}", display_name=f"Editor {s}")
    assert role.id is not None
    assert role.name == f"editor_{s}"
    assert role.is_active is True


async def test_create_permission_persists(real_session, rbac_service) -> None:
    s = _short()
    perm = await rbac_service.create_permission(
        real_session,
        name=f"posts_edit_{s}",
        display_name="Edit posts",
        resource=f"posts_{s}",
        action="edit",
    )
    assert perm.id is not None
    assert perm.resource == f"posts_{s}"


async def test_grant_permission_writes_casbin_policy(real_session, rbac_service, enforcer) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"r_{s}", display_name=f"R {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"p_{s}",
        display_name=f"P {s}",
        resource=f"res_{s}",
        action="read",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)

    policies = enforcer.get_policy()
    assert any(p == [f"role:{role.id}", f"res_{s}", "read"] for p in policies)


async def test_assign_role_to_user_grants_access(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"viewer_{s}", display_name=f"Viewer {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"doc_read_{s}",
        display_name="Read",
        resource=f"doc_{s}",
        action="read",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)
    await rbac_service.assign_role_to_user(real_session, user_id=seeded_user.id, role_id=role.id)

    allowed = await access_service.check(user_id=seeded_user.id, resource=f"doc_{s}", action="read")
    assert allowed is True


async def test_check_denies_when_no_role(access_service) -> None:
    allowed = await access_service.check(user_id=uuid.uuid4(), resource=f"missing_{_short()}", action="read")
    assert allowed is False


async def test_group_role_propagates_to_members(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"team_role_{s}", display_name=f"TeamRole {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"art_write_{s}",
        display_name="Write",
        resource=f"article_{s}",
        action="write",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)
    group = await rbac_service.create_group(real_session, name=f"team_{s}", display_name=f"Team {s}")
    await rbac_service.add_user_to_group(real_session, user_id=seeded_user.id, group_id=group.id)
    await rbac_service.assign_role_to_group(real_session, group_id=group.id, role_id=role.id)

    allowed = await access_service.check(user_id=seeded_user.id, resource=f"article_{s}", action="write")
    assert allowed is True


# ----- ABAC -----------------------------------------------------------------


async def test_check_object_allows_owner(access_service) -> None:
    user_id = uuid.uuid4()
    obj = type("Obj", (), {"owner_id": user_id})()
    assert await access_service.check_object(user_id=user_id, obj=obj, action="edit") is True


async def test_check_object_denies_non_owner_without_role(access_service) -> None:
    obj = type("Obj", (), {"owner_id": uuid.uuid4()})()
    assert await access_service.check_object(user_id=uuid.uuid4(), obj=obj, action="edit", resource="post") is False


async def test_check_object_falls_back_to_rbac(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"mod_{s}", display_name=f"Mod {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"p_post_edit_{s}",
        display_name="Edit",
        resource=f"post_{s}",
        action="edit",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)
    await rbac_service.assign_role_to_user(real_session, user_id=seeded_user.id, role_id=role.id)

    obj = type("Post", (), {"owner_id": uuid.uuid4()})()  # NOT seeded user
    assert (
        await access_service.check_object(user_id=seeded_user.id, obj=obj, action="edit", resource=f"post_{s}") is True
    )


# ----- decorators -----------------------------------------------------------


async def test_require_access_allows(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"r_{s}", display_name=f"R {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"res_write_{s}",
        display_name="Write",
        resource=f"res_{s}",
        action="write",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)
    await rbac_service.assign_role_to_user(real_session, user_id=seeded_user.id, role_id=role.id)

    @require_access(f"res_{s}", "write")
    async def handler(*, current_user, access_service):
        return "ok"

    assert await handler(current_user=seeded_user, access_service=access_service) == "ok"


async def test_require_access_denies(access_service, seeded_user) -> None:
    @require_access("nonexistent_resource", "write")
    async def handler(*, current_user, access_service):
        return "ok"

    with pytest.raises(AccessDeniedError):
        await handler(current_user=seeded_user, access_service=access_service)


async def test_require_ownership_allows_owner(real_session, access_service, seeded_user) -> None:
    target = type("Doc", (), {"owner_id": seeded_user.id, "id": uuid.uuid4()})()

    async def loader(_session, _id):
        return target

    @require_ownership("doc", "edit", loader=loader, id_param="doc_id")
    async def handler(*, current_user, access_service, session, doc_id, **kwargs):
        return kwargs["_loaded_doc_id"]

    result = await handler(
        current_user=seeded_user,
        access_service=access_service,
        session=real_session,
        doc_id=target.id,
    )
    assert result is target


async def test_require_ownership_denies_non_owner(real_session, access_service, seeded_user) -> None:
    target = type("Doc", (), {"owner_id": uuid.uuid4(), "id": uuid.uuid4()})()

    async def loader(_session, _id):
        return target

    @require_ownership("doc", "edit", loader=loader, id_param="doc_id")
    async def handler(*, current_user, access_service, session, doc_id, **kwargs):
        return "ok"

    with pytest.raises(AccessDeniedError):
        await handler(
            current_user=seeded_user,
            access_service=access_service,
            session=real_session,
            doc_id=target.id,
        )


async def test_require_ownership_falls_back_to_rbac(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    role = await rbac_service.create_role(real_session, name=f"r_{s}", display_name=f"R {s}")
    perm = await rbac_service.create_permission(
        real_session,
        name=f"doc_edit_{s}",
        display_name="Edit",
        resource=f"doc_{s}",
        action="edit",
    )
    await rbac_service.grant_permission_to_role(real_session, role_id=role.id, permission_id=perm.id)
    await rbac_service.assign_role_to_user(real_session, user_id=seeded_user.id, role_id=role.id)

    target = type("Doc", (), {"owner_id": uuid.uuid4(), "id": uuid.uuid4()})()

    async def loader(_session, _id):
        return target

    @require_ownership(f"doc_{s}", "edit", loader=loader, id_param="doc_id")
    async def handler(*, current_user, access_service, session, doc_id, **kwargs):
        return "ok"

    assert (
        await handler(
            current_user=seeded_user,
            access_service=access_service,
            session=real_session,
            doc_id=target.id,
        )
        == "ok"
    )


# ----- per-object grants (instance-level ABAC) ------------------------------


async def test_grant_object_permission_writes_casbin_policy(real_session, rbac_service, enforcer, seeded_user) -> None:
    s = _short()
    obj_id = str(uuid.uuid4())
    await rbac_service.grant_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"post_{s}",
        object_id=obj_id,
        action="edit",
    )
    policies = enforcer.get_policy()
    assert any(p == [f"user:{seeded_user.id}", f"post_{s}:{obj_id}", "edit"] for p in policies)


async def test_check_object_allows_via_instance_grant_non_owner(
    real_session, rbac_service, access_service, seeded_user
) -> None:
    s = _short()
    obj_id = uuid.uuid4()
    await rbac_service.grant_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"post_{s}",
        object_id=str(obj_id),
        action="edit",
    )
    # NOT the owner
    obj = type("Post", (), {"owner_id": uuid.uuid4(), "id": obj_id})()
    assert (
        await access_service.check_object(
            user_id=seeded_user.id,
            obj=obj,
            action="edit",
            resource=f"post_{s}",
        )
        is True
    )


async def test_check_object_instance_grant_does_not_leak_to_other_objects(
    real_session, rbac_service, access_service, seeded_user
) -> None:
    s = _short()
    granted = uuid.uuid4()
    other = uuid.uuid4()
    await rbac_service.grant_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"post_{s}",
        object_id=str(granted),
        action="edit",
    )
    obj = type("Post", (), {"owner_id": uuid.uuid4(), "id": other})()
    assert (
        await access_service.check_object(
            user_id=seeded_user.id,
            obj=obj,
            action="edit",
            resource=f"post_{s}",
        )
        is False
    )


async def test_revoke_object_permission_removes_access(real_session, rbac_service, access_service, seeded_user) -> None:
    s = _short()
    obj_id = uuid.uuid4()
    await rbac_service.grant_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"post_{s}",
        object_id=str(obj_id),
        action="edit",
    )
    revoked = await rbac_service.revoke_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"post_{s}",
        object_id=str(obj_id),
        action="edit",
    )
    assert revoked is True

    obj = type("Post", (), {"owner_id": uuid.uuid4(), "id": obj_id})()
    assert (
        await access_service.check_object(
            user_id=seeded_user.id,
            obj=obj,
            action="edit",
            resource=f"post_{s}",
        )
        is False
    )


async def test_require_ownership_allows_via_instance_grant(
    real_session, rbac_service, access_service, seeded_user
) -> None:
    s = _short()
    obj_id = uuid.uuid4()
    await rbac_service.grant_object_permission(
        real_session,
        user_id=seeded_user.id,
        resource=f"doc_{s}",
        object_id=str(obj_id),
        action="edit",
    )
    target = type("Doc", (), {"owner_id": uuid.uuid4(), "id": obj_id})()

    async def loader(_session, _id):
        return target

    @require_ownership(f"doc_{s}", "edit", loader=loader, id_param="doc_id")
    async def handler(*, current_user, access_service, session, doc_id, **kwargs):
        return "ok"

    result = await handler(
        current_user=seeded_user,
        access_service=access_service,
        session=real_session,
        doc_id=obj_id,
    )
    assert result == "ok"
