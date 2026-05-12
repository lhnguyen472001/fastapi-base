"""Real-DB integration tests for the blog module.

Pre-requisites (per :mod:`tests.integration.realdb.conftest`):

* ``docker compose up -d postgres``
* ``uv run alembic upgrade head``

Each test runs inside a transaction that's always rolled back at teardown.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from apps.blog.enums import PostStatus
from apps.blog.exceptions import (
    BlogResourceWorkspaceMismatchError,
    PostInvalidStatusTransitionError,
    PostNotFoundError,
    PostSlugConflictError,
)
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import (
    CreateCategoryRequest,
    CreatePostRequest,
    CreateTagRequest,
    HeroQuote,
    ListPostsRequest,
    UpdatePostRequest,
)
from apps.blog.services import CategoryService, PostService, TagService
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category_service() -> CategoryService:
    return CategoryService(repository=CategoryRepository())


@pytest.fixture
def tag_service() -> TagService:
    return TagService(repository=TagRepository())


@pytest.fixture
def post_service() -> PostService:
    # Disabled cache + autosave by passing redis_client=None — the existing
    # realdb tests assert DB behavior, not Redis. Cache and autosave are
    # exercised by their own dedicated test modules.
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


async def _make_user(real_session: AsyncSession, user_service: UserService, suffix: str) -> User:
    user = await user_service.create(
        real_session,
        data=CreateUserRequest(
            email=f"blog_{suffix}@example.com",
            username=f"blog_{suffix}",
            password="Sup3rSecret!",
        ),
    )
    await real_session.flush()
    return user


async def _make_workspace(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user: User,
    suffix: str,
) -> Workspace:
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(slug=f"ws-{suffix}", name=f"WS {suffix}", description=None),
    )
    await real_session.flush()
    return workspace


def _doc(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ],
    }


# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------


async def test_category_create_and_list(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    category_service: CategoryService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    cat = await category_service.create(
        real_session,
        workspace_id=workspace.id,
        data=CreateCategoryRequest(name="Tech", slug=None, description=None),
    )
    await real_session.flush()

    assert cat.workspace_id == workspace.id
    assert cat.slug == "tech"


# ---------------------------------------------------------------------------
# Tag CRUD
# ---------------------------------------------------------------------------


async def test_tag_create_and_lookup(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    tag_service: TagService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    tag = await tag_service.create(
        real_session,
        workspace_id=workspace.id,
        data=CreateTagRequest(name="Python", slug=None),
    )
    await real_session.flush()
    assert tag.slug == "python"


# ---------------------------------------------------------------------------
# Post create + Tiptap pipeline
# ---------------------------------------------------------------------------


async def test_create_post_runs_tiptap_pipeline(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="Hello world",
            slug=None,
            content_json=_doc("This is the body."),
            hero_quote=HeroQuote(text="Quote of the day", author=None, source_url=None),
        ),
    )
    await real_session.flush()

    assert post.slug == "hello-world"
    assert post.status == PostStatus.DRAFT.value
    assert post.content_hash is not None and len(post.content_hash) == 64
    assert post.content is not None
    assert post.content.content_text == "This is the body."
    assert "<p>This is the body.</p>" in post.content.content_html
    assert post.word_count == 4
    assert post.reading_minutes == 1
    assert post.hero_quote == {"text": "Quote of the day", "author": None, "source_url": None}


async def test_create_post_rejects_duplicate_slug(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(title="Hello", slug="dup", content_json=_doc("x")),
    )
    await real_session.flush()

    with pytest.raises(PostSlugConflictError):
        await post_service.create(
            real_session,
            workspace_id=workspace.id,
            author_id=user.id,
            data=CreatePostRequest(title="Other", slug="dup", content_json=_doc("y")),
        )


async def test_create_post_rejects_too_many_tags() -> None:
    """Pydantic schema caps tag_ids at MAX_TAGS_PER_POST before the service runs."""
    too_many = [uuid.uuid4() for _ in range(11)]
    with pytest.raises(ValidationError):
        CreatePostRequest(
            title="Lots of tags",
            slug=None,
            tag_ids=too_many,
            content_json=_doc("x"),
        )


async def test_create_post_rejects_foreign_workspace_tag(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    tag_service: TagService,
    post_service: PostService,
) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    user_a = await _make_user(real_session, user_service, suffix_a)
    user_b = await _make_user(real_session, user_service, suffix_b)
    workspace_a = await _make_workspace(real_session, workspace_service, user_a, suffix_a)
    workspace_b = await _make_workspace(real_session, workspace_service, user_b, suffix_b)

    foreign_tag = await tag_service.create(
        real_session,
        workspace_id=workspace_b.id,
        data=CreateTagRequest(name="Foreign", slug=None),
    )
    await real_session.flush()

    with pytest.raises(BlogResourceWorkspaceMismatchError):
        await post_service.create(
            real_session,
            workspace_id=workspace_a.id,
            author_id=user_a.id,
            data=CreatePostRequest(
                title="x",
                slug=None,
                tag_ids=[foreign_tag.id],
                content_json=_doc("x"),
            ),
        )


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


async def test_publish_then_unpublish(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="Publishable post",
            slug=None,
            content_json=_doc("This body is intentionally long enough to clear the publish readiness gate."),
        ),
    )
    await real_session.flush()
    assert post.status == PostStatus.DRAFT.value

    published = await post_service.publish(real_session, workspace_id=workspace.id, post_id=post.id)
    await real_session.flush()
    assert published.status == PostStatus.PUBLISHED.value
    assert published.published_at is not None

    unpublished = await post_service.unpublish(real_session, workspace_id=workspace.id, post_id=post.id)
    await real_session.flush()
    assert unpublished.status == PostStatus.DRAFT.value
    assert unpublished.published_at is None


async def test_cannot_publish_already_published(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="Publishable post",
            slug=None,
            content_json=_doc("This body is intentionally long enough to clear the publish readiness gate."),
        ),
    )
    await post_service.publish(real_session, workspace_id=workspace.id, post_id=post.id)
    await real_session.flush()

    with pytest.raises(PostInvalidStatusTransitionError):
        await post_service.publish(real_session, workspace_id=workspace.id, post_id=post.id)


# ---------------------------------------------------------------------------
# Public read isolation
# ---------------------------------------------------------------------------


async def test_get_published_by_slug_excludes_drafts(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="hidden",
            slug="hidden",
            content_json=_doc("This body is intentionally long enough to clear the publish readiness gate."),
        ),
    )
    await real_session.flush()

    with pytest.raises(PostNotFoundError):
        await post_service.get_published_by_slug(real_session, workspace_id=workspace.id, slug=post.slug)

    await post_service.publish(real_session, workspace_id=workspace.id, post_id=post.id)
    await real_session.flush()

    found = await post_service.get_published_by_slug(real_session, workspace_id=workspace.id, slug=post.slug)
    assert found.id == post.id
    assert found.content is not None


# ---------------------------------------------------------------------------
# Cross-workspace isolation
# ---------------------------------------------------------------------------


async def test_post_lookup_returns_none_for_other_workspace(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    user_a = await _make_user(real_session, user_service, suffix_a)
    user_b = await _make_user(real_session, user_service, suffix_b)
    workspace_a = await _make_workspace(real_session, workspace_service, user_a, suffix_a)
    workspace_b = await _make_workspace(real_session, workspace_service, user_b, suffix_b)

    post_a = await post_service.create(
        real_session,
        workspace_id=workspace_a.id,
        author_id=user_a.id,
        data=CreatePostRequest(title="Secret", slug=None, content_json=_doc("a body")),
    )
    await real_session.flush()

    with pytest.raises(PostNotFoundError):
        await post_service.find_or_raise(real_session, workspace_id=workspace_b.id, post_id=post_a.id)


# ---------------------------------------------------------------------------
# Update + content_hash skip semantics
# ---------------------------------------------------------------------------


async def test_update_skips_rerender_when_content_unchanged(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    initial = _doc("original body")
    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(title="t", slug=None, content_json=initial),
    )
    await real_session.flush()
    original_hash = post.content_hash

    # Update title only — content_json unchanged.
    updated = await post_service.update(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        data=UpdatePostRequest(title="renamed"),
    )
    await real_session.flush()
    assert updated.title == "renamed"
    assert updated.content_hash == original_hash

    # Submit identical content_json — hash should match.
    updated2 = await post_service.update(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        data=UpdatePostRequest(content_json=initial),
    )
    await real_session.flush()
    assert updated2.content_hash == original_hash

    # Real change — hash should flip.
    updated3 = await post_service.update(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        data=UpdatePostRequest(content_json=_doc("changed body")),
    )
    await real_session.flush()
    assert updated3.content_hash != original_hash


# ---------------------------------------------------------------------------
# FTS search
# ---------------------------------------------------------------------------


async def test_full_text_search_finds_post(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="Postgres fundamentals",
            slug=None,
            content_json=_doc("Concurrency control in Postgres is built around MVCC."),
        ),
    )
    await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title="Redis caching",
            slug=None,
            content_json=_doc("Cache aside is a popular pattern."),
        ),
    )
    await real_session.flush()

    items, total = await post_service.list_posts(
        real_session,
        workspace_id=workspace.id,
        params=ListPostsRequest(limit=10, offset=0, search="postgres"),
    )
    assert total >= 1
    assert any("Postgres" in p.title for p in items)
