"""Blog module — workspace-scoped Tiptap-backed posts, categories, tags.

Every row in this module FKs to :class:`apps.workspace.models.Workspace`
via ``workspace_id`` and is gated by
:func:`apps.workspace.dependencies.require_workspace_role` at the route
boundary. Heavy Tiptap content lives in
:class:`apps.blog.models.PostContent` (1:1 with :class:`Post`) so list
queries don't eagerly hydrate megabytes of JSONB.
"""
