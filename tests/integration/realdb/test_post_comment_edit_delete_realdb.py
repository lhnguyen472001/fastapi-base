"""Real-DB integration tests for self-edit / self-delete (T052).

Covers US4 / FR-019..FR-021:
* author can edit own comment within window; edited_at set
* edit window expiry rejected (CommentEditWindowExpiredError, 403)
* non-author edit rejected (CommentAuthorForbiddenError, 403)
* anonymous-authored comment is immutable (AnonymousAuthorImmutableError, 403)
* author can hard-delete own comment when no approved replies; counter -1
* author tombstones top-level with approved replies; counter -1
* author can hard-delete own reply; counter -1
* non-author delete rejected (CommentAuthorForbiddenError, 403)
* anonymous-authored delete rejected (AnonymousAuthorImmutableError, 403)
* delete-missing id surfaces as CommentNotFoundError (404)
* edit re-sanitizes the body
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update

from apps.blog.enums import CommentState, PostStatus
from apps.blog.exceptions import (
    AnonymousAuthorImmutableError,
    CommentAuthorForbiddenError,
    CommentEditWindowExpiredError,
    CommentNotFoundError,
)
from apps.blog.models import PostComment
from apps.blog.repositories import (
    CategoryRepository,
    PostCommentRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import (
    CreateAnonymousCommentRequest,
    CreateAuthenticatedCommentRequest,
    CreatePostRequest,
    HeroQuote,
    UpdateCommentRequest,
)
from apps.blog.services import PostCommentService, PostService
from apps.blog.store import AutosaveStore
from apps.core.redis import CacheManager
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.blog.models import Post
    from apps.user.models import User
    from apps.workspace.models import Workspace


@pytest.fixture
def post_comment_service() -> PostCommentService:
    return PostCommentService(
        repository=PostCommentRepository(),
        post_repository=PostRepository(),
    )


@pytest.fixture
def post_service() -> PostService:
    return PostService(
        repository=PostRepository(),
        content_repository=PostContentRepository(),
        post_tag_repository=PostTagRepository(),
        category_repository=CategoryRepository(),
        tag_repository=TagRepository(),
        post_version_repository=PostVersionRepository(),
        cache=CacheManager(redis_client=None),
        autosave_store=AutosaveStore(redis_client=None),
    )


@pytest.fixture
def workspace_service() -> WorkspaceService:
    return WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )


@pytest.fixture
def user_service() -> UserService:
    return UserService(repository=UserRepository())


async def _make_user(session: AsyncSession, user_service: UserService, suffix: str) -> User:
    user = await user_service.create(
        session,
        data=CreateUserRequest(
            email=f"edt_{suffix}@example.com",
            username=f"edt_{suffix}",
            password="Sup3rSecret!",
        ),
    )
    await session.flush()
    return user


async def _make_workspace(
    session: AsyncSession,
    workspace_service: WorkspaceService,
    user: User,
    suffix: str,
    *,
    allow_anonymous: bool = False,
) -> Workspace:
    workspace = await workspace_service.create(
        session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(
            slug=f"ws-edt-{suffix}",
            name=f"WS Edt {suffix}",
            description=None,
        ),
    )
    workspace.allow_anonymous_comments = allow_anonymous
    await session.flush()
    return workspace


async def _make_published_post(
    session: AsyncSession,
    post_service: PostService,
    workspace: Workspace,
    author: User,
    suffix: str,
) -> Post:
    post = await post_service.create(
        session,
        workspace_id=workspace.id,
        author_id=author.id,
        data=CreatePostRequest(
            title=f"Edit-target {suffix}",
            slug=None,
            content_json={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "body"}]}],
            },
            hero_quote=HeroQuote(text="q", author=None, source_url=None),
        ),
    )
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.datetime.now(tz=datetime.UTC)
    await session.flush()
    return post


async def _backdate_comment_created_at(
    session: AsyncSession,
    comment_id: uuid.UUID,
    *,
    seconds: int,
) -> None:
    """Push created_at into the past so the edit window check can fire."""
    past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=seconds)
    await session.execute(
        update(PostComment).where(PostComment.id == comment_id).values(created_at=past),
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Edit tests
# ---------------------------------------------------------------------------


async def test_author_edits_own_comment_within_window(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-019: author can edit own comment; edited_at gets stamped."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    original = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="original body"),
    )
    assert original.edited_at is None

    edited = await post_comment_service.edit_own(
        real_session,
        comment_id=original.id,
        current_user_id=author.id,
        data=UpdateCommentRequest(body="updated body"),
    )

    assert edited.id == original.id
    assert edited.body == "updated body"
    assert edited.edited_at is not None
    assert edited.edited_at > original.created_at


async def test_edit_window_expired_rejected(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-019: edit past the window → CommentEditWindowExpiredError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    comment = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="will expire"),
    )
    await _backdate_comment_created_at(real_session, comment.id, seconds=3600)

    with pytest.raises(CommentEditWindowExpiredError):
        await post_comment_service.edit_own(
            real_session,
            comment_id=comment.id,
            current_user_id=author.id,
            data=UpdateCommentRequest(body="too late"),
        )


async def test_non_author_edit_forbidden(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-021: non-author edit → CommentAuthorForbiddenError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    other = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    comment = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="mine"),
    )

    with pytest.raises(CommentAuthorForbiddenError):
        await post_comment_service.edit_own(
            real_session,
            comment_id=comment.id,
            current_user_id=other.id,
            data=UpdateCommentRequest(body="not yours to edit"),
        )


async def test_anonymous_comment_edit_immutable(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-019: anonymous comments are immutable → AnonymousAuthorImmutableError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(
        real_session,
        workspace_service,
        author,
        suffix,
        allow_anonymous=True,
    )
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    anon = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="anon body", author_display_name="Anon"),
        source_ip=None,
    )
    with pytest.raises(AnonymousAuthorImmutableError):
        await post_comment_service.edit_own(
            real_session,
            comment_id=anon.id,
            current_user_id=author.id,
            data=UpdateCommentRequest(body="nope"),
        )


async def test_edit_body_is_sanitized(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Edited body runs through nh3 the same as the create path."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    comment = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="original"),
    )
    edited = await post_comment_service.edit_own(
        real_session,
        comment_id=comment.id,
        current_user_id=author.id,
        data=UpdateCommentRequest(body="<script>alert(1)</script> visible text"),
    )
    assert "<script" not in (edited.body or "")
    assert "visible text" in (edited.body or "")


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------


async def test_author_hard_deletes_when_no_replies(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-020: top-level with zero approved replies → hard delete; counter -1."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    comment = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="to delete"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 1

    await post_comment_service.delete_own(
        real_session,
        comment_id=comment.id,
        current_user_id=author.id,
    )

    db_row = (
        await real_session.execute(select(PostComment).where(PostComment.id == comment.id))
    ).scalar_one_or_none()
    assert db_row is None

    await real_session.refresh(post)
    assert post.comment_count == 0


async def test_author_tombstones_when_has_replies(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-020: top-level with approved replies → tombstone; counter -1 (parent only)."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="parent"),
    )
    await post_comment_service.create_reply_authenticated(
        real_session,
        workspace_id=workspace.id,
        parent_comment_id=parent.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="reply that survives"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 2

    await post_comment_service.delete_own(
        real_session,
        comment_id=parent.id,
        current_user_id=author.id,
    )

    db_row = (
        await real_session.execute(select(PostComment).where(PostComment.id == parent.id))
    ).scalar_one()
    assert db_row.is_tombstoned is True
    assert db_row.deleted_at is not None

    await real_session.refresh(post)
    assert post.comment_count == 1

    page = await post_comment_service.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 0


async def test_author_hard_deletes_own_reply(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Replies have no children, so delete is always hard-delete."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="parent"),
    )
    reply = await post_comment_service.create_reply_authenticated(
        real_session,
        workspace_id=workspace.id,
        parent_comment_id=parent.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="reply"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 2

    await post_comment_service.delete_own(
        real_session,
        comment_id=reply.id,
        current_user_id=author.id,
    )

    db_row = (
        await real_session.execute(select(PostComment).where(PostComment.id == reply.id))
    ).scalar_one_or_none()
    assert db_row is None
    await real_session.refresh(post)
    assert post.comment_count == 1


async def test_non_author_delete_forbidden(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-021: non-author delete → CommentAuthorForbiddenError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    other = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    comment = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="mine"),
    )
    with pytest.raises(CommentAuthorForbiddenError):
        await post_comment_service.delete_own(
            real_session,
            comment_id=comment.id,
            current_user_id=other.id,
        )


async def test_anonymous_comment_delete_immutable(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-019: anonymous comment delete → AnonymousAuthorImmutableError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(
        real_session,
        workspace_service,
        author,
        suffix,
        allow_anonymous=True,
    )
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    anon = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="anon", author_display_name="Anon"),
        source_ip=None,
    )
    with pytest.raises(AnonymousAuthorImmutableError):
        await post_comment_service.delete_own(
            real_session,
            comment_id=anon.id,
            current_user_id=author.id,
        )


async def test_delete_missing_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    user_service: UserService,
) -> None:
    """Unknown id → CommentNotFoundError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")

    with pytest.raises(CommentNotFoundError):
        await post_comment_service.delete_own(
            real_session,
            comment_id=uuid.uuid4(),
            current_user_id=author.id,
        )


