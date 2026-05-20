"""Authenticated blog admin routes — workspace-scoped CRUD.

Phase C.2 split the original flat ``apps/blog/routes/admin.py`` (879
LOC, over the 800-LOC project cap) into three cohesive sub-modules:
taxonomy (categories + tags), posts (CRUD + versions + autosave +
publishing), and comments (self-edit/delete + moderation + reconcile).

The combined ``blog_admin_router`` symbol is preserved so
``apps/factory.py`` mounts it unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.blog.routes.admin._comments import router as _comments_router
from apps.blog.routes.admin._posts import router as _posts_router
from apps.blog.routes.admin._taxonomy import router as _taxonomy_router

blog_admin_router = APIRouter(prefix="/workspaces/{workspace_slug}/blog", tags=["blog"])
blog_admin_router.include_router(_taxonomy_router)
blog_admin_router.include_router(_posts_router)
blog_admin_router.include_router(_comments_router)

__all__ = ("blog_admin_router",)
