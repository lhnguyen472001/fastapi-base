"""Workspace module — multi-tenant primitive.

A :class:`Workspace` is the unit of tenancy: every blog row, comment,
category, tag, and media asset is scoped to exactly one workspace via
``workspace_id``. Users join workspaces through :class:`WorkspaceMember`
with a per-workspace :class:`WorkspaceRole` (``owner`` / ``editor`` /
``viewer`` / ``commenter``).

Workspace roles are intentionally separate from the global Casbin RBAC:
they are dynamic, per-user-per-workspace data, whereas Casbin policies
gate coarse-grained system actions (e.g. super-admin operations).
"""
