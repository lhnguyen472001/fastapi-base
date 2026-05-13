"""Real-DB integration tests for moderator queue + actions (T058).

Covers US5 / FR-010d / FR-022 / data-model §3 counter math:
* list_pending returns only state='pending' rows in the workspace, oldest-first,
  scoped to one post when post_id is supplied
* approve flips pending → approved; counter +1; moderator attribution stamped
* reject flips pending → rejected; counter unchanged; attribution stamped
* approve-already-approved raises CommentNotPendingError (409)
* moderator_delete by RBAC holder (post-author-irrelevant): deleted_at set,
  counter -1, attribution stamped
* moderator_delete by post-author bypass (RBAC denies): same effect
* moderator_delete rejected when caller is neither moderator nor post-author
* moderator_delete on a pending row: drops it from the queue, counter unchanged
  (was never contributing)
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from apps.blog.enums import CommentState, PostStatus
from apps.blog.exceptions import CommentNotPendingError
from apps.blog.models import PostComment
from apps.blog.repositories import (
    CategoryRepository,
    PostCommentModerationRepository,
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
    ModerationActionRequest,
)
from apps.blog.services import PostCommentModerationService, PostCommentService, PostService
from apps.blog.store import AutosaveStore
from apps.core.exceptions.errors import ForbiddenError
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


@dataclass
class _FakeAccessService:
    """Stand-in for :class:`apps.rbac.services.AccessService`.

    Casbin + Redis-watcher wiring is out of scope for these tests; the
    moderator-OR-post-author branch is exercised by toggling ``allow``.
    """

    allow: bool

    async def check(self, *, user_id: uuid.UUID, resource: str, action: str) -> bool:
        _ = (user_id, resource, action)
        return self.allow


def _make_moderation_service(*, rbac_allows: bool) -> PostCommentModerationService:
    return PostCommentModerationService(
        repository=PostCommentModerationRepository(),
        post_repository=PostRepository(),
        access_service=_FakeAccessService(allow=rbac_allows),  # type: ignore[arg-type]
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
            email=f"mod_{suffix}@example.com",
            username=f"mod_{suffix}",
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
            slug=f"ws-mod-{suffix}",
            name=f"WS Mod {suffix}",
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
            title=f"Mod-target {suffix}",
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
# list_pending
# ---------------------------------------------------------------------------


async def test_list_pending_returns_only_pending_rows_in_workspace(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """list_pending excludes approved + rejected + soft-deleted rows."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    # 2 pending anonymous + 1 approved authenticated
    await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="pending one", author_display_name="anon1", author_email=None),
        source_ip="10.0.0.1",
    )
    await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="pending two", author_display_name="anon2", author_email=None),
        source_ip="10.0.0.2",
    )
    await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=owner.id,
        data=CreateAuthenticatedCommentRequest(body="approved-from-the-start"),
    )

    service = _make_moderation_service(rbac_allows=True)
    rows, total = await service.list_pending(
        real_session,
        workspace_id=workspace.id,
        post_id=None,
        limit=10,
        offset=0,
    )

    assert total == 2
    assert len(rows) == 2
    assert all(r.state == CommentState.PENDING.value for r in rows)
    # Oldest-first
    assert rows[0].body == "pending one"


async def test_list_pending_filters_by_post_id(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Optional post_id narrows the queue to a single post."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post_a = await _make_published_post(real_session, post_service, workspace, owner, suffix + "a")
    post_b = await _make_published_post(real_session, post_service, workspace, owner, suffix + "b")

    await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post_a.id,
        data=CreateAnonymousCommentRequest(body="on a", author_display_name="anonA", author_email=None),
        source_ip=None,
    )
    await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post_b.id,
        data=CreateAnonymousCommentRequest(body="on b", author_display_name="anonB", author_email=None),
        source_ip=None,
    )

    service = _make_moderation_service(rbac_allows=True)
    rows, total = await service.list_pending(
        real_session,
        workspace_id=workspace.id,
        post_id=post_a.id,
        limit=10,
        offset=0,
    )

    assert total == 1
    assert rows[0].post_id == post_a.id


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


async def test_approve_flips_state_and_ticks_counter(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """pending → approved: counter +1, attribution stamped."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    pending = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="please approve", author_display_name="anon", author_email=None),
        source_ip="10.0.0.5",
    )
    await real_session.refresh(post)
    assert post.comment_count == 0

    service = _make_moderation_service(rbac_allows=True)
    updated = await service.approve(
        real_session,
        comment_id=pending.id,
        moderator_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="ok"),
    )

    assert updated.state == CommentState.APPROVED.value
    assert updated.moderated_by_user_id == moderator.id
    assert updated.moderation_reason == "ok"
    assert updated.moderated_at is not None

    await real_session.refresh(post)
    assert post.comment_count == 1


async def test_approve_already_approved_rejected(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """approving a non-pending comment raises CommentNotPendingError (409)."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    already_approved = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=owner.id,
        data=CreateAuthenticatedCommentRequest(body="auth comment born approved"),
    )

    service = _make_moderation_service(rbac_allows=True)
    with pytest.raises(CommentNotPendingError):
        await service.approve(
            real_session,
            comment_id=already_approved.id,
            moderator_user_id=moderator.id,
            data=ModerationActionRequest(moderation_reason=None),
        )


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


