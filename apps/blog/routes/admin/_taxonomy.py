"""Workspace admin routes: Category + Tag CRUD."""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.blog.containers import BlogContainer
from apps.blog.schemas import (
    CategoryResponse,
    CreateCategoryRequest,
    CreateTagRequest,
    ListCategoriesRequest,
    ListTagsRequest,
    TagResponse,
    UpdateCategoryRequest,
    UpdateTagRequest,
)
from apps.blog.services import CategoryService, TagService
from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.workspace.dependencies import require_workspace_member, require_workspace_role
from apps.workspace.enums import WorkspaceRole
from apps.workspace.models import Workspace

router = APIRouter()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.get(
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


@router.post(
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


@router.patch(
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


@router.delete(
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


@router.get(
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


@router.post(
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


@router.patch(
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


@router.delete(
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
