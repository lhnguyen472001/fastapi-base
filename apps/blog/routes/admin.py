"""Authenticated blog admin routes — workspace-scoped CRUD.

All routes mount under ``/workspaces/{workspace_slug}/blog/...`` and are
gated by :func:`apps.workspace.dependencies.require_workspace_role`. The
role-permission matrix (owner / editor / viewer / commenter) is enforced
per-route below.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from apps.auth.dependencies import get_current_user
from apps.blog.containers import BlogContainer
from apps.blog.schemas import (
    CategoryResponse,
    CreateCategoryRequest,
    CreatePostRequest,
    CreateTagRequest,
    ListCategoriesRequest,
    ListPostsRequest,
    ListTagsRequest,
    PostDetailResponse,
    PostResponse,
    TagResponse,
    UpdateCategoryRequest,
    UpdatePostRequest,
    UpdateTagRequest,
)
from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.workspace.dependencies import require_workspace_member, require_workspace_role
from apps.workspace.enums import WorkspaceRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.blog.models import Post
    from apps.blog.services import CategoryService, PostService, TagService
    from apps.user.models import User
    from apps.workspace.models import Workspace

blog_admin_router = APIRouter(prefix="/workspaces/{workspace_slug}/blog", tags=["blog"])


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@blog_admin_router.get(
    "/categories",
    response_model=APIResponse[PaginatedResponse[CategoryResponse]],
)
@inject
async def list_categories(
    params: ListCategoriesRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    category_service: CategoryService = Depends(Provide[BlogContainer.category_service]),
) -> APIResponse[PaginatedResponse[CategoryResponse]]:
    """List categories. Any workspace member can view."""
    items, total = await category_service.list_categories(session, workspace_id=workspace.id, params=params)
    return APIResponse[PaginatedResponse[CategoryResponse]].success(
        data=PaginatedResponse[CategoryResponse](
            items=[CategoryResponse.model_validate(c) for c in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Categories retrieved successfully.",
    )


@blog_admin_router.post(
    "/categories",
    response_model=APIResponse[CategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_category(
    data: CreateCategoryRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    category_service: CategoryService = Depends(Provide[BlogContainer.category_service]),
) -> APIResponse[CategoryResponse]:
    """Create a category. Owner / editor only."""
    category = await category_service.create(session, workspace_id=workspace.id, data=data)
    return APIResponse[CategoryResponse].success(
        data=CategoryResponse.model_validate(category),
        message="Category created successfully.",
    )


@blog_admin_router.patch(
    "/categories/{category_id}",
    response_model=APIResponse[CategoryResponse],
)
@inject
async def update_category(
    category_id: uuid.UUID,
    data: UpdateCategoryRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    category_service: CategoryService = Depends(Provide[BlogContainer.category_service]),
) -> APIResponse[CategoryResponse]:
    """Partially update a category. Owner / editor only."""
    category = await category_service.update(
        session,
        workspace_id=workspace.id,
        category_id=category_id,
        data=data,
    )
    return APIResponse[CategoryResponse].success(
        data=CategoryResponse.model_validate(category),
        message="Category updated successfully.",
    )


@blog_admin_router.delete(
    "/categories/{category_id}",
    response_model=APIResponse[CategoryResponse],
)
@inject
async def delete_category(
    category_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    category_service: CategoryService = Depends(Provide[BlogContainer.category_service]),
) -> APIResponse[CategoryResponse]:
    """Soft-delete a category. Owner / editor only."""
    category = await category_service.soft_delete(
        session,
        workspace_id=workspace.id,
        category_id=category_id,
    )
    return APIResponse[CategoryResponse].success(
        data=CategoryResponse.model_validate(category),
        message="Category deleted successfully.",
    )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@blog_admin_router.get(
    "/tags",
    response_model=APIResponse[PaginatedResponse[TagResponse]],
)
@inject
async def list_tags(
    params: ListTagsRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    tag_service: TagService = Depends(Provide[BlogContainer.tag_service]),
) -> APIResponse[PaginatedResponse[TagResponse]]:
    """List tags. Any workspace member can view."""
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


@blog_admin_router.post(
    "/tags",
    response_model=APIResponse[TagResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_tag(
    data: CreateTagRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    tag_service: TagService = Depends(Provide[BlogContainer.tag_service]),
) -> APIResponse[TagResponse]:
    """Create a tag. Owner / editor only."""
    tag = await tag_service.create(session, workspace_id=workspace.id, data=data)
    return APIResponse[TagResponse].success(
        data=TagResponse.model_validate(tag),
        message="Tag created successfully.",
    )


@blog_admin_router.patch(
    "/tags/{tag_id}",
    response_model=APIResponse[TagResponse],
)
@inject
async def update_tag(
    tag_id: uuid.UUID,
    data: UpdateTagRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    tag_service: TagService = Depends(Provide[BlogContainer.tag_service]),
) -> APIResponse[TagResponse]:
    """Update a tag. Owner / editor only."""
    tag = await tag_service.update(session, workspace_id=workspace.id, tag_id=tag_id, data=data)
    return APIResponse[TagResponse].success(
        data=TagResponse.model_validate(tag),
        message="Tag updated successfully.",
    )


@blog_admin_router.delete(
    "/tags/{tag_id}",
    response_model=APIResponse[TagResponse],
)
@inject
async def delete_tag(
    tag_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    tag_service: TagService = Depends(Provide[BlogContainer.tag_service]),
) -> APIResponse[TagResponse]:
    """Hard-delete a tag. Owner / editor only."""
    tag = await tag_service.delete(session, workspace_id=workspace.id, tag_id=tag_id)
    return APIResponse[TagResponse].success(
        data=TagResponse.model_validate(tag),
        message="Tag deleted successfully.",
    )


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


@blog_admin_router.get(
    "/posts",
    response_model=APIResponse[PaginatedResponse[PostResponse]],
)
@inject
async def list_posts(
    params: ListPostsRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PaginatedResponse[PostResponse]]:
    """List posts (any status). Any workspace member can view drafts."""
    items, total = await post_service.list_posts(session, workspace_id=workspace.id, params=params)
    return APIResponse[PaginatedResponse[PostResponse]].success(
        data=PaginatedResponse[PostResponse](
            items=[PostResponse.model_validate(p) for p in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Posts retrieved successfully.",
    )


@blog_admin_router.post(
    "/posts",
    response_model=APIResponse[PostDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_post(
    data: CreatePostRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Create a draft post. Owner / editor only."""
    post = await post_service.create(
        session,
        workspace_id=workspace.id,
        author_id=current_user.id,
        data=data,
    )
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post created successfully.",
    )


