"""Real-DB integration tests for UserService against migrated tables.

Targets the public service contract:
    - create / get_by_id / list_users / update / soft_delete
    - get_by_email_or_username
Plus business rules: password hashing, conflict detection, NotFound on missing.
"""

from __future__ import annotations

import uuid

import pytest

from apps.core.security import verify_password
from apps.user.exceptions import UserAlreadyExistsError, UserNotFoundError
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest, ListUsersRequest, UpdateUserRequest
from apps.user.services import UserService


@pytest.fixture
def user_service() -> UserService:
    return UserService(repository=UserRepository())


def _create_request(suffix: str, *, password: str = "Sup3rSecret!") -> CreateUserRequest:
    return CreateUserRequest(
        email=f"svc_{suffix}@example.com",
        username=f"svc_{suffix}",
        password=password,
    )


# ------------------------------- create -------------------------------------


async def test_create_persists_user_with_hashed_password(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    plain = "Sup3rSecret!"
    request = _create_request(suffix, password=plain)

    user = await user_service.create(real_session, data=request)
    await real_session.flush()

    assert user.id is not None
    assert user.email == request.email
    assert user.username == request.username
    # New users start inactive — they must verify email via OTP first.
    assert user.is_active is False
    assert user.hashed_password != plain
    assert verify_password(plain, user.hashed_password) is True


async def test_create_rejects_duplicate_email(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    duplicate = CreateUserRequest(
        email=f"svc_{suffix}@example.com",
        username=f"svc_{suffix}_other",
        password="AnotherPass1!",
    )
    with pytest.raises(UserAlreadyExistsError):
        await user_service.create(real_session, data=duplicate)


async def test_create_rejects_duplicate_username(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    duplicate = CreateUserRequest(
        email=f"other_{suffix}@example.com",
        username=f"svc_{suffix}",
        password="AnotherPass1!",
    )
    with pytest.raises(UserAlreadyExistsError):
        await user_service.create(real_session, data=duplicate)


# ------------------------------- get_by_id ----------------------------------


async def test_get_by_id_returns_user(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    fetched = await user_service.get_by_id(real_session, user_id=created.id)
    assert fetched.id == created.id
    assert fetched.username == created.username


async def test_get_by_id_raises_when_missing(real_session, user_service) -> None:
    with pytest.raises(UserNotFoundError):
        await user_service.get_by_id(real_session, user_id=uuid.uuid4())


async def test_get_by_id_raises_for_soft_deleted(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    await user_service.soft_delete(real_session, user_id=created.id)

    with pytest.raises(UserNotFoundError):
        await user_service.get_by_id(real_session, user_id=created.id)


# ------------------------------- list_users ---------------------------------


async def test_list_users_paginates_and_counts(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    for i in range(5):
        await user_service.create(real_session, data=_create_request(f"{suffix}_{i}"))
    await real_session.flush()

    items, total = await user_service.list_users(real_session, params=ListUsersRequest(limit=3, offset=0))

    assert total >= 5
    assert len(items) == 3


async def test_list_users_filters_by_is_active(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    active = await user_service.create(real_session, data=_create_request(f"{suffix}_a"))
    inactive = await user_service.create(real_session, data=_create_request(f"{suffix}_b"))
    # New users default to inactive — flip the first one to active for this test.
    active.is_active = True
    await real_session.flush()

    items, _ = await user_service.list_users(real_session, params=ListUsersRequest(limit=100, offset=0, is_active=True))
    ids = {u.id for u in items}
    assert active.id in ids
    assert inactive.id not in ids


# --------------------------------- update -----------------------------------


async def test_update_changes_field_and_persists(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    updated = await user_service.update(
        real_session,
        user_id=created.id,
        data=UpdateUserRequest(is_active=False),
    )
    await real_session.flush()

    assert updated.is_active is False

    refetched = await user_service.get_by_id(real_session, user_id=created.id)
    assert refetched.is_active is False


async def test_update_rehashes_password(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    old_plain = "OldPassword1!"
    new_plain = "NewPassword2@"
    created = await user_service.create(real_session, data=_create_request(suffix, password=old_plain))
    await real_session.flush()

    updated = await user_service.update(
        real_session,
        user_id=created.id,
        data=UpdateUserRequest(password=new_plain),
    )
    await real_session.flush()

    assert verify_password(new_plain, updated.hashed_password) is True
    assert verify_password(old_plain, updated.hashed_password) is False


async def test_update_rejects_email_conflict_with_other_user(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    user_a = await user_service.create(real_session, data=_create_request(f"{suffix}_a"))
    user_b = await user_service.create(real_session, data=_create_request(f"{suffix}_b"))
    await real_session.flush()

    with pytest.raises(UserAlreadyExistsError):
        await user_service.update(
            real_session,
            user_id=user_b.id,
            data=UpdateUserRequest(email=user_a.email),
        )


async def test_update_allows_no_op_with_same_email(real_session, user_service) -> None:
    """Updating a user's email to its current value must NOT trigger a conflict."""
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    updated = await user_service.update(
        real_session,
        user_id=created.id,
        data=UpdateUserRequest(email=created.email),
    )
    assert updated.email == created.email


async def test_update_raises_when_user_missing(real_session, user_service) -> None:
    with pytest.raises(UserNotFoundError):
        await user_service.update(
            real_session,
            user_id=uuid.uuid4(),
            data=UpdateUserRequest(is_active=False),
        )


# ------------------------------- soft_delete --------------------------------


async def test_soft_delete_sets_deleted_at(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    deleted = await user_service.soft_delete(real_session, user_id=created.id)
    await real_session.flush()

    assert deleted.deleted_at is not None

    raw = await user_service.repository.find_by_id(real_session, user_id=created.id, include_deleted=True)
    assert raw is not None
    assert raw.deleted_at is not None


async def test_soft_delete_idempotent_raises_on_second_call(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    await user_service.soft_delete(real_session, user_id=created.id)
    await real_session.flush()

    with pytest.raises(UserNotFoundError):
        await user_service.soft_delete(real_session, user_id=created.id)


async def test_soft_delete_raises_when_missing(real_session, user_service) -> None:
    with pytest.raises(UserNotFoundError):
        await user_service.soft_delete(real_session, user_id=uuid.uuid4())


# -------------------------- get_by_email_or_username ------------------------


async def test_get_by_email_or_username_returns_user(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    by_email = await user_service.get_by_email_or_username(real_session, email=created.email)
    by_username = await user_service.get_by_email_or_username(real_session, username=created.username)

    assert by_email is not None and by_email.id == created.id
    assert by_username is not None and by_username.id == created.id


async def test_get_by_email_or_username_excludes_soft_deleted(real_session, user_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    created = await user_service.create(real_session, data=_create_request(suffix))
    await real_session.flush()

    await user_service.soft_delete(real_session, user_id=created.id)
    await real_session.flush()

    found = await user_service.get_by_email_or_username(real_session, email=created.email)
    assert found is None
