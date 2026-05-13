"""Post-comment service — auth + anonymous create, list (US2).

Implements US2 of specs/003-post-likes-comments. Authenticated callers
submit comments that are born ``approved`` (visible immediately, counter
ticks +1 via the PG trigger). Anonymous callers submit through the same
endpoint and land in ``pending`` (visible only to moderators; counter
unchanged) provided the workspace's ``allow_anonymous_comments`` flag is
ON — otherwise the request returns the same not-found shape used to
mask cross-workspace probes (FR-010b).

Body sanitization is strict: all HTML tags + attributes are stripped
via ``nh3.clean(..., tags=set(), attributes={})`` per research §5, so
no untrusted markup can ever reach another reader's browser (SC-008).
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import TYPE_CHECKING

import nh3
from loguru import logger

from apps.blog.enums import CommentAuthorKind, CommentState, PostStatus
from apps.blog.exceptions import (
    AnonymousCommentsDisabledError,
    PostEngagementClosedError,
    PostNotFoundError,
)
from apps.blog.repositories import PostCommentRepository, PostRepository
from apps.blog.schemas import (
    CreateAnonymousCommentRequest,
    CreateAuthenticatedCommentRequest,
    PostCommentAuthor,
    PostCommentResponse,
)
from apps.core.database.transactional import transactional
from apps.core.schemas.response import PaginatedResponse

if TYPE_CHECKING:
    from apps.blog.models import Post, PostComment
    from apps.core.database.types import SessionType
    from apps.workspace.models import Workspace


_DELETED_USER_DISPLAY = "[deleted]"


def _sanitize_comment_body(raw: str) -> str:
    """Strip every HTML tag/attribute from ``raw``; preserve text + line breaks.

    Returns the canonical stored form. The Pydantic request schema has
    already stripped surrounding whitespace; this function additionally
    neutralizes any markup, so the stored body is plain text only.
    """
    return nh3.clean(
        raw,
        tags=set(),
        attributes={},
        strip_comments=True,
    )


class PostCommentService:
    """Comment lifecycle service for auth + anonymous create + list."""

    def __init__(
        self,
        repository: PostCommentRepository,
        post_repository: PostRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository

    @transactional
    async def create_authenticated(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        author_user_id: uuid.UUID,
        data: CreateAuthenticatedCommentRequest,
    ) -> PostCommentResponse:
        """Submit an authenticated top-level comment on a published post.

        Born ``approved``; the PG INSERT trigger increments
        ``posts.comment_count`` atomically.
        """
        post = await self._load_open_post(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )
        body = _sanitize_comment_body(data.body)
        row = await self.repository.insert(
            session,
            data={
                "post_id": post.id,
                "workspace_id": post.workspace_id,
                "author_user_id": author_user_id,
                "author_display_name": None,
                "body": body,
                "state": CommentState.APPROVED.value,
            },
        )
        logger.info(
            "PostCommentService - create_authenticated - "
            "post_id={post_id} comment_id={comment_id} author_user_id={author_user_id}",
            post_id=post.id,
            comment_id=row.id,
            author_user_id=author_user_id,
        )
        usernames = await self.repository.fetch_author_usernames(
            session,
            user_ids=[author_user_id],
        )
        author = PostCommentAuthor(
            display_name=usernames.get(author_user_id, _DELETED_USER_DISPLAY),
            user_id=author_user_id,
            username=usernames.get(author_user_id),
        )
        return _row_to_response(row, author=author, reply_count=0)

    @transactional
    async def create_anonymous(
        self,
        session: SessionType,
        *,
        workspace: Workspace,
        post_id: uuid.UUID,
        data: CreateAnonymousCommentRequest,
        source_ip: str | None,
    ) -> PostCommentResponse:
        """Submit an anonymous top-level comment.

        Gated by ``workspace.allow_anonymous_comments`` (FR-010b);
        rejected with the same 404-shape used by cross-workspace probes
        when the flag is OFF, so the flag's state isn't observable.

        Born ``pending``; the PG INSERT trigger predicate filters this
        out, so ``posts.comment_count`` does NOT move. The counter ticks
        only when a moderator transitions the row to ``approved``
        (Phase 7 / FR-010d).
        """
        if not workspace.allow_anonymous_comments:
            raise AnonymousCommentsDisabledError(message="Post not found.")

        post = await self._load_open_post(
            session,
            workspace_id=workspace.id,
            post_id=post_id,
        )
        body = _sanitize_comment_body(data.body)
        ip = _parse_ip(source_ip)
        row = await self.repository.insert(
            session,
            data={
                "post_id": post.id,
                "workspace_id": post.workspace_id,
                "author_user_id": None,
                "author_display_name": data.author_display_name,
                "author_email": data.author_email,
                "author_ip": ip,
                "body": body,
                "state": CommentState.PENDING.value,
            },
        )
        logger.info(
            "PostCommentService - create_anonymous - post_id={post_id} comment_id={comment_id} display={display}",
            post_id=post.id,
            comment_id=row.id,
            display=data.author_display_name,
        )
        author = PostCommentAuthor(
            display_name=data.author_display_name,
            user_id=None,
            username=None,
        )
        return _row_to_response(row, author=author, reply_count=0)

    async def list_top_level(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> PaginatedResponse[PostCommentResponse]:
        """List approved top-level comments for a public post (FR-017).

        Cross-workspace requests surface as ``PostNotFoundError``; the
        list itself is a single SELECT plus one batched username fetch
        plus one batched reply-count fetch — three round-trips total for
        a page, regardless of page size.
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

        rows, total = await self.repository.list_top_level_approved(
            session,
            post_id=post.id,
            limit=limit,
            offset=offset,
        )

        author_ids = [r.author_user_id for r in rows if r.author_user_id is not None]
        usernames = await self.repository.fetch_author_usernames(
            session,
            user_ids=author_ids,
        )
        reply_counts = await self.repository.count_replies(
            session,
            parent_ids=[r.id for r in rows],
        )

        items = [
            _row_to_response(
                r,
                author=_author_from_row(r, usernames),
                reply_count=reply_counts.get(r.id, 0),
            )
            for r in rows
        ]
        return PaginatedResponse[PostCommentResponse](
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def _load_open_post(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        """Load and validate the target post is open for engagement."""
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


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _author_from_row(row: PostComment, usernames: dict[uuid.UUID, str]) -> PostCommentAuthor:
    """Compose the PostCommentAuthor from an ORM row + the username lookup."""
    if row.author_user_id is not None:
        return PostCommentAuthor(
            display_name=usernames.get(row.author_user_id, _DELETED_USER_DISPLAY),
            user_id=row.author_user_id,
            username=usernames.get(row.author_user_id),
        )
    return PostCommentAuthor(
        display_name=row.author_display_name or _DELETED_USER_DISPLAY,
        user_id=None,
        username=None,
    )


def _row_to_response(
    row: PostComment,
    *,
    author: PostCommentAuthor,
    reply_count: int,
) -> PostCommentResponse:
    """Project a PostComment row into the public response shape."""
    kind = CommentAuthorKind.AUTHENTICATED if row.author_user_id is not None else CommentAuthorKind.ANONYMOUS
    body = None if row.is_tombstoned else row.body
    return PostCommentResponse(
        id=row.id,
        post_id=row.post_id,
        parent_comment_id=row.parent_comment_id,
        author_kind=kind.value,
        author=author,
        body=body,
        edited_at=row.edited_at,
        created_at=row.created_at,
        is_tombstoned=row.is_tombstoned,
        reply_count=reply_count,
    )


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Best-effort parse of the source IP for anonymous-comment storage."""
    if value is None:
        return None
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None
