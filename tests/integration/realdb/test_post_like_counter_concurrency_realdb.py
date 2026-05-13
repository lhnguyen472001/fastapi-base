"""Concurrent like writes — SC-003 (exactness) + SC-004 (duplicate idempotency).

Each test creates its own dataset in a setup transaction, fires the
concurrent workload via separate sessions, then cleans up. Cannot use
the savepoint-rollback ``real_session`` fixture because true concurrent
writes need distinct connections that each commit independently.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import TYPE_CHECKING

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from apps.blog.enums import PostStatus
from apps.blog.models import (
    Post as PostModel,
    PostContent,
    PostLike,
    PostTag,
    PostVersion,
)
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
from apps.user.models import User
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.models import Workspace as WorkspaceModel, WorkspaceMember
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _build_post_service() -> PostService:
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


@pytest_asyncio.fixture
async def isolated_dataset(real_engine: AsyncEngine) -> AsyncGenerator[dict]:
    """Create + clean up a published post + workspace + author in their own
    committed transaction.
    """
    factory = async_sessionmaker(bind=real_engine, expire_on_commit=False, class_=AsyncSession)
    suffix = uuid.uuid4().hex[:8]

    user_service = UserService(repository=UserRepository())
    workspace_service = WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )
    post_service = _build_post_service()

    async with factory() as setup_session:
        author = await user_service.create(
            setup_session,
            data=CreateUserRequest(
                email=f"conc_author_{suffix}@example.com",
                username=f"conc_author_{suffix}",
                password="Sup3rSecret!",
            ),
        )
        await setup_session.flush()

        workspace = await workspace_service.create(
            setup_session,
            owner_user_id=author.id,
            data=CreateWorkspaceRequest(
                slug=f"ws-conc-{suffix}",
                name=f"WS Conc {suffix}",
                description=None,
            ),
        )
        await setup_session.flush()

        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "body"}]},
            ],
        }
        post = await post_service.create(
            setup_session,
            workspace_id=workspace.id,
            author_id=author.id,
            data=CreatePostRequest(
                title=f"Concurrent {suffix}",
                slug=None,
                content_json=doc,
                hero_quote=HeroQuote(text="q", author=None, source_url=None),
            ),
        )
        post.status = PostStatus.PUBLISHED.value
        post.published_at = datetime.datetime.now(tz=datetime.UTC)
        await setup_session.flush()
        await setup_session.commit()

        post_id = post.id
        workspace_id = workspace.id
        author_id = author.id

    try:
        yield {
            "factory": factory,
            "workspace_id": workspace_id,
            "post_id": post_id,
            "author_id": author_id,
            "suffix": suffix,
        }
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(delete(PostLike).where(PostLike.post_id == post_id))
            await cleanup_session.execute(delete(PostTag).where(PostTag.post_id == post_id))
            await cleanup_session.execute(delete(PostVersion).where(PostVersion.post_id == post_id))
            await cleanup_session.execute(delete(PostContent).where(PostContent.post_id == post_id))
            await cleanup_session.execute(delete(PostModel).where(PostModel.id == post_id))
            await cleanup_session.execute(
                delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id),
            )
            await cleanup_session.execute(
                delete(WorkspaceModel).where(WorkspaceModel.id == workspace_id),
            )
            user_ids = (
                (
                    await cleanup_session.execute(
                        select(User.id).where(User.username.like(f"conc_%_{suffix}%")),
                    )
                )
                .scalars()
                .all()
            )
            if user_ids:
                await cleanup_session.execute(delete(User).where(User.id.in_(user_ids)))
            await cleanup_session.execute(delete(User).where(User.id == author_id))
            await cleanup_session.commit()


async def _one_like(
    factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: uuid.UUID,
    post_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Apply a single like in its own committing session."""
    svc = PostLikeService(
        repository=PostLikeRepository(),
        post_repository=PostRepository(),
    )
    async with factory() as session:
        await svc.like(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            user_id=user_id,
        )
        await session.commit()


async def test_concurrent_distinct_likers_exact_count(isolated_dataset: dict) -> None:
    """SC-003: N distinct concurrent likers → counter ends at exactly N.

    Spec target is 100; we run 50 to keep the test under a few seconds
    on the dev Postgres while still exercising true write contention.
    """
    factory = isolated_dataset["factory"]
    workspace_id = isolated_dataset["workspace_id"]
    post_id = isolated_dataset["post_id"]
    suffix = isolated_dataset["suffix"]

    user_ids: list[uuid.UUID] = []
    async with factory() as seed_session:
        user_service = UserService(repository=UserRepository())
        for i in range(50):
            u = await user_service.create(
                seed_session,
                data=CreateUserRequest(
                    email=f"conc_lk_{i}_{suffix}@example.com",
                    username=f"conc_lk_{i}_{suffix}",
                    password="Sup3rSecret!",
                ),
            )
            await seed_session.flush()
            user_ids.append(u.id)
        await seed_session.commit()

    await asyncio.gather(
        *[_one_like(factory, workspace_id=workspace_id, post_id=post_id, user_id=uid) for uid in user_ids],
    )

    async with factory() as verify_session:
        like_count = (
            await verify_session.execute(select(PostModel.like_count).where(PostModel.id == post_id))
        ).scalar_one()

    assert like_count == 50, f"expected 50, got {like_count}"


async def test_concurrent_duplicate_likes_from_one_user_idempotent(isolated_dataset: dict) -> None:
    """SC-004: 20 duplicate likes from one user → counter moves by exactly 1."""
    factory = isolated_dataset["factory"]
    workspace_id = isolated_dataset["workspace_id"]
    post_id = isolated_dataset["post_id"]
    suffix = isolated_dataset["suffix"]

    async with factory() as seed_session:
        user_service = UserService(repository=UserRepository())
        user = await user_service.create(
            seed_session,
            data=CreateUserRequest(
                email=f"conc_dup_{suffix}@example.com",
                username=f"conc_dup_{suffix}",
                password="Sup3rSecret!",
            ),
        )
        await seed_session.flush()
        user_id = user.id
        await seed_session.commit()

    await asyncio.gather(
        *[_one_like(factory, workspace_id=workspace_id, post_id=post_id, user_id=user_id) for _ in range(20)],
    )

    async with factory() as verify_session:
        like_count = (
            await verify_session.execute(select(PostModel.like_count).where(PostModel.id == post_id))
        ).scalar_one()

    assert like_count == 1, f"expected exactly 1 like after 20 dup attempts, got {like_count}"
