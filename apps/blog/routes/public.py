"""Public blog routes — read-only by default; engagement-mutate endpoints require auth.

Mounts under ``/public/workspaces/{workspace_slug}/blog/...`` so the
URL prefix can never collide with workspace slugs (``public`` is on the
:data:`apps.workspace.constants.WORKSPACE_RESERVED_SLUGS` list).
"""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.dependencies import get_current_user, get_current_user_optional
from apps.blog.constants import POST_LIKE_RATE_LIMIT
from apps.blog.containers import BlogContainer
from apps.blog.enums import PostStatus
from apps.blog.routes._engagement_rate_keys import auth_user_key
from apps.blog.schemas import (
    CategoryResponse,
    LikeState,
    ListCategoriesRequest,
    ListPostsRequest,
    ListTagsRequest,
    PostDetailResponse,
    PostResponse,
    TagResponse,
)
from apps.blog.services import CategoryService, PostLikeService, PostService, TagService
from apps.core.database.session import session_factory
from apps.core.rate_limit import limiter
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.user.models import User
from apps.workspace.dependencies import get_workspace_by_slug
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
    post_like_service: PostLikeService = Depends(Provide[BlogContainer.post_like_service]),
    current_user: User | None = Depends(get_current_user_optional),
) -> APIResponse[PostDetailResponse]:
    """Fetch a published post by slug. 404s for any non-published row.

    Read-through Redis cache (TTL 5 min, workspace-pattern invalidation on
    every post mutation). When the caller is authenticated, the response's
    ``liked_by_me`` field is populated via a single ``EXISTS`` probe
    against ``post_likes`` (FR-006). Anonymous callers receive
    ``liked_by_me = None``.
    """
    detail = await post_service.get_published_detail_by_slug(
        session,
        workspace_id=workspace.id,
        slug=post_slug,
    )
    if current_user is not None:
        detail.liked_by_me = await post_like_service.probe_liked_by_me(
            session,
            post_id=detail.id,
            user_id=current_user.id,
        )
    return APIResponse[PostDetailResponse].success(
        data=detail,
        message="Post retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# Engagement — likes (US1, FR-001..FR-009)
# ---------------------------------------------------------------------------


@blog_public_router.post(
    "/posts/{post_id}/like",
    response_model=APIResponse[LikeState],
    status_code=status.HTTP_200_OK,
)
@limiter.limit(POST_LIKE_RATE_LIMIT, key_func=auth_user_key)
@inject
async def like_post(
    request: Request,
    post_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace_by_slug),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_like_service: PostLikeService = Depends(Provide[BlogContainer.post_like_service]),
) -> APIResponse[LikeState]:
    """Idempotent like on a post. Authenticated users only (FR-001 / FR-007)."""
    state = await post_like_service.like(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        user_id=current_user.id,
    )
    return APIResponse[LikeState].success(
        data=state,
        message="Post liked.",
    )


@blog_public_router.delete(
    "/posts/{post_id}/like",
    response_model=APIResponse[LikeState],
    status_code=status.HTTP_200_OK,
)
@limiter.limit(POST_LIKE_RATE_LIMIT, key_func=auth_user_key)
@inject
async def unlike_post(
    request: Request,
    post_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace_by_slug),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_like_service: PostLikeService = Depends(Provide[BlogContainer.post_like_service]),
) -> APIResponse[LikeState]:
    """Idempotent unlike on a post. Authenticated users only (FR-003 / FR-007)."""
    state = await post_like_service.unlike(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        user_id=current_user.id,
    )
    return APIResponse[LikeState].success(
        data=state,
        message="Like removed.",
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
