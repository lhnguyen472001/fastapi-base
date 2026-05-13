"""Post-like service — like / unlike / liked-by-me state.

Implements US1 of specs/003-post-likes-comments. The service composes
:class:`apps.blog.repositories.PostLikeRepository` (the like-row writer)
with :class:`apps.blog.repositories.PostRepository` (to load and validate
the target post + read the authoritative ``Post.like_count``). Counter
maintenance is handled by the PG triggers installed in the engagement
migration (data-model §4); this service never touches ``Post.like_count``
directly.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

from apps.blog.enums import PostStatus
from apps.blog.exceptions import PostEngagementClosedError, PostNotFoundError
from apps.blog.repositories import PostLikeRepository, PostRepository
from apps.blog.schemas import LikerResponse, LikeState
from apps.core.database.transactional import transactional
from apps.core.schemas.response import PaginatedResponse

if TYPE_CHECKING:
    from apps.blog.models import Post
    from apps.core.database.types import SessionType


class PostLikeService:
    """Like flow on a published post.

    All mutations route through :class:`PostLikeRepository.add_idempotent`
    or :meth:`remove`; the per-(post, user) UNIQUE constraint plus
    ``INSERT … ON CONFLICT DO NOTHING`` guarantees FR-002 idempotency
    without an application-level lock.
    """

    def __init__(
        self,
        repository: PostLikeRepository,
        post_repository: PostRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository

    @transactional
    async def like(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> LikeState:
        """Apply a like for ``user_id`` on ``post_id`` (idempotent).

        Raises:
            PostNotFoundError: When the post does not exist in the workspace.
            PostEngagementClosedError: When the post is soft-deleted or
                archived (FR-008 / FR-015).
        """
        post = await self._load_open_post(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )
        inserted = await self.repository.add_idempotent(
            session,
            post_id=post.id,
            user_id=user_id,
            workspace_id=post.workspace_id,
        )
        if inserted:
            logger.info(
                "PostLikeService - like - post_id={post_id} user_id={user_id}",
                post_id=post.id,
                user_id=user_id,
            )
        return await self._like_state_for(session, post=post, user_id=user_id)

    @transactional
    async def unlike(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> LikeState:
        """Remove ``user_id``'s like on ``post_id`` (idempotent — no-op when absent)."""
        post = await self._load_open_post(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )
        removed = await self.repository.remove(session, post_id=post.id, user_id=user_id)
        if removed:
            logger.info(
                "PostLikeService - unlike - post_id={post_id} user_id={user_id}",
                post_id=post.id,
                user_id=user_id,
            )
        return await self._like_state_for(session, post=post, user_id=user_id)

    async def _load_open_post(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        """Load the post + reject mutations on closed (soft-deleted / archived) rows.

        Cross-workspace requests surface as ``PostNotFoundError`` (not
        ``ForbiddenError``) per FR-027 — same response shape as
        not-found masks existence.
        """
        post = await self.post_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            include_deleted=False,
            load_content=False,
        )
        if post is None:
            raise PostNotFoundError(message="Post not found.")
        if post.status == PostStatus.ARCHIVED.value:
            raise PostEngagementClosedError(message="Post is archived and not accepting engagement.")
        return post

    async def _like_state_for(
        self,
        session: SessionType,
        *,
        post: Post,
        user_id: uuid.UUID,
    ) -> LikeState:
        """Compose the LikeState response for the post-after-mutation."""
        liked = await self.repository.exists_for_user(
            session,
            post_id=post.id,
            user_id=user_id,
        )
        like_count = await self.repository.count_for_post(session, post_id=post.id)
        return LikeState(post_id=post.id, like_count=like_count, liked_by_me=liked)

    async def probe_liked_by_me(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Return whether ``user_id`` has liked ``post_id``.

        Used by the public post-detail route to populate
        :attr:`apps.blog.schemas.PostDetailResponse.liked_by_me` for
        authenticated callers (FR-006).
        """
        return await self.repository.exists_for_user(
            session,
            post_id=post_id,
            user_id=user_id,
        )

    async def list_likers(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> PaginatedResponse[LikerResponse]:
        """Paginated newest-first list of users who liked ``post_id`` (US6).

        Cross-workspace and soft-deleted requests surface as
        :class:`PostNotFoundError` (404 mask per FR-027); archived posts
        remain readable because this endpoint is a read path
        (FR-008 / FR-015 reject mutations only).
        """
        post = await self.post_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            include_deleted=False,
            load_content=False,
        )
        if post is None:
            raise PostNotFoundError(message="Post not found.")
        rows, total = await self.repository.list_likers(
            session,
            post_id=post.id,
            limit=limit,
            offset=offset,
        )
        items = [
            LikerResponse(
                user_id=row.user.id,
                username=row.user.username,
                liked_at=row.created_at,
            )
            for row in rows
        ]
        return PaginatedResponse[LikerResponse](
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
