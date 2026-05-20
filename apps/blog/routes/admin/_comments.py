"""Workspace admin routes: comment self-edit/delete + moderation + reconcile."""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.dependencies import get_current_user
from apps.blog.containers import BlogContainer
from apps.blog.enums import CommentAuthorKind
from apps.blog.models import PostComment
from apps.blog.schemas import (
    ListPendingCommentsRequest,
    ModerationActionRequest,
    ModeratorPostCommentResponse,
    PostCommentResponse,
    ReconcileEngagementCountersResponse,
    UpdateCommentRequest,
)
from apps.blog.services import PostCommentModerationService, PostCommentService
from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, PaginatedResponse
from apps.rbac.dependencies import access_required
from apps.user.models import User
from apps.workspace.dependencies import require_workspace_member
from apps.workspace.models import Workspace

router = APIRouter()


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


# ---------------------------------------------------------------------------
# Self-edit / self-delete on own comments (US4, FR-019..FR-021)
# ---------------------------------------------------------------------------


@router.patch(
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


@router.delete(
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


@router.get(
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


@router.post(
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


@router.post(
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


@router.delete(
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


@router.post(
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
