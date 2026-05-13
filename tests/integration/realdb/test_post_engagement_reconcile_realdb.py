"""Real-DB integration tests for the reconcile-counters endpoint (T059).

Covers FR-026 / SC-010 / research §15:
* deliberately corrupt ``posts.like_count`` + ``posts.comment_count`` via raw SQL
  so cached counters drift away from scalar truth
* call ``reconcile_counters`` and assert ``before`` reflects the drift,
  ``after`` matches the authoritative scalar counts, and ``drift_corrected``
  is True
* a second call with no drift returns ``drift_corrected`` = False
* approved-but-deleted rows are excluded from the comment count
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import update

from apps.blog.enums import PostStatus
from apps.blog.models import Post
from apps.blog.repositories import (
    CategoryRepository,
    PostCommentModerationRepository,
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
    ModerationActionRequest,
)
from apps.blog.services import (
    PostCommentModerationService,
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


@dataclass
class _FakeAccessService:
    allow: bool = True

    async def check(self, *, user_id: uuid.UUID, resource: str, action: str) -> bool:
        _ = (user_id, resource, action)
        return self.allow


def _make_moderation_service() -> PostCommentModerationService:
    return PostCommentModerationService(
        repository=PostCommentModerationRepository(),
        post_repository=PostRepository(),
        access_service=_FakeAccessService(),  # type: ignore[arg-type]
    )


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
            email=f"rec_{suffix}@example.com",
            username=f"rec_{suffix}",
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
            slug=f"ws-rec-{suffix}",
            name=f"WS Rec {suffix}",
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
):
    post = await post_service.create(
        session,
        workspace_id=workspace.id,
        author_id=author.id,
        data=CreatePostRequest(
            title=f"Reconcile-target {suffix}",
            slug=None,
            content_json={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}],
            },
            hero_quote=HeroQuote(text="q", author=None, source_url=None),
        ),
    )
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.datetime.now(tz=datetime.UTC)
    await session.flush()
    return post


async def test_reconcile_corrects_drift(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Drifted counters → after call: scalar truth + drift_corrected=True."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    liker1 = await _make_user(real_session, user_service, f"l1{suffix}")
    liker2 = await _make_user(real_session, user_service, f"l2{suffix}")
    await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=liker1.id,
    )
    await post_like_service.like(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        user_id=liker2.id,
    )

    for _ in range(3):
        await post_comment_service.create_authenticated(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            author_user_id=author.id,
            data=CreateAuthenticatedCommentRequest(body=f"c-{uuid.uuid4().hex[:6]}"),
        )

    await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="pending", author_display_name="bot", author_email=None),
        source_ip=None,
    )

    await real_session.refresh(post)
    assert post.like_count == 2
    assert post.comment_count == 3

    await real_session.execute(
        update(Post).where(Post.id == post.id).values(like_count=999, comment_count=999),
    )
    await real_session.flush()

    service = _make_moderation_service()
    result = await service.reconcile_counters(real_session, post_id=post.id)

    assert result.post_id == post.id
    assert result.before.like_count == 999
    assert result.before.comment_count == 999
    assert result.after.like_count == 2
    assert result.after.comment_count == 3
    assert result.drift_corrected is True

    await real_session.refresh(post)
    assert post.like_count == 2
    assert post.comment_count == 3


async def test_reconcile_no_drift_reports_false(
    real_session: AsyncSession,
    post_like_service: PostLikeService,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """A call with no drift → drift_corrected=False."""
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
    await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="single"),
    )

    service = _make_moderation_service()
    result = await service.reconcile_counters(real_session, post_id=post.id)

    assert result.before.like_count == 1
    assert result.before.comment_count == 1
    assert result.after.like_count == 1
    assert result.after.comment_count == 1
    assert result.drift_corrected is False


async def test_reconcile_excludes_moderator_deleted_rows(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """A moderator-deleted (deleted_at set) approved row is excluded from the count.

    Drift-correction must agree with the trigger's contribution predicate.
    """
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    surviving = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="keep"),
    )
    doomed = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="kill"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 2

    service = _make_moderation_service()
    await service.moderator_delete(
        real_session,
        comment_id=doomed.id,
        current_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="dup"),
    )

    await real_session.execute(
        update(Post).where(Post.id == post.id).values(comment_count=42),
    )
    await real_session.flush()

    result = await service.reconcile_counters(real_session, post_id=post.id)

    assert result.after.comment_count == 1
    assert result.drift_corrected is True
    _ = surviving
