"""Real-DB integration tests for the anonymous comment path (T032).

Covers FR-010 (anon path), FR-010a (display name + private email),
FR-010b (workspace-flag gate, 404-mask shape), FR-010c (pending state +
public-list exclusion), and counter behavior under pending → approved.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from apps.blog.enums import CommentAuthorKind, CommentState, PostStatus
from apps.blog.exceptions import AnonymousCommentsDisabledError
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
            email=f"acmt_{suffix}@example.com",
            username=f"acmt_{suffix}",
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
            slug=f"ws-acmt-{suffix}",
            name=f"WS ACmt {suffix}",
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
            title=f"Anon-commentable {suffix}",
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


async def test_anon_submission_on_flag_off_workspace_404s(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-010b: anonymous submit to a flag-OFF workspace returns 404-shape."""
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

    with pytest.raises(AnonymousCommentsDisabledError):
        await post_comment_service.create_anonymous(
            real_session,
            workspace=workspace,
            post_id=post.id,
            data=CreateAnonymousCommentRequest(
                body="hi",
                author_display_name="Reader",
            ),
            source_ip="203.0.113.1",
        )


async def test_anon_submission_on_flag_on_lands_pending(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-010c: anon submission lands `pending`, counter does not move."""
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

    assert post.comment_count == 0

    resp = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(
            body="thoughtful comment",
            author_display_name="Curious Reader",
            author_email="reader@example.com",
        ),
        source_ip="203.0.113.5",
    )

    assert resp.author_kind == CommentAuthorKind.ANONYMOUS.value
    assert resp.author.user_id is None
    assert resp.author.username is None
    assert resp.author.display_name == "Curious Reader"

    # Pending row does NOT show up in the public list.
    page = await post_comment_service.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 0

    # Counter is unchanged.
    await real_session.refresh(post)
    assert post.comment_count == 0

    # Row exists in DB in pending state with the private fields populated.
    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == resp.id))).scalar_one()
    assert db_row.state == CommentState.PENDING.value
    assert db_row.author_email == "reader@example.com"
    assert str(db_row.author_ip) == "203.0.113.5"


async def test_anon_email_is_optional(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-010a: anonymous email is optional; persists as NULL when omitted."""
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

    resp = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(
            body="email-less",
            author_display_name="Anonymous",
        ),
        source_ip=None,
    )

    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == resp.id))).scalar_one()
    assert db_row.author_email is None
    assert db_row.author_ip is None


async def test_pending_approve_transition_ticks_counter(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Approving a pending anon comment via direct UPDATE fires the UPDATE
    trigger and increments comment_count by 1 (no service path yet — Phase 7).
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

    resp = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(
            body="awaiting moderator",
            author_display_name="Reader",
        ),
        source_ip="203.0.113.1",
    )

    await real_session.refresh(post)
    assert post.comment_count == 0

    # Direct state flip — stand-in for the moderator endpoint in Phase 7.
    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == resp.id))).scalar_one()
    db_row.state = CommentState.APPROVED.value
    await real_session.flush()

    await real_session.refresh(post)
    assert post.comment_count == 1

    page = await post_comment_service.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 1
    assert page.items[0].author_kind == CommentAuthorKind.ANONYMOUS.value
    assert page.items[0].author.display_name == "Reader"
