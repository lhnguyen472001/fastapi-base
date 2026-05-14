"""Real-DB integration tests for cross-workspace engagement masking (T075).

Covers SC-006 / FR-027. The implementation masks "post exists but lives in
a workspace you can't see" as "post does not exist" — same response shape
across every engagement endpoint that takes ``workspace_id`` as a
parameter. The test creates two independent workspaces, places a post in
workspace A, and asserts that every workspace-scoped service call with
``workspace_id=workspace_B.id`` raises :class:`PostNotFoundError`.

**Scope note:** Endpoints whose service signature is keyed on
``comment_id`` instead of ``(workspace_id, post_id)`` — i.e. ``edit_own``,
``delete_own``, the moderator approve/reject/delete trio — are guarded at
the *route* layer by the ``workspace_slug`` resolver and the workspace-
membership gate that precedes the service call. Those route-level gates
return the same 404 shape but are exercised by the route-test suite, not
the service-test suite this file targets. Reconcile-counters is RBAC-
gated and is *intentionally* cross-workspace-callable for operators, so
it is excluded by design (research §15).
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
            email=f"xw_{suffix}@example.com",
            username=f"xw_{suffix}",
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
            slug=f"ws-xw-{suffix}",
            name=f"WS XW {suffix}",
            description=None,
        ),
    )
    workspace.allow_anonymous_comments = True
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
            title=f"XW-target {suffix}",
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


async def _two_workspaces_one_post(
    session: AsyncSession,
    *,
    user_service: UserService,
    workspace_service: WorkspaceService,
    post_service: PostService,
) -> tuple[User, Workspace, Workspace, Post]:
    suffix = uuid.uuid4().hex[:8]
    owner_a = await _make_user(session, user_service, f"a{suffix}")
    owner_b = await _make_user(session, user_service, f"b{suffix}")
    workspace_a = await _make_workspace(session, workspace_service, owner_a, f"a{suffix}")
    workspace_b = await _make_workspace(session, workspace_service, owner_b, f"b{suffix}")
    post = await _make_published_post(session, post_service, workspace_a, owner_a, f"a{suffix}")
    return owner_b, workspace_a, workspace_b, post


async def test_like_under_wrong_workspace_id_masks_as_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """like(workspace_id=B, post_id=in_A) raises PostNotFoundError (404 mask)."""
    other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_like_service.like(
            real_session,
            workspace_id=ws_b.id,
            post_id=post.id,
            user_id=other_owner.id,
        )


async def test_unlike_under_wrong_workspace_id_masks_as_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """unlike(workspace_id=B, post_id=in_A) raises PostNotFoundError."""
    other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_like_service.unlike(
            real_session,
            workspace_id=ws_b.id,
            post_id=post.id,
            user_id=other_owner.id,
        )


async def test_list_likers_under_wrong_workspace_id_masks_as_not_found(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """list_likers(workspace_id=B, post_id=in_A) raises PostNotFoundError."""
    _other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_like_service.list_likers(
            real_session,
            workspace_id=ws_b.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )


async def test_create_authenticated_comment_under_wrong_workspace_id_masks_as_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """create_authenticated(workspace_id=B, post_id=in_A) raises PostNotFoundError."""
    other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=ws_b.id,
            post_id=post.id,
            author_user_id=other_owner.id,
            data=CreateAuthenticatedCommentRequest(body="cross-ws probe"),
        )


async def test_create_anonymous_comment_under_wrong_workspace_masks_as_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """create_anonymous(workspace=B, post_id=in_A) raises PostNotFoundError.

    create_anonymous takes the resolved workspace as a parameter (instead
    of just workspace_id) because the service inspects the workspace's
    allow_anonymous_comments flag in the same call. Passing workspace B's
    row therefore exercises the same predicate as the like/comment paths.
    """
    _other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_comment_service.create_anonymous(
            real_session,
            workspace=ws_b,
            post_id=post.id,
            data=CreateAnonymousCommentRequest(
                body="anon cross-ws probe",
                author_display_name="anon",
                author_email=None,
            ),
            source_ip="10.0.0.1",
        )


async def test_list_top_level_under_wrong_workspace_id_masks_as_not_found(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """list_top_level(workspace_id=B, post_id=in_A) raises PostNotFoundError."""
    _other_owner, _ws_a, ws_b, post = await _two_workspaces_one_post(
        real_session,
        user_service=user_service,
        workspace_service=workspace_service,
        post_service=post_service,
    )

    with pytest.raises(PostNotFoundError):
        await post_comment_service.list_top_level(
            real_session,
            workspace_id=ws_b.id,
            post_id=post.id,
            limit=20,
            offset=0,
        )
