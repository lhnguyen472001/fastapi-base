"""Authenticated blog admin routes — workspace-scoped CRUD.

All routes mount under ``/workspaces/{workspace_slug}/blog/...`` and are
gated by :func:`apps.workspace.dependencies.require_workspace_role`. The
role-permission matrix (owner / editor / viewer / commenter) is enforced
per-route below.
"""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.dependencies import get_current_user
from apps.blog.constants import AUTOSAVE_RATE_LIMIT
from apps.blog.containers import BlogContainer
from apps.blog.enums import CommentAuthorKind
from apps.blog.models import Post, PostComment
from apps.blog.schemas import (
    AutosavePostRequest,
    AutosaveResponse,
    CategoryResponse,
    CompareVersionsResult,
    CreateCategoryRequest,
    CreatePostRequest,
    CreateTagRequest,
    ListCategoriesRequest,
    ListPendingCommentsRequest,
    ListPostsRequest,
    ListPostVersionsRequest,
    ListTagsRequest,
    ModerationActionRequest,
    ModeratorPostCommentResponse,
    PostCommentResponse,
    PostDetailResponse,
    PostResponse,
    PostVersionDetailResponse,
    PostVersionResponse,
    ReconcileEngagementCountersResponse,
    RestorePostVersionRequest,
    RestoreVersionResult,
    TagResponse,
    UpdateCategoryRequest,
    UpdateCommentRequest,
    UpdatePostRequest,
    UpdateTagRequest,
)
from apps.blog.services import (
    CategoryService,
    PostCommentModerationService,
    PostCommentService,
    PostService,
    PostVersionService,
    TagService,
)
from apps.core.database.session import session_factory
from apps.core.rate_limit import limiter
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.rbac.dependencies import access_required
from apps.user.models import User
from apps.workspace.dependencies import require_workspace_member, require_workspace_role
from apps.workspace.enums import WorkspaceRole
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


