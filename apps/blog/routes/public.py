"""Public blog routes — read-only, no auth required.

Mounts under ``/public/workspaces/{workspace_slug}/blog/...`` so the
URL prefix can never collide with workspace slugs (``public`` is on the
:data:`apps.workspace.constants.WORKSPACE_RESERVED_SLUGS` list).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from apps.blog.containers import BlogContainer
from apps.blog.enums import PostStatus
from apps.blog.routes.admin import _build_post_detail
from apps.blog.schemas import (
    CategoryResponse,
    ListCategoriesRequest,
    ListPostsRequest,
    ListTagsRequest,
    PostDetailResponse,
    PostResponse,
    TagResponse,
)
from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.workspace.dependencies import get_workspace_by_slug

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.blog.services import CategoryService, PostService, TagService
    from apps.workspace.models import Workspace

blog_public_router = APIRouter(prefix="/public/workspaces/{workspace_slug}/blog", tags=["blog-public"])


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


@blog_public_router.get(
    "/posts",
    response_model=APIResponse[PaginatedResponse[PostResponse]],
)
@inject
async def list_published_posts(
    params: ListPostsRequest = Depends(),
    workspace: Workspace = Depends(get_workspace_by_slug),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PaginatedResponse[PostResponse]]:
    """List published posts for a workspace. Status param is ignored."""
    # Force-pin status to PUBLISHED — public reads never expose drafts/archived.
    public_params = params.model_copy(update={"status": PostStatus.PUBLISHED})
    items, total = await post_service.list_posts(session, workspace_id=workspace.id, params=public_params)
    return APIResponse[PaginatedResponse[PostResponse]].success(
        data=PaginatedResponse[PostResponse](
            items=[PostResponse.model_validate(p) for p in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Published posts retrieved successfully.",
    )


@blog_public_router.get(
    "/posts/{post_slug}",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def get_published_post_by_slug(
    post_slug: str,
    workspace: Workspace = Depends(get_workspace_by_slug),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Fetch a published post by slug. 404s for any non-published row."""
    post = await post_service.get_published_by_slug(session, workspace_id=workspace.id, slug=post_slug)
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@blog_public_router.get(
    "/categories",
    response_model=APIResponse[PaginatedResponse[CategoryResponse]],
)
@inject
async def list_categories_public(
    params: ListCategoriesRequest = Depends(),
    workspace: Workspace = Depends(get_workspace_by_slug),
    session: AsyncSession = Depends(session_factory),
    category_service: CategoryService = Depends(Provide[BlogContainer.category_service]),
) -> APIResponse[PaginatedResponse[CategoryResponse]]:
    """List active categories for a workspace."""
    public_params = params.model_copy(update={"is_active": True})
    items, total = await category_service.list_categories(
        session,
        workspace_id=workspace.id,
        params=public_params,
    )
    return APIResponse[PaginatedResponse[CategoryResponse]].success(
        data=PaginatedResponse[CategoryResponse](
            items=[CategoryResponse.model_validate(c) for c in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Categories retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@blog_public_router.get(
    "/tags",
    response_model=APIResponse[PaginatedResponse[TagResponse]],
)
@inject
async def list_tags_public(
    params: ListTagsRequest = Depends(),
    workspace: Workspace = Depends(get_workspace_by_slug),
    session: AsyncSession = Depends(session_factory),
    tag_service: TagService = Depends(Provide[BlogContainer.tag_service]),
) -> APIResponse[PaginatedResponse[TagResponse]]:
    """List tags for a workspace."""
    items, total = await tag_service.list_tags(session, workspace_id=workspace.id, params=params)
    return APIResponse[PaginatedResponse[TagResponse]].success(
        data=PaginatedResponse[TagResponse](
            items=[TagResponse.model_validate(t) for t in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Tags retrieved successfully.",
    )
