"""Real-DB integration tests for 1-level reply threading (T045).

Covers US3 / FR-013..FR-016 / SC-005:
* depth-1 reply lands approved (auth path), counter ticks +1
* depth-2 reply is rejected (CommentNestingTooDeepError)
* reply to a tombstoned / soft-deleted parent surfaces as not-found
* reply to a pending parent surfaces as not-found (parent isn't visible)
* anonymous reply on a flag-on workspace lands pending; counter unchanged
* anonymous reply on a flag-off workspace surfaces as not-found
* list_replies returns oldest-first
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update

from apps.blog.enums import CommentAuthorKind, CommentState, PostStatus
from apps.blog.exceptions import (
    AnonymousCommentsDisabledError,
    CommentNestingTooDeepError,
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
            email=f"rep_{suffix}@example.com",
            username=f"rep_{suffix}",
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
            slug=f"ws-rep-{suffix}",
            name=f"WS Rep {suffix}",
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
            title=f"Reply-target {suffix}",
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_depth_1_auth_reply_lands_approved(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """SC-005: depth-1 reply lands approved + counter ticks +1."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    replier = await _make_user(real_session, user_service, f"r{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="parent body"),
    )

    await real_session.refresh(post)
    assert post.comment_count == 1

    reply = await post_comment_service.create_reply_authenticated(
        real_session,
        workspace_id=workspace.id,
        parent_comment_id=parent.id,
        author_user_id=replier.id,
        data=CreateAuthenticatedCommentRequest(body="reply body"),
    )

    assert reply.parent_comment_id == parent.id
    assert reply.author_kind == CommentAuthorKind.AUTHENTICATED.value
    assert reply.author.user_id == replier.id

    await real_session.refresh(post)
    assert post.comment_count == 2

    page = await post_comment_service.list_replies(
        real_session,
        workspace_id=workspace.id,
        parent_comment_id=parent.id,
        limit=10,
        offset=0,
    )
    assert page.total == 1
    assert page.items[0].id == reply.id
    assert page.items[0].body == "reply body"


async def test_depth_2_reply_rejected(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-014: depth-2 replies are rejected with CommentNestingTooDeepError."""
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

    with pytest.raises(CommentNestingTooDeepError):
        await post_comment_service.create_reply_authenticated(
            real_session,
            workspace_id=workspace.id,
            parent_comment_id=reply.id,
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body="too deep"),
        )


async def test_reply_to_soft_deleted_parent_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-016: parent soft-deleted (tombstoned) → reply rejected as not-found."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="will be deleted"),
    )

    await real_session.execute(
        update(PostComment)
        .where(PostComment.id == parent.id)
        .values(deleted_at=datetime.datetime.now(tz=datetime.UTC), is_tombstoned=True),
    )
    await real_session.flush()

    with pytest.raises(CommentNotFoundError):
        await post_comment_service.create_reply_authenticated(
            real_session,
            workspace_id=workspace.id,
            parent_comment_id=parent.id,
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body="too late"),
        )


async def test_reply_to_pending_parent_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-016: parent still pending (not visible) → reply rejected as not-found."""
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

    anon_pending = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(
            body="anon hi",
            author_display_name="Anon",
        ),
        source_ip=None,
    )

    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == anon_pending.id))).scalar_one()
    assert db_row.state == CommentState.PENDING.value

    with pytest.raises(CommentNotFoundError):
        await post_comment_service.create_reply_authenticated(
            real_session,
            workspace_id=workspace.id,
            parent_comment_id=anon_pending.id,
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body="reply to pending"),
        )


async def test_reply_to_missing_parent_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Unknown parent id → CommentNotFoundError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)

    with pytest.raises(CommentNotFoundError):
        await post_comment_service.create_reply_authenticated(
            real_session,
            workspace_id=workspace.id,
            parent_comment_id=uuid.uuid4(),
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body="nope"),
        )


async def test_anon_reply_flag_on_lands_pending(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-010c + FR-013: anon reply lands pending; counter unchanged."""
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

    await real_session.refresh(post)
    baseline = post.comment_count

    reply = await post_comment_service.create_reply_anonymous(
        real_session,
        workspace=workspace,
        parent_comment_id=parent.id,
        data=CreateAnonymousCommentRequest(
            body="anon reply",
            author_display_name="Curious",
        ),
        source_ip=None,
    )
    assert reply.parent_comment_id == parent.id
    assert reply.author_kind == CommentAuthorKind.ANONYMOUS.value

    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == reply.id))).scalar_one()
    assert db_row.state == CommentState.PENDING.value

    await real_session.refresh(post)
    assert post.comment_count == baseline


async def test_anon_reply_flag_off_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-010b: anon reply on flag-off workspace → not-found mask."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(
        real_session,
        workspace_service,
        author,
        suffix,
        allow_anonymous=False,
    )
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    parent = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="parent"),
    )

    with pytest.raises(AnonymousCommentsDisabledError):
        await post_comment_service.create_reply_anonymous(
            real_session,
            workspace=workspace,
            parent_comment_id=parent.id,
            data=CreateAnonymousCommentRequest(
                body="not allowed",
                author_display_name="A",
            ),
            source_ip=None,
        )


async def test_list_replies_oldest_first(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Replies are listed oldest-first so threading reads as a conversation."""
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

    bodies = ["first", "second", "third"]
    for body in bodies:
        await post_comment_service.create_reply_authenticated(
            real_session,
            workspace_id=workspace.id,
            parent_comment_id=parent.id,
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body=body),
        )

    page = await post_comment_service.list_replies(
        real_session,
        workspace_id=workspace.id,
        parent_comment_id=parent.id,
        limit=10,
        offset=0,
    )
    assert page.total == 3
    assert [item.body for item in page.items] == bodies
