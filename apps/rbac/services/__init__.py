"""RBAC + ABAC services.

Two top-level public services:

* :class:`RBACService` — **write-side facade**. Delegates to the three
  focused sub-services so routes and tests that expect a single
  ``RBACService`` keep working.
* :class:`AccessService` — **read-side**. Used by the route decorators.

The facade composes:

* :class:`RolePermissionService` — roles, permissions, role↔permission
  links, direct user↔role assignment.
* :class:`GroupService` — group creation, user↔group membership,
  group↔role links (with fan-out to members).
* :class:`ObjectPermissionService` — per-object ABAC grants / revokes.

Casbin mapping (no domains):

* ``p, role:<role_id>, <resource>, <action>`` — a role grants an action.
* ``g, user:<user_id>, role:<role_id>`` — a user *is* a role (direct
  assignment).
* ``g, user:<user_id>, role:<role_id>`` — also written for every role the
  user inherits via group membership, so a single ``enforce`` call
  resolves the full graph.

Transaction boundary note (commit-then-policy-sync)
---------------------------------------------------

Casbin's :class:`casbin_async_sqlalchemy_adapter.Adapter` opens its **own**
``AsyncSession`` against the configured database URL. Every
``add_policy`` / ``add_grouping_policy`` / ``remove_policy`` call commits
on that adapter session independently of the FastAPI request session, so
co-locating the call inside ``@transactional`` does **not** make the two
writes atomic — it only happens to look that way under happy-path tests.

This module therefore uses *commit-then-policy-sync*:

1. The relational write (e.g. ``RolePermission`` insert, ``UserGroup``
   insert) commits in a small ``@transactional`` block.
2. After commit, the Casbin policy/grouping write runs *outside* any
   transaction.
3. If the Casbin write fails, the relational row is compensated (best-
   effort delete in a fresh transaction) and the public method raises
   :class:`apps.rbac.exceptions.RBACPolicySyncError` so the caller
   does **not** assume the policy is in effect.

This is not a true outbox: a process crash between step 1 and step 2
leaves the relational store ahead of Casbin (under-grant). Compensation
itself can also fail, leaving drift in the same direction. Both
conditions are logged at ``error`` level with a ``DRIFT:`` prefix so
they can be alerted on. A full transactional outbox + watcher remains
the recommended next step before bulk-grant volume grows; until then,
this layout closes the silent-privilege-escalation hole identified by
the 2026-05-08 audit (C1).
"""

from __future__ import annotations

from apps.rbac.services._access import AccessService
from apps.rbac.services._facade import RBACService
from apps.rbac.services._group import GroupService
from apps.rbac.services._object_permission import ObjectPermissionService
from apps.rbac.services._permission import PermissionService
from apps.rbac.services._role import RoleService

__all__ = [
    "AccessService",
    "GroupService",
    "ObjectPermissionService",
    "PermissionService",
    "RBACService",
    "RoleService",
]
