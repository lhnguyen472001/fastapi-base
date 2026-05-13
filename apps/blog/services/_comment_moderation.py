"""Moderation service — pending queue, approve / reject, moderator-delete,
reconcile-engagement-counters (US5 of specs/003-post-likes-comments).

The two-axis lifecycle (data-model §3) means the counter math comes "for
free" from the PG triggers on every state / deleted_at transition. This
service issues the underlying UPDATEs and lets the trigger do the
arithmetic; the only exception is :meth:`reconcile_counters`, which is
the operator-callable drift-correction path that overwrites the cached
counters from authoritative scalar SELECTs.

The moderator-delete branch is RBAC OR post-author: callers without the
``blog:moderate_comments`` permission are still allowed through when
they authored the post being moderated (FR-022). The OR-check is in the
service so it can inspect per-row data (the post's ``author_id``); the
route layer therefore mounts only ``Depends(get_current_user)`` for that
endpoint and lets this method enforce the policy.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from loguru import logger

from apps.blog.enums import CommentState
from apps.blog.exceptions import (
    CommentNotFoundError,
    CommentNotPendingError,
    PostNotFoundError,
)
from apps.blog.repositories import (
    PostCommentModerationRepository,
    PostRepository,
)
from apps.blog.schemas import (
    EngagementCounters,
    ModerationActionRequest,
    ReconcileEngagementCountersResponse,
)
from apps.core.database.transactional import transactional
from apps.rbac.exceptions import AccessDeniedError

if TYPE_CHECKING:
    from apps.blog.models import Post, PostComment
    from apps.core.database.types import SessionType
    from apps.rbac.services import AccessService


_MODERATE_RESOURCE = "blog"
_MODERATE_ACTION = "moderate_comments"


class PostCommentModerationService:
    """Moderator-side comment lifecycle service.

    All write methods are wrapped in :func:`transactional` so a failed
    state transition leaves no half-stamped attribution columns behind.
    """

    def __init__(
        self,
        repository: PostCommentModerationRepository,
        post_repository: PostRepository,
        access_service: AccessService,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository
        self.access_service = access_service

    async def list_pending(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PostComment], int]:
        """Return ``(rows, total)`` for the pending queue (FR-010d)."""
        return await self.repository.list_pending(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            limit=limit,
            offset=offset,
        )

    @transactional
    async def approve(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        moderator_user_id: uuid.UUID,
        data: ModerationActionRequest,
    ) -> PostComment:
        """Transition ``pending → approved``.

        Trigger ticks ``posts.comment_count`` +1 because the row now
        satisfies the contribution predicate. Raises
        :class:`CommentNotPendingError` (409) if the row is in any other
        state.
        """
        comment = await self._require_existing_comment(session, comment_id=comment_id)
        if comment.state != CommentState.PENDING.value:
            msg = f"Comment {comment_id} is not pending (state={comment.state})."
            raise CommentNotPendingError(message=msg)

        updated = await self.repository.transition_state(
            session,
            comment_id=comment_id,
            new_state=CommentState.APPROVED.value,
            moderator_id=moderator_user_id,
            moderated_at=_now(),
            reason=data.moderation_reason,
        )
        logger.info(
            "PostCommentModerationService - approve - comment_id={cid} moderator_id={mid}",
            cid=comment_id,
            mid=moderator_user_id,
        )
        return updated

    @transactional
    async def reject(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        moderator_user_id: uuid.UUID,
        data: ModerationActionRequest,
    ) -> PostComment:
        """Transition to ``rejected``.

        Trigger handles the counter math: ``pending → rejected`` is a
        no-op; ``approved → rejected`` drops the counter by 1 (data-model
        §3). Re-rejecting an already-rejected row is a no-op surfaced as
        :class:`CommentNotPendingError` to avoid silent double-attribution.
        """
        comment = await self._require_existing_comment(session, comment_id=comment_id)
        if comment.state == CommentState.REJECTED.value:
            msg = f"Comment {comment_id} is already rejected."
            raise CommentNotPendingError(message=msg)

        updated = await self.repository.transition_state(
            session,
            comment_id=comment_id,
            new_state=CommentState.REJECTED.value,
            moderator_id=moderator_user_id,
            moderated_at=_now(),
            reason=data.moderation_reason,
        )
        logger.info(
            "PostCommentModerationService - reject - comment_id={cid} moderator_id={mid}",
            cid=comment_id,
            mid=moderator_user_id,
        )
        return updated

    @transactional
    async def moderator_delete(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
        current_user_id: uuid.UUID,
        data: ModerationActionRequest,
    ) -> PostComment:
        """Moderator soft-delete (FR-022). RBAC OR post-author.

        Allowed iff the caller holds ``blog:moderate_comments`` OR is the
        author of the comment's post; otherwise raises
        :class:`AccessDeniedError` (403). Trigger drops the counter by 1
        iff the row was contributing (``state = 'approved' AND
        deleted_at IS NULL``) before the UPDATE.
        """
        comment = await self._require_existing_comment(session, comment_id=comment_id)

        is_moderator = await self.access_service.check(
            user_id=current_user_id,
            resource=_MODERATE_RESOURCE,
            action=_MODERATE_ACTION,
        )
        if not is_moderator:
            post = await self._find_post_by_id_any_workspace(session, post_id=comment.post_id)
            if post is None or post.author_id != current_user_id:
                msg = "Caller lacks moderation permission and is not the post author."
                raise AccessDeniedError(message=msg)

        updated = await self.repository.mark_moderator_deleted(
            session,
            comment_id=comment_id,
            moderator_id=current_user_id,
            moderated_at=_now(),
            reason=data.moderation_reason,
        )
        logger.info(
            "PostCommentModerationService - moderator_delete - comment_id={cid} moderator_id={mid}",
            cid=comment_id,
            mid=current_user_id,
        )
        return updated

    @transactional
    async def reconcile_counters(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> ReconcileEngagementCountersResponse:
        """Operator-callable drift correction (FR-026 / research §15).

        Reads the cached counters, computes the authoritative scalar
        counts, overwrites the cached counters, and returns a before/
        after envelope with a ``drift_corrected`` flag for audit.

        Looks up the post via the bypass helper because the reconcile
        route is RBAC-gated (``blog:moderate_comments``) rather than
        workspace-membership-gated; the caller cannot be assumed to know
        the post's workspace slug.
        """
        cached = await self.post_repository.find_cached_counters(session, post_id=post_id)
        if cached is None:
            raise PostNotFoundError(message=f"Post {post_id} not found.")
        before = EngagementCounters(like_count=cached[0], comment_count=cached[1])
        like_count, comment_count = await self.post_repository.scalar_counts_for_reconcile(
            session,
            post_id=post_id,
        )
        await self.post_repository.update_counters(
            session,
            post_id=post_id,
            like_count=like_count,
            comment_count=comment_count,
        )
        after = EngagementCounters(like_count=like_count, comment_count=comment_count)
        drift = before.like_count != after.like_count or before.comment_count != after.comment_count
        logger.info(
            "PostCommentModerationService - reconcile_counters - post_id={pid} drift={drift}",
            pid=post_id,
            drift=drift,
        )
        return ReconcileEngagementCountersResponse(
            post_id=post_id,
            before=before,
            after=after,
            drift_corrected=drift,
        )

    async def _require_existing_comment(
        self,
        session: SessionType,
        *,
        comment_id: uuid.UUID,
    ) -> PostComment:
        comment = await self.repository.find_by_id(session, comment_id=comment_id)
        if comment is None:
            raise CommentNotFoundError(message=f"Comment {comment_id} not found.")
        return comment

    async def _find_post_by_id_any_workspace(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> Post | None:
        """Direct post lookup, bypassing the workspace filter.

        Moderation endpoints are RBAC-gated rather than workspace-scoped,
        so the caller knows the comment's ``post_id`` but not necessarily
        its workspace. A direct lookup by id is safe because the route
        layer already enforced ``blog:moderate_comments``.
        """
        from sqlalchemy import select  # noqa: PLC0415

        from apps.blog.models import Post  # noqa: PLC0415

        stmt = select(Post).where(Post.id == post_id)
        return (await session.execute(stmt)).scalar_one_or_none()


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)