async def test_reject_pending_leaves_counter_at_zero(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """pending → rejected: counter unchanged; attribution stamped."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    pending = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="spam", author_display_name="bot", author_email=None),
        source_ip="10.0.0.6",
    )

    service = _make_moderation_service(rbac_allows=True)
    updated = await service.reject(
        real_session,
        comment_id=pending.id,
        moderator_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="spam pattern"),
    )

    assert updated.state == CommentState.REJECTED.value
    assert updated.moderation_reason == "spam pattern"

    await real_session.refresh(post)
    assert post.comment_count == 0


async def test_reject_after_approve_decrements_counter(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """approved → rejected: trigger drops counter by 1 (data-model §3)."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    approved = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=owner.id,
        data=CreateAuthenticatedCommentRequest(body="will be retroactively rejected"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 1

    service = _make_moderation_service(rbac_allows=True)
    await service.reject(
        real_session,
        comment_id=approved.id,
        moderator_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="late call"),
    )

    await real_session.refresh(post)
    assert post.comment_count == 0


# ---------------------------------------------------------------------------
# moderator_delete
# ---------------------------------------------------------------------------


async def test_moderator_delete_by_rbac_holder(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """RBAC holder deletes any approved comment; counter -1."""
    suffix = uuid.uuid4().hex[:8]
    author = await _make_user(real_session, user_service, f"a{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, author, suffix)

    target = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body="naughty comment"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 1

    service = _make_moderation_service(rbac_allows=True)  # RBAC says yes
    await service.moderator_delete(
        real_session,
        comment_id=target.id,
        current_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="off-topic"),
    )

    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == target.id))).scalar_one()
    assert db_row.deleted_at is not None
    assert db_row.moderated_by_user_id == moderator.id
    assert db_row.moderation_reason == "off-topic"
    assert db_row.is_tombstoned is False

    await real_session.refresh(post)
    assert post.comment_count == 0


async def test_moderator_delete_by_post_author_bypass(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Post author can moderator-delete even if RBAC denies (FR-022)."""
    suffix = uuid.uuid4().hex[:8]
    post_author = await _make_user(real_session, user_service, f"a{suffix}")
    commenter = await _make_user(real_session, user_service, f"c{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, post_author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, post_author, suffix)

    target = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=commenter.id,
        data=CreateAuthenticatedCommentRequest(body="someone elses comment"),
    )
    await real_session.refresh(post)
    assert post.comment_count == 1

    service = _make_moderation_service(rbac_allows=False)  # RBAC denies
    await service.moderator_delete(
        real_session,
        comment_id=target.id,
        current_user_id=post_author.id,  # but caller IS the post author
        data=ModerationActionRequest(moderation_reason=None),
    )

    await real_session.refresh(post)
    assert post.comment_count == 0


async def test_moderator_delete_rejected_for_non_mod_non_author(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Caller without RBAC and not the post author gets 403."""
    suffix = uuid.uuid4().hex[:8]
    post_author = await _make_user(real_session, user_service, f"a{suffix}")
    stranger = await _make_user(real_session, user_service, f"s{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, post_author, suffix)
    post = await _make_published_post(real_session, post_service, workspace, post_author, suffix)

    target = await post_comment_service.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=post_author.id,
        data=CreateAuthenticatedCommentRequest(body="protected"),
    )

    service = _make_moderation_service(rbac_allows=False)
    with pytest.raises(ForbiddenError):
        await service.moderator_delete(
            real_session,
            comment_id=target.id,
            current_user_id=stranger.id,
            data=ModerationActionRequest(moderation_reason=None),
        )

    db_row = (await real_session.execute(select(PostComment).where(PostComment.id == target.id))).scalar_one()
    assert db_row.deleted_at is None


async def test_moderator_delete_pending_does_not_move_counter(
    real_session: AsyncSession,
    post_comment_service: PostCommentService,
    post_service: PostService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Deleting a pending row drops it from the queue but counter stays."""
    suffix = uuid.uuid4().hex[:8]
    owner = await _make_user(real_session, user_service, f"o{suffix}")
    moderator = await _make_user(real_session, user_service, f"m{suffix}")
    workspace = await _make_workspace(real_session, workspace_service, owner, suffix)
    post = await _make_published_post(real_session, post_service, workspace, owner, suffix)

    pending = await post_comment_service.create_anonymous(
        real_session,
        workspace=workspace,
        post_id=post.id,
        data=CreateAnonymousCommentRequest(body="trash", author_display_name="bot", author_email=None),
        source_ip=None,
    )
    await real_session.refresh(post)
    assert post.comment_count == 0

    service = _make_moderation_service(rbac_allows=True)
    await service.moderator_delete(
        real_session,
        comment_id=pending.id,
        current_user_id=moderator.id,
        data=ModerationActionRequest(moderation_reason="never approved"),
    )

    await real_session.refresh(post)
    assert post.comment_count == 0

    rows, total = await service.list_pending(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert total == 0
    assert rows == []
