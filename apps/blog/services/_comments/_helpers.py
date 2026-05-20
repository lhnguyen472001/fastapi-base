"""Stateless helpers shared by :class:`PostCommentService` and its tests.

* :func:`_sanitize_comment_body` runs ``nh3`` so the stored body is
  plain text only.
* :func:`_author_from_row` / :func:`_row_to_response` project ORM rows
  into the public :class:`PostCommentAuthor` / :class:`PostCommentResponse`
  shapes.
* :func:`_parse_ip` best-effort parses the optional source IP for
  anonymous comments.
"""

from __future__ import annotations

import ipaddress
import uuid

import nh3

from apps.blog.enums import CommentAuthorKind
from apps.blog.models import PostComment
from apps.blog.schemas import PostCommentAuthor, PostCommentResponse

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
