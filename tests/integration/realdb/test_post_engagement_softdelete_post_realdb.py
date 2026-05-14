"""Real-DB integration tests for engagement against a soft-deleted post (T074).

Covers FR-008 + FR-027 — the *current* visibility model. The implementation
treats a soft-deleted post the same way it treats a cross-workspace post: the
row is invisible to every engagement caller, regardless of workspace
membership, and every engagement endpoint surfaces ``PostNotFoundError``
(404 mask). Mutations therefore raise the same not-found exception as reads.

This is the FR-027 mask — same response shape for "doesn't exist" and "you
can't see it" — and it is enforced uniformly across like, unlike, comment
create/list/reply/edit/self-delete and the moderator surface. The
implementation owes its uniformity to the services calling
``post_repository.find_by_id(include_deleted=False, ...)`` before any
mutation / list, so all paths fall through the same gate.

**Spec divergence flagged for follow-up (out of scope here):**

* FR-008 originally specifies "mutations on soft-deleted posts return 409"
  (engagement-closed). The current implementation returns 404 instead, which
  aligns soft-delete with the existence mask but conflicts with the strict
  reading of FR-008. The archived-post path *does* still raise 409 — that
  case is exercised by ``test_post_like_realdb.py`` and friends.
* FR-028a originally specifies "workspace members can read engagement on
  soft-deleted posts". The current services have no workspace-membership
  probe in their visibility resolver, so members and non-members alike see
  the 404 mask. Implementing this would mean threading a
  ``PostVisibilityResolver`` through the read services (research §12).

This test verifies the *implemented* behavior so a future change can flip
the assertions atomically with the resolver implementation.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import update

from apps.blog.enums import PostStatus
from apps.blog.exceptions import PostNotFoundError
from apps.blog.models import Post
from apps.blog.repositories import (
    CategoryRepository,
    PostCommentRepository,
    PostContentRepository,
    PostLikeRepository,
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
from apps.blog.services import (
    PostCommentService,
    PostLikeService,
    PostService,
)
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

    from apps.user.models import User
    from apps.workspace.models import Workspace


@pytest.fixture
def post_like_service() -> PostLikeService:
    return PostLikeService(
        repository=PostLikeRepository(),
        post_repository=PostRepository(),
    )


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
            email=f"sd_{suffix}@example.com",
            username=f"sd_{suffix}",
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
    allow_anonymous: bool = True,
) -> Workspace:
    workspace = await workspace_service.create(
        session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(
            slug=f"ws-sd-{suffix}",
            name=f"WS SD {suffix}",
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
            title=f"SD-target {suffix}",
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


async def _soft_delete(session: AsyncSession, *, post_id: uuid.UUID) -> None:
    await session.execute(
        update(Post).where(Post.id == post_id).values(deleted_at=datetime.datetime.now(tz=datetime.UTC)),
    )
    await session.flush()


async def test_like_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """A workspace member cannot like a soft-deleted post — surfaces 404 mask."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_like_service.like(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=owner.id,
        )


async def test_unlike_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Unlike on a soft-deleted post is the same 404 mask as like."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_like_service.unlike(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            user_id=owner.id,
        )


async def test_list_likers_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """list_likers on a soft-deleted post is the 404 mask (FR-028a deferral)."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_like_service.list_likers(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )


async def test_create_comment_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Authenticated comment-create on a soft-deleted post is the 404 mask."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            author_user_id=owner.id,
            data=CreateAuthenticatedCommentRequest(body="hello"),
        )


async def test_create_anonymous_comment_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Anonymous comment-create on a soft-deleted post is the 404 mask."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(
        real_session,
        workspace_service,
        owner,
        suffix,
        allow_anonymous=True,
    )
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_comment_service.create_anonymous(
            real_session,
            workspace=workspace,
            post_id=post.id,
            data=CreateAnonymousCommentRequest(
                body="anon hello",
                author_display_name="anon",
                author_email=None,
            ),
            source_ip="10.0.0.1",
        )


async def test_list_top_level_on_soft_deleted_post_raises_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """list_top_level on a soft-deleted post is the 404 mask (FR-028a deferral)."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)
    await _soft_delete(real_session, post_id=post.id)

    with pytest.raises(PostNotFoundError):
        await post_comment_service.list_top_level(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )
