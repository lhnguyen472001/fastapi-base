"""Real-DB integration tests for the comment-moderation retention sweeper (T073).

Covers FR-010e / research §11:
* pending rows older than ``POST_COMMENT_MODERATION_PENDING_TTL_SECONDS`` are
  deleted by a single sweeper pass
* approved rows of the same age are preserved (only ``state='pending'`` is
  in scope)
* the sweeper helper is callable on a bare session so a test can drive one
  tick deterministically without spinning the forever loop or the leader
  election
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update

from apps.blog.enums import CommentState, PostStatus
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
from apps.blog.sweeper import delete_stale_pending_comments
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
            email=f"sweep_{suffix}@example.com",
            username=f"sweep_{suffix}",
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
            slug=f"ws-sweep-{suffix}",
            name=f"WS Sweep {suffix}",
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
            title=f"Sweep-target {suffix}",
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


async def _backdate(session: AsyncSession, *, comment_id: uuid.UUID, age_days: int) -> None:
    """Push ``created_at`` into the past so the sweeper's predicate matches."""
    past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=age_days)
    await session.execute(
        update(PostComment).where(PostComment.id == comment_id).values(created_at=past),
    )
    await session.flush()


async def test_sweeper_purges_pending_rows_older_than_ttl_keeps_approved(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Three pending rows older than TTL get dropped; one approved survives.

    Drives :func:`delete_stale_pending_comments` directly on the rolled-back
    real_session — same shape as the post-version sweeper's ``trim_post`` helper
    test in ``test_blog_post_versions_realdb.py``.
    """
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    pending_ids: list[uuid.UUID] = []
    for n in range(3):
        comment = await post_comment_service.create_anonymous(
            real_session,
            workspace=workspace,
            post_id=post.id,
            data=CreateAnonymousCommentRequest(
                body=f"stale pending {n}",
                author_display_name=f"anon_{n}",
                author_email=None,
            ),
            source_ip=f"10.0.0.{n + 1}",
        )
        pending_ids.append(comment.id)
        await _backdate(real_session, comment_id=comment.id, age_days=31)

    approved = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=owner.id,
        data=CreateAuthenticatedCommentRequest(body="approved survives"),
    )
    await _backdate(real_session, comment_id=approved.id, age_days=31)

    pre_pending = (
        (
            await real_session.execute(
                select(PostComment).where(
                    PostComment.post_id == post.id,
                    PostComment.state == CommentState.PENDING.value,
                ),
            )
        )
        .scalars()
        .all()
    )
    assert {row.id for row in pre_pending} == set(pending_ids)

    deleted = await delete_stale_pending_comments(
        real_session,
        cutoff_seconds=24 * 3600,
        batch_size=200,
    )
    await real_session.flush()

    assert deleted == 3

    remaining = (await real_session.execute(select(PostComment).where(PostComment.post_id == post.id))).scalars().all()
    assert len(remaining) == 1
    surviving = remaining[0]
    assert surviving.id == approved.id
    assert surviving.state == CommentState.APPROVED.value


async def test_sweeper_leaves_fresh_pending_rows_alone(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """A pending row younger than the cutoff is not deleted."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    comment = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(
            body="fresh pending",
            author_display_name="anon",
            author_email=None,
        ),
        source_ip="10.0.0.1",
    )

    deleted = await delete_stale_pending_comments(
        real_session,
        cutoff_seconds=24 * 3600,
        batch_size=200,
    )

    assert deleted == 0
    survivor = (await real_session.execute(select(PostComment).where(PostComment.id == comment.id))).scalar_one()
    assert survivor.state == CommentState.PENDING.value
