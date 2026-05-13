"""Integration test for find_by_name + soft-delete (F-PERF-3 / SC-006).

The pre-change ``PermissionRepository.find_by_name`` builds its SELECT
directly via ``session.execute(select(Permission).where(...))``, which
bypasses :meth:`BaseSQLAlchemyRepository._get_soft_delete_filter`. After
F-PERF-3 the body delegates to ``self.get_one(...)`` which applies the
``deleted_at IS NULL`` filter automatically — soft-deleted rows are
correctly excluded from name lookups.

The task originally targeted ``RoleRepository.find_by_name``; we test
``PermissionRepository.find_by_name`` instead because ``Role`` does not
inherit ``HasSoftDeletedMixin`` (only ``Permission`` does), so the
soft-delete behavior is observable only on the permission path. The
F-PERF-3 fix still applies to both repositories — see the implementation
task for the parallel rewrite of ``RoleRepository.find_by_name``.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac.repositories import PermissionRepository


def _short() -> str:
    return uuid.uuid4().hex[:8]


async def test_find_by_name_returns_active_permission(real_session: AsyncSession) -> None:
    """A non-soft-deleted permission resolves through find_by_name."""
    repo = PermissionRepository()
    suffix = _short()
    perm = await repo.add(
        real_session,
        {
            "name": f"perm_active_{suffix}",
            "display_name": "Active perm",
            "resource": f"res_{suffix}",
            "action": "read",
        },
        expunge=False,
    )
    await real_session.flush()

    found = await repo.find_by_name(real_session, name=perm.name)
    assert found is not None
    assert found.id == perm.id


async def test_find_by_name_excludes_soft_deleted_permission(real_session: AsyncSession) -> None:
    """After F-PERF-3, soft-deleted permissions must not be returned."""
    repo = PermissionRepository()
    suffix = _short()
    perm = await repo.add(
        real_session,
        {
            "name": f"perm_softdel_{suffix}",
            "display_name": "Soft-deleted perm",
            "resource": f"res_{suffix}",
            "action": "read",
        },
        expunge=False,
    )
    await real_session.flush()

    await repo.update(
        real_session,
        item_id=perm.id,
        data={"deleted_at": datetime.datetime.now(datetime.UTC)},
    )
    await real_session.flush()

    found = await repo.find_by_name(real_session, name=perm.name)
    assert found is None, (
        f"PermissionRepository.find_by_name returned soft-deleted permission "
        f"{found.id if found is not None else None}; expected None."
    )


async def test_find_by_name_returns_none_for_missing_permission(real_session: AsyncSession) -> None:
    repo = PermissionRepository()
    found = await repo.find_by_name(real_session, name=f"never_existed_{_short()}")
    assert found is None
