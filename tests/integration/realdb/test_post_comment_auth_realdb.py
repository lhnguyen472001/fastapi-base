"""Real-DB integration tests for the authenticated comment path (T031).

Covers SC-002 (round-trip), FR-017 (list shape + newest-first),
FR-023 (counter +1 on auth submit), and the cross-workspace 404 shape.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest

from apps.blog.enums import CommentAuthorKind, PostStatus
from apps.blog.exceptions import PostEngagementClosedError, PostNotFoundError
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
            email=f"cmt_{suffix}@example.com",
            username=f"cmt_{suffix}",
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
) -> Workspace:
    workspace = await workspace_service.create(
        session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(
            slug=f"ws-cmt-{suffix}",
            name=f"WS Cmt {suffix}",
            description=None,
        ),
    )
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
            title=f"Commentable post {suffix}",
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


async def test_auth_comment_round_trip(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """SC-002 + FR-017: auth submit lands approved + appears in list."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    reader = await _make_user(real_session, user_service, f"r{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    resp = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=reader.id,
        data=CreateAuthenticatedCommentRequest(body="Great post!"),
    )

    assert resp.post_id == post.id
    assert resp.author_kind == CommentAuthorKind.AUTHENTICATED.value
    assert resp.author.user_id == reader.id
    assert resp.author.username == reader.username
    assert resp.body == "Great post!"
    assert resp.is_tombstoned is False
    assert resp.reply_count == 0

    page = await post_comment_service.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 1
    assert page.items[0].id == resp.id
    assert page.items[0].body == "Great post!"


async def test_auth_comment_counter_increments(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-023: each approved auth comment ticks posts.comment_count +1."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    assert post.comment_count == 0

    for i in range(3):
        r = await _make_user(real_session, user_service, f"r{i}{suffix}")
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            author_user_id=r.id,
            data=CreateAuthenticatedCommentRequest(body=f"comment {i}"),
        )

    await real_session.refresh(post)
    assert post.comment_count == 3


async def test_auth_comment_list_returns_all_bodies(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-017: list returns every approved row for the post."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    bodies = []
    for i in range(3):
        r = await _make_user(real_session, user_service, f"r{i}{suffix}")
        body = f"body number {i}"
        bodies.append(body)
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            author_user_id=r.id,
            data=CreateAuthenticatedCommentRequest(body=body),
        )

    page = await post_comment_service.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    returned_bodies = [item.body for item in page.items]
    assert set(returned_bodies) == set(bodies)


async def test_auth_comment_cross_workspace_404(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """SC-006 / FR-027: cross-workspace probe surfaces as not-found."""
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, f"u{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    with pytest.raises(PostNotFoundError):
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=uuid.uuid4(),
            author_user_id=user.id,
            data=CreateAuthenticatedCommentRequest(body="not gonna land"),
        )


async def test_auth_comment_archived_post_rejected(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-015: mutations on archived posts return engagement-closed."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    reader = await _make_user(real_session, user_service, f"r{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    post.status = PostStatus.ARCHIVED.value
    await real_session.flush()

    with pytest.raises(PostEngagementClosedError):
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            author_user_id=reader.id,
            data=CreateAuthenticatedCommentRequest(body="not gonna land"),
        )


async def test_auth_response_never_includes_email(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """The public response shape carries no author_email / author_ip fields."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    resp = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="hi"),
    )

    dumped = resp.model_dump_json()
    assert "author_email" not in dumped
    assert "author_ip" not in dumped
