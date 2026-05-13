"""Real-DB integration tests for the "Liked by" list endpoint (T066 / US6).

Covers FR-009 + US6 acceptance scenarios + cross-workspace 404 + the
soft-deleted-post read mask.

Pre-requisites:
* ``docker compose up -d postgres``
* ``uv run alembic upgrade head``

Each test runs inside a savepoint that is rolled back at teardown.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest

from apps.blog.enums import PostStatus
from apps.blog.exceptions import PostNotFoundError
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostLikeRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import CreatePostRequest, HeroQuote, LikerResponse
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
            email=f"likers_{suffix}@example.com",
            username=f"likers_{suffix}",
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
            slug=f"ws-likers-{suffix}",
            name=f"WS Likers {suffix}",
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
            title=f"Likers-target {suffix}",
            slug=None,
            content_json=_doc("Body."),
            hero_quote=HeroQuote(text="Quote", author=None, source_url=None),
        ),
    )
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.datetime.now(tz=datetime.UTC)
    await session.flush()
    return post


async def test_list_likers_orders_newest_first(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Five distinct likers → list returns 5 entries ordered by liked_at DESC."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    likers: list[User] = []
    for i in range(5):
        liker = await _make_user(real_session, user_service, f"l{i}{suffix}")
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=liker.id,
        )
        likers.append(liker)

    page = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=50,
        offset=0,
    )

    assert page.total == 5
    assert page.limit == 50
    assert page.offset == 0
    assert len(page.items) == 5
    expected_user_ids_desc = [u.id for u in reversed(likers)]
    assert [item.user_id for item in page.items] == expected_user_ids_desc
    for item, source_user in zip(page.items, reversed(likers), strict=True):
        assert isinstance(item, LikerResponse)
        assert item.user_id == source_user.id
        assert item.username == source_user.username
        assert item.liked_at.tzinfo is not None


async def test_list_likers_paginates(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """12 likers + page size 5 → three disjoint pages covering every liker."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    seen_user_ids: list[uuid.UUID] = []
    for i in range(12):
        liker = await _make_user(real_session, user_service, f"p{i:02d}{suffix}")
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=liker.id,
        )
        seen_user_ids.append(liker.id)

    page1 = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=5,
        offset=0,
    )
    page2 = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=5,
        offset=5,
    )
    page3 = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=5,
        offset=10,
    )

    for page in (page1, page2, page3):
        assert page.total == 12

    assert len(page1.items) == 5
    assert len(page2.items) == 5
    assert len(page3.items) == 2

    ids_page1 = {item.user_id for item in page1.items}
    ids_page2 = {item.user_id for item in page2.items}
    ids_page3 = {item.user_id for item in page3.items}
    assert ids_page1.isdisjoint(ids_page2)
    assert ids_page1.isdisjoint(ids_page3)
    assert ids_page2.isdisjoint(ids_page3)
    assert ids_page1 | ids_page2 | ids_page3 == set(seen_user_ids)


async def test_list_likers_empty_for_post_with_no_likes(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Brand-new post → list returns 0 items, total 0."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    page = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=20,
        offset=0,
    )

    assert page.total == 0
    assert page.items == []


async def test_list_likers_cross_workspace_masks_as_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Post in workspace A queried via workspace B → PostNotFoundError (FR-027)."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace_a = await _make_workspace(real_session, workspace_service, author, f"a{suffix}")
    workspace_b = await _make_workspace(real_session, workspace_service, author, f"b{suffix}")
    post = await _make_published_post(real_session, post_service, workspace_a, author, suffix)

    liker = await _make_user(real_session, user_service, f"l{suffix}")
    await post_like_service.like(
        real_session,
        workspace_id=workspace_a.id,
        post_id=post.id,
        user_id=liker.id,
    )

    with pytest.raises(PostNotFoundError):
        await post_like_service.list_likers(
            real_session,
            workspace_id=workspace_b.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )


async def test_list_likers_on_soft_deleted_post_masks_as_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Soft-deleted post → PostNotFoundError (matches comment-list read mask)."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)
    liker = await _make_user(real_session, user_service, f"l{suffix}")
    await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=liker.id,
    )

    post.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    await real_session.flush()

    with pytest.raises(PostNotFoundError):
        await post_like_service.list_likers(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )


async def test_list_likers_on_archived_post_still_returns_results(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Archiving a post does not hide its existing likers from this read endpoint."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    for i in range(3):
        liker = await _make_user(real_session, user_service, f"a{i}{suffix}")
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=liker.id,
        )

    post.status = PostStatus.ARCHIVED.value
    await real_session.flush()

    page = await post_like_service.list_likers(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=20,
        offset=0,
    )

    assert page.total == 3
    assert len(page.items) == 3
