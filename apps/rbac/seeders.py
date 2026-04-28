"""Bootstrap permissions + Casbin policies from the resource registry.

The :func:`apps.rbac.registry.rbac_resource` decorator declares every
``(resource, action)`` pair an ORM model accepts. :func:`sync_registered_resources`
turns those declarations into:

* a ``Permission`` row per pair (idempotent, ``INSERT ... ON CONFLICT DO NOTHING``),
* a ``RolePermission`` link from a configurable system-admin role to each
  permission (also idempotent),
* a matching ``p, role:<id>, <resource>, <action>`` policy in the Casbin
  ``casbin_rule`` table.

Called from :func:`apps.factory.lifespan` when
``app_settings.rbac.auto_seed_resources_from_registry`` is true. Idempotent
across worker restarts and across multiple workers booting concurrently —
the unique constraints on ``roles.name`` and ``permissions.name`` plus
``ON CONFLICT DO NOTHING`` make duplicate seed attempts safe.
"""

from __future__ import annotations

from dataclasses import dataclass

import casbin
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.rbac.models import Permission, Role, RolePermission
from apps.rbac.registry import get_registered_resources
from apps.rbac.services._helpers import role_sub


@dataclass(frozen=True, slots=True)
class SeedReport:
    """Summary of what the seeder created on this invocation."""

    role_created: bool
    permissions_created: int
    role_permissions_created: int
    casbin_policies_added: int


async def sync_registered_resources(
    session: AsyncSession,
    enforcer: casbin.AsyncEnforcer,
    *,
    admin_role_name: str,
) -> SeedReport:
    """Idempotently seed the registry's ``(resource, action)`` pairs."""
    registry = get_registered_resources()
    if not registry:
        logger.info("rbac.seeders - sync_registered_resources - registry empty, nothing to seed")
        return SeedReport(
            role_created=False,
            permissions_created=0,
            role_permissions_created=0,
            casbin_policies_added=0,
        )

    admin_role, role_created = await _ensure_admin_role(session, name=admin_role_name)

    permissions_created = 0
    role_permissions_created = 0
    casbin_policies_added = 0
    admin_subject = role_sub(admin_role.id)

    for resource in registry.values():
        for action in resource.actions:
            permission, created_perm = await _ensure_permission(
                session,
                resource_name=resource.name,
                action_value=action.value,
            )
            permissions_created += int(created_perm)

            created_link = await _ensure_role_permission(
                session,
                role_id=admin_role.id,
                permission_id=permission.id,
            )
            role_permissions_created += int(created_link)

            policy_added = await enforcer.add_policy(admin_subject, resource.name, action.value)
            casbin_policies_added += int(bool(policy_added))

    await session.flush()
    report = SeedReport(
        role_created=role_created,
        permissions_created=permissions_created,
        role_permissions_created=role_permissions_created,
        casbin_policies_added=casbin_policies_added,
    )
    logger.info("rbac.seeders - sync_registered_resources - {report}", report=report)
    return report


async def _ensure_admin_role(session: AsyncSession, *, name: str) -> tuple[Role, bool]:
    """Return (role, created) — fetches existing or inserts a new admin role."""
    existing = await session.execute(select(Role).where(Role.name == name))
    found = existing.scalar_one_or_none()
    if found is not None:
        return found, False

    role = Role(name=name, display_name=name.replace("_", " ").title(), description="Auto-seeded by registry sync.")
    session.add(role)
    await session.flush()
    return role, True


async def _ensure_permission(
    session: AsyncSession,
    *,
    resource_name: str,
    action_value: str,
) -> tuple[Permission, bool]:
    """Idempotently insert a Permission for ``(resource, action)``.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` on the unique ``permissions.name``
    constraint so concurrent workers cannot raise duplicates.
    """
    perm_name = f"{resource_name}:{action_value}"
    stmt = (
        pg_insert(Permission)
        .values(
            name=perm_name,
            display_name=perm_name,
            resource=resource_name,
            action=action_value,
            is_system=True,
        )
        .on_conflict_do_nothing(index_elements=["name"])
    )
    result = await session.execute(stmt)
    created = (result.rowcount or 0) > 0

    found = await session.execute(select(Permission).where(Permission.name == perm_name))
    return found.scalar_one(), created


async def _ensure_role_permission(
    session: AsyncSession,
    *,
    role_id: int,
    permission_id: int,
) -> bool:
    """Idempotently link admin role → permission. Returns True when a row was inserted."""
    existing = await session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False

    session.add(RolePermission(role_id=role_id, permission_id=permission_id))
    await session.flush()
    return True
