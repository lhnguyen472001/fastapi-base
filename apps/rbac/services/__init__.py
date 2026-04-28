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

Transaction boundary note
-------------------------

Every mutating method calls ``self.enforcer.add_policy`` /
``add_grouping_policy`` / ``remove_policy`` **inside** its
``@transactional`` block. The Casbin SQLAlchemy adapter persists each
rule itself, so we do not call ``enforcer.save_policy()`` (that would
rewrite the entire ``casbin_rule`` table on every grant). Keeping the
single-rule writes inside the transaction means the relational rows and
the ``casbin_rule`` table commit as one atomic unit — if Casbin writes
fail, the whole assignment rolls back and the two stores cannot drift.

The tradeoff is lock contention: the Casbin adapter writes hold a row-
lock on ``casbin_rule`` for the duration of the DB transaction. Under
bulk grants (e.g. :meth:`GroupService.add_user_to_group` or
:meth:`GroupService.assign_role_to_group` with many inherited roles)
this can serialize concurrent writers.

When we outgrow single-writer throughput, move the enforcer sync **after**
commit and add a compensating retry queue (e.g. Redis or an outbox table)
so failed syncs can be replayed without leaving the relational store ahead
of Casbin. Do NOT bypass the transaction without such a compensation
mechanism — stale authz is a security footgun.
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