@blog_admin_router.put(
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
# Post version history
# ---------------------------------------------------------------------------


@blog_admin_router.get(
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


@blog_admin_router.get(
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


@blog_admin_router.get(
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


@blog_admin_router.post(
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


# ---------------------------------------------------------------------------
# Self-edit / self-delete on own comments (US4, FR-019..FR-021)
# ---------------------------------------------------------------------------


@blog_admin_router.patch(
    "/comments/{comment_id}",
    response_model=APIResponse[PostCommentResponse],
)
@inject
async def edit_own_comment(
    comment_id: uuid.UUID,
    data: UpdateCommentRequest,
    workspace: Workspace = Depends(require_workspace_member()),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_comment_service: PostCommentService = Depends(
        Provide[BlogContainer.post_comment_service],
    ),
) -> APIResponse[PostCommentResponse]:
    """Author-only body edit within the configured window (FR-019).

    The workspace gate is membership-only so a non-member can't probe
    comment ids by id. Author-check is enforced in the service layer.
    """
    _ = workspace
    updated = await post_comment_service.edit_own(
        session,
        comment_id=comment_id,
        current_user_id=current_user.id,
        data=data,
    )
    return APIResponse[PostCommentResponse].success(
        data=updated,
        message="Comment updated successfully.",
    )


@blog_admin_router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def delete_own_comment(
    comment_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_member()),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    post_comment_service: PostCommentService = Depends(
        Provide[BlogContainer.post_comment_service],
    ),
) -> None:
    """Author-only delete (FR-020).

    Top-level rows with at least one approved live reply are tombstoned
    (body cleared, ``is_tombstoned=true``, ``deleted_at`` set); every
    other case (replies, top-level without approved replies) is hard
    deleted. Anonymous rows are immutable.
    """
    _ = workspace
    await post_comment_service.delete_own(
        session,
        comment_id=comment_id,
        current_user_id=current_user.id,
    )


# ---------------------------------------------------------------------------
# Moderation queue + actions (US5, FR-010d / FR-022 / FR-026)
# ---------------------------------------------------------------------------


def _to_moderator_response(row: PostComment) -> ModeratorPostCommentResponse:
    """Project a PostComment ORM row into the moderator-private shape.

    Moderators see the private fields (state, author_email, author_ip,
    moderation attribution) plus the body regardless of tombstone state.
    """
    kind = CommentAuthorKind.AUTHENTICATED if row.author_user_id is not None else CommentAuthorKind.ANONYMOUS
    display = row.author_display_name if row.author_user_id is None else None
    return ModeratorPostCommentResponse(
        id=row.id,
        post_id=row.post_id,
        parent_comment_id=row.parent_comment_id,
        author_kind=kind.value,
        author={  # type: ignore[arg-type]
            "display_name": display or "[deleted]",
            "user_id": row.author_user_id,
            "username": None,
        },
        body=row.body,
        edited_at=row.edited_at,
        created_at=row.created_at,
        is_tombstoned=row.is_tombstoned,
        reply_count=0,
        state=row.state,
        author_email=row.author_email,
        author_ip=str(row.author_ip) if row.author_ip is not None else None,
        moderation_reason=row.moderation_reason,
        moderated_by_user_id=row.moderated_by_user_id,
        moderated_at=row.moderated_at,
        deleted_at=row.deleted_at,
    )


@blog_admin_router.get(
    "/comments/pending",
    response_model=APIResponse[PaginatedResponse[ModeratorPostCommentResponse]],
)
@inject
async def list_pending_comments(
    params: ListPendingCommentsRequest = Depends(),
    workspace: Workspace = Depends(require_workspace_member()),
    _: User = Depends(access_required("blog", "moderate_comments")),
    session: AsyncSession = Depends(session_factory),
    moderation_service: PostCommentModerationService = Depends(
        Provide[BlogContainer.post_comment_moderation_service],
    ),
) -> APIResponse[PaginatedResponse[ModeratorPostCommentResponse]]:
    """List pending comments for the workspace (oldest-first, FR-010d).

    Optional ``post_id`` narrows the queue to a single post. Gated by
    the ``blog:moderate_comments`` Casbin policy seeded in the engagement
    migration.
    """
    rows, total = await moderation_service.list_pending(
        session,
        workspace_id=workspace.id,
        post_id=params.post_id,
        limit=params.limit,
        offset=params.offset,
    )
    return APIResponse[PaginatedResponse[ModeratorPostCommentResponse]].success(
        data=PaginatedResponse[ModeratorPostCommentResponse](
            items=[_to_moderator_response(r) for r in rows],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Pending comments retrieved successfully.",
    )


@blog_admin_router.post(
    "/comments/{comment_id}/approve",
    response_model=APIResponse[ModeratorPostCommentResponse],
)
@inject
async def approve_comment(
    comment_id: uuid.UUID,
    data: ModerationActionRequest,
    workspace: Workspace = Depends(require_workspace_member()),
    moderator: User = Depends(access_required("blog", "moderate_comments")),
    session: AsyncSession = Depends(session_factory),
    moderation_service: PostCommentModerationService = Depends(
        Provide[BlogContainer.post_comment_moderation_service],
    ),
) -> APIResponse[ModeratorPostCommentResponse]:
    """Transition a pending comment to ``approved``. RBAC required."""
    _ = workspace
    updated = await moderation_service.approve(
        session,
        comment_id=comment_id,
        moderator_user_id=moderator.id,
        data=data,
    )
    return APIResponse[ModeratorPostCommentResponse].success(
        data=_to_moderator_response(updated),
        message="Comment approved.",
    )


@blog_admin_router.post(
    "/comments/{comment_id}/reject",
    response_model=APIResponse[ModeratorPostCommentResponse],
)
@inject
async def reject_comment(
    comment_id: uuid.UUID,
    data: ModerationActionRequest,
    workspace: Workspace = Depends(require_workspace_member()),
    moderator: User = Depends(access_required("blog", "moderate_comments")),
    session: AsyncSession = Depends(session_factory),
    moderation_service: PostCommentModerationService = Depends(
        Provide[BlogContainer.post_comment_moderation_service],
    ),
) -> APIResponse[ModeratorPostCommentResponse]:
    """Reject a comment (terminal). RBAC required."""
    _ = workspace
    updated = await moderation_service.reject(
        session,
        comment_id=comment_id,
        moderator_user_id=moderator.id,
        data=data,
    )
    return APIResponse[ModeratorPostCommentResponse].success(
        data=_to_moderator_response(updated),
        message="Comment rejected.",
    )


@blog_admin_router.delete(
    "/comments/{comment_id}/moderator",
    response_model=APIResponse[ModeratorPostCommentResponse],
)
@inject
async def moderator_delete_comment(
    comment_id: uuid.UUID,
    data: ModerationActionRequest,
    workspace: Workspace = Depends(require_workspace_member()),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(session_factory),
    moderation_service: PostCommentModerationService = Depends(
        Provide[BlogContainer.post_comment_moderation_service],
    ),
) -> APIResponse[ModeratorPostCommentResponse]:
    """Moderator delete (FR-022). RBAC OR post-author.

    The route mounts only ``get_current_user`` so a post-author who does
    NOT hold the RBAC permission can still reach the handler; the
    service enforces the OR-check.
    """
    _ = workspace
    updated = await moderation_service.moderator_delete(
        session,
        comment_id=comment_id,
        current_user_id=current_user.id,
        data=data,
    )
    return APIResponse[ModeratorPostCommentResponse].success(
        data=_to_moderator_response(updated),
        message="Comment moderator-deleted.",
    )


@blog_admin_router.post(
    "/posts/{post_id}/reconcile-engagement-counters",
    response_model=APIResponse[ReconcileEngagementCountersResponse],
)
@inject
async def reconcile_engagement_counters(
    post_id: uuid.UUID,
    workspace: Workspace = Depends(require_workspace_member()),
    _: User = Depends(access_required("blog", "moderate_comments")),
    session: AsyncSession = Depends(session_factory),
    moderation_service: PostCommentModerationService = Depends(
        Provide[BlogContainer.post_comment_moderation_service],
    ),
) -> APIResponse[ReconcileEngagementCountersResponse]:
    """Recompute ``posts.like_count`` + ``posts.comment_count`` from scalars (FR-026).

    Non-blocking for public read paths — the UPDATE on a single posts row
    holds a short row-lock that doesn't interfere with concurrent SELECTs
    under READ COMMITTED. RBAC required.
    """
    _ = workspace
    result = await moderation_service.reconcile_counters(session, post_id=post_id)
    return APIResponse[ReconcileEngagementCountersResponse].success(
        data=result,
        message="Engagement counters reconciled.",
    )
