"""Real-DB integration tests for the post-like service (US1, FR-001..FR-009).

Pre-requisites:
* ``docker compose up -d postgres``
* ``uv run alembic upgrade head``

Each test runs inside a transaction that's rolled back at teardown.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest

from apps.blog.enums import PostStatus
from apps.blog.exceptions import PostEngagementClosedError, PostNotFoundError
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostLikeRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import CreatePostRequest, HeroQuote
from apps.blog.services import PostLikeService, PostService
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def post_like_service() -> PostLikeService:
    return PostLikeService(
        repository=PostLikeRepository(),
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
            email=f"like_{suffix}@example.com",
            username=f"like_{suffix}",
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
            slug=f"ws-like-{suffix}",
            name=f"WS Like {suffix}",
            description=None,
        ),
    )
    await session.flush()
    return workspace


def _doc(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ],
    }


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
            title=f"Likeable post {suffix}",
            slug=None,
            content_json=_doc("Body."),
            hero_quote=HeroQuote(text="Quote", author=None, source_url=None),
        ),
    )
    # Force-publish so engagement rules apply. ck_posts_published_implies_published_at
    # requires published_at to be set whenever status='published'.
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.datetime.now(tz=datetime.UTC)
    await session.flush()
    return post


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_like_increments_then_idempotent(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """SC-001 + FR-002: first like ticks the counter; subsequent likes are no-ops."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"author{suffix}")
    reader = await _make_user(real_session, user_service, f"reader{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    state1 = await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=reader.id,
    )
    assert state1.post_id == post.id
    assert state1.like_count == 1
    assert state1.liked_by_me is True

    # 10x repeat — idempotent per FR-002.
    for _ in range(10):
        state_n = await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=reader.id,
        )
        assert state_n.like_count == 1
        assert state_n.liked_by_me is True


async def test_unlike_reverses_like_state(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-003 / FR-004: unlike decrements and is also idempotent."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"author{suffix}")
    reader = await _make_user(real_session, user_service, f"reader{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=reader.id,
    )
    state = await post_like_service.unlike(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=reader.id,
    )
    assert state.like_count == 0
    assert state.liked_by_me is False

    # FR-004 idempotency for unlike.
    state2 = await post_like_service.unlike(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=reader.id,
    )
    assert state2.like_count == 0
    assert state2.liked_by_me is False


async def test_like_on_unknown_post_rejected(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Cross-workspace 404 (FR-027): a like on a post that doesn't exist in the
    caller's workspace surfaces a not-found, not a forbidden."""
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    with pytest.raises(PostNotFoundError):
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=uuid.uuid4(),
            user_id=user.id,
        )


async def test_like_on_archived_post_rejected(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-008 / FR-015: mutations on archived posts surface PostEngagementClosedError."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"author{suffix}")
    reader = await _make_user(real_session, user_service, f"reader{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    post.status = PostStatus.ARCHIVED.value
    await real_session.flush()

    with pytest.raises(PostEngagementClosedError):
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=reader.id,
        )


async def test_probe_liked_by_me(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """FR-006: the probe reports per-user like state without ambiguity."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"author{suffix}")
    reader = await _make_user(real_session, user_service, f"reader{suffix}")
    other = await _make_user(real_session, user_service, f"other{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=reader.id,
    )

    assert (
        await post_like_service.probe_liked_by_me(
            real_session,
            post_id=post.id,
            user_id=reader.id,
        )
        is True
    )
    assert (
        await post_like_service.probe_liked_by_me(
            real_session,
            post_id=post.id,
            user_id=other.id,
        )
        is False
    )


async def test_counter_trigger_drives_like_count(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """The PG trigger keeps ``posts.like_count`` in sync — sanity check that
    the like service does NOT mutate the counter manually."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"author{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    assert post.like_count == 0

    # Three distinct likers.
    readers = []
    for i in range(3):
        r = await _make_user(real_session, user_service, f"r{i}{suffix}")
        readers.append(r)
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=r.id,
        )

    await real_session.refresh(post)
    assert post.like_count == 3

    # One unlike — counter ticks down.
    await post_like_service.unlike(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=readers[0].id,
    )
    await real_session.refresh(post)
    assert post.like_count == 2