@blog_admin_router.get(
    "/posts/{post_id}",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def get_post(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Fetch a single post (any status) by id. Any workspace member."""
    post = await post_service.find_or_raise(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        load_content=True,
    )
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post retrieved successfully.",
    )


@blog_admin_router.patch(
    "/posts/{post_id}",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def update_post(
    post_id: uuid.UUID,
    data: UpdatePostRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Partially update a post. Owner / editor only."""
    post = await post_service.update(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        data=data,
    )
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post updated successfully.",
    )


@blog_admin_router.post(
    "/posts/{post_id}/publish",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def publish_post(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Transition a post to ``published``. Owner / editor only."""
    post = await post_service.publish(session, workspace_id=workspace.id, post_id=post_id)
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post published successfully.",
    )


@blog_admin_router.post(
    "/posts/{post_id}/unpublish",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def unpublish_post(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Transition a post back to ``draft``. Owner / editor only."""
    post = await post_service.unpublish(session, workspace_id=workspace.id, post_id=post_id)
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post unpublished successfully.",
    )


@blog_admin_router.post(
    "/posts/{post_id}/archive",
    response_model=APIResponse[PostDetailResponse],
)
@inject
async def archive_post(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostDetailResponse]:
    """Transition a post to ``archived``. Owner / editor only."""
    post = await post_service.archive(session, workspace_id=workspace.id, post_id=post_id)
    return APIResponse[PostDetailResponse].success(
        data=_build_post_detail(post),
        message="Post archived successfully.",
    )


@blog_admin_router.delete(
    "/posts/{post_id}",
    response_model=APIResponse[PostResponse],
)
@inject
async def delete_post(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[PostResponse]:
    """Soft-delete a post. Owner / editor only."""
    post = await post_service.soft_delete(session, workspace_id=workspace.id, post_id=post_id)
    return APIResponse[PostResponse].success(
        data=PostResponse.model_validate(post),
        message="Post deleted successfully.",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_post_detail(post: Post) -> PostDetailResponse:
    """Hand-build :class:`PostDetailResponse` so we can inline the 1:1 content."""
    base = PostResponse.model_validate(post).model_dump()
    content = post.content
    return PostDetailResponse(
        **base,
        content_json=content.content_json if content is not None else {"type": "doc", "content": []},
        content_html=content.content_html if content is not None else "",
        content_text=content.content_text if content is not None else "",
        category=CategoryResponse.model_validate(post.category) if post.category is not None else None,
        tags=[TagResponse.model_validate(tag) for tag in post.tags],
    )
