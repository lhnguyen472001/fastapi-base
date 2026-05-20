"""Workspace admin routes: Post CRUD + autosave + publishing + version history."""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.dependencies import get_current_user
from apps.blog.constants import AUTOSAVE_RATE_LIMIT
from apps.blog.containers import BlogContainer
from apps.blog.models import Post
from apps.blog.schemas import (
    AutosavePostRequest,
    AutosaveResponse,
    CategoryResponse,
    CompareVersionsResult,
    CreatePostRequest,
    ListPostsRequest,
    ListPostVersionsRequest,
    PostDetailResponse,
    PostResponse,
    PostVersionDetailResponse,
    PostVersionResponse,
    RestorePostVersionRequest,
    RestoreVersionResult,
    TagResponse,
    UpdatePostRequest,
)
from apps.blog.services import PostService, PostVersionService
from apps.core.database.session import session_factory
from apps.core.rate_limit import limiter
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.user.models import User
from apps.workspace.dependencies import require_workspace_member, require_workspace_role
from apps.workspace.enums import WorkspaceRole
from apps.workspace.models import Workspace

router = APIRouter()


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


# ---------------------------------------------------------------------------
# Posts — CRUD
# ---------------------------------------------------------------------------


@router.get(
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


@router.post(
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


@router.get(
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
    """Fetch a single post (any status) by id. Any workspace member.

    Merges any pending autosave snapshot from Redis over the Postgres
    state so the editor sees the latest keystrokes after a tab refresh.
    """
    detail = await post_service.get_for_admin(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
    )
    return APIResponse[PostDetailResponse].success(
        data=detail,
        message="Post retrieved successfully.",
    )


@router.patch(
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


@router.delete(
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
# Autosave
# ---------------------------------------------------------------------------


@router.put(
    "/posts/{post_id}/autosave",
    response_model=APIResponse[AutosaveResponse],
)
@limiter.limit(AUTOSAVE_RATE_LIMIT)
@inject
async def autosave_post(
    request: Request,
    post_id: uuid.UUID,
    data: AutosavePostRequest,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_service: PostService = Depends(Provide[BlogContainer.post_service]),
) -> APIResponse[AutosaveResponse]:
    """Persist a draft body snapshot to Redis (write-behind to Postgres).

    Lightweight by design: no slug / category / tag validation, no full
    Tiptap render. The body is hashed; an unchanged hash is a no-op.
    Owner / editor only. Rate-limited per remote address.
    """
    content_hash, word_count, reading_minutes, updated_at, persisted = await post_service.autosave(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        author_id=current_user.id,
        content_json=data.content_json,
    )
    return APIResponse[AutosaveResponse].success(
        data=AutosaveResponse(
            post_id=post_id,
            content_hash=content_hash,
            word_count=word_count,
            reading_minutes=reading_minutes,
            updated_at=updated_at,
            persisted=persisted,
        ),
        message="Autosave accepted.",
    )


# ---------------------------------------------------------------------------
# Publishing — publish unpublish archive
# ---------------------------------------------------------------------------


@router.post(
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


@router.post(
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


@router.post(
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


# ---------------------------------------------------------------------------
# Post version history
# ---------------------------------------------------------------------------


@router.get(
    "/posts/{post_id}/versions",
    response_model=APIResponse[PaginatedResponse[PostVersionResponse]],
)
@inject
async def list_post_versions(
    post_id: uuid.UUID,
    params: ListPostVersionsRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    post_version_service: PostVersionService = Depends(Provide[BlogContainer.post_version_service]),
) -> APIResponse[PaginatedResponse[PostVersionResponse]]:
    """List versions for a post (newest-first). Any workspace member can view."""
    page = await post_version_service.list_for_post(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        limit=params.limit,
        offset=params.offset,
    )
    return APIResponse[PaginatedResponse[PostVersionResponse]].success(
        data=page,
        message="Post versions retrieved successfully.",
    )


@router.get(
    "/posts/{post_id}/versions/compare",
    response_model=APIResponse[CompareVersionsResult],
)
@inject
async def compare_post_versions(
    post_id: uuid.UUID,
    from_version: int = Query(..., alias="from", ge=1),
    to_version: int = Query(..., alias="to", ge=1),
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    post_version_service: PostVersionService = Depends(Provide[BlogContainer.post_version_service]),
) -> APIResponse[CompareVersionsResult]:
    """Structured line-diff between two versions of the same post.

    Both ``from`` and ``to`` MUST belong to ``post_id``. Combined input
    over the configured byte cap returns 413; identical from/to is 422.
    """
    result = await post_version_service.compare(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        from_version=from_version,
        to_version=to_version,
    )
    return APIResponse[CompareVersionsResult].success(
        data=result,
        message="Post versions compared successfully.",
    )


@router.get(
    "/posts/{post_id}/versions/{version}",
    response_model=APIResponse[PostVersionDetailResponse],
)
@inject
async def get_post_version(
    post_id: uuid.UUID,
    version: int,
    workspace: Workspace = Depends(require_workspace_member()),
    session: AsyncSession = Depends(session_factory),
    post_version_service: PostVersionService = Depends(Provide[BlogContainer.post_version_service]),
) -> APIResponse[PostVersionDetailResponse]:
    """Fetch the full historical content of one version. Any workspace member."""
    detail = await post_version_service.get_for_post(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        version=version,
    )
    return APIResponse[PostVersionDetailResponse].success(
        data=detail,
        message="Post version retrieved successfully.",
    )


@router.post(
    "/posts/{post_id}/versions/{version}/restore",
    response_model=APIResponse[RestoreVersionResult],
)
@inject
async def restore_post_version(
    post_id: uuid.UUID,
    version: int,
    data: RestorePostVersionRequest | None = None,
    workspace: Workspace = Depends(require_workspace_role(WorkspaceRole.OWNER, WorkspaceRole.EDITOR)),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_version_service: PostVersionService = Depends(Provide[BlogContainer.post_version_service]),
) -> APIResponse[RestoreVersionResult]:
    """Restore a historical version as the post's working copy. Owner / editor only.

    Does NOT change the post's publication status. The new version row
    captures the restored state so the restore itself is reversible.
    """
    result = await post_version_service.restore(
        session,
        workspace_id=workspace.id,
        post_id=post_id,
        version=version,
        actor_id=current_user.id,
        change_note=data.change_note if data is not None else None,
    )
    return APIResponse[RestoreVersionResult].success(
        data=result,
        message="Post version restored successfully.",
    )