async def test_delete_top_level_with_pending_reply_still_hard_deletes(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Only APPROVED+live replies force tombstone; pending replies don't count.

    Cascade on the FK takes care of the pending reply row.
    """
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(
        real_session,
        workspace_service,
        author,
        suffix,
        allow_anonymous=True,
    )
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="parent"),
    )
    anon_reply = await post_comment_service.create_reply_anonymous(
        real_session,
        workspace=workspace,
        parent_comment_id=parent.id,
        data=CreateAnonymousCommentRequest(body="pending reply", author_display_name="A"),
        source_ip=None,
    )
    db_anon = (
        await real_session.execute(select(PostComment).where(PostComment.id == anon_reply.id))
    ).scalar_one()
    assert db_anon.state == CommentState.PENDING.value

    await post_comment_service.delete_own(
        real_session,
        comment_id=parent.id,
        current_user_id=author.id,
    )

    # Parent gone (hard delete because no approved replies); pending child
    # cascade-deleted by the FK.
    parent_row = (
        await real_session.execute(select(PostComment).where(PostComment.id == parent.id))
    ).scalar_one_or_none()
    assert parent_row is None
    reply_row = (
        await real_session.execute(select(PostComment).where(PostComment.id == anon_reply.id))
    ).scalar_one_or_none()
    assert reply_row is None
