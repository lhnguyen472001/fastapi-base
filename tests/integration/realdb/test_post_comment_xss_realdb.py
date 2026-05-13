"""End-to-end XSS round-trip — SC-008.

Submit a script payload through the full service path and verify the
stored body + the public list response carry no executable markup.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

import pytest

from apps.blog.enums import PostStatus
from apps.blog.repositories import (
    CategoryRepository,
    PostCommentRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import CreateAuthenticatedCommentRequest, CreatePostRequest, HeroQuote
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


@pytest.fixture
def post_comment_service() -> PostCommentService:
    return PostCommentService(
        repository=PostCommentRepository(),
        post_repository=PostRepository(),
    )


async def test_xss_payload_sanitized_through_service(
    real_session: AsyncSession,
) -> None:
    """SC-008: a comment body with `<script>` is stored sanitized; the
    public list response carries no executable markup.
    """
    suffix = uuid.uuid4().hex[:8]
    user_service = UserService(repository=UserRepository())
    workspace_service = WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )
    post_service = PostService(
        repository=PostRepository(),
        content_repository=PostContentRepository(),
        post_tag_repository=PostTagRepository(),
        category_repository=CategoryRepository(),
        tag_repository=TagRepository(),
        post_version_repository=PostVersionRepository(),
        cache=CacheManager(redis_client=None),
        autosave_store=AutosaveStore(redis_client=None),
    )
    pcs = PostCommentService(
        repository=PostCommentRepository(),
        post_repository=PostRepository(),
    )

    author = await user_service.create(
        real_session,
        data=CreateUserRequest(
            email=f"xss_{suffix}@example.com",
            username=f"xss_{suffix}",
            password="Sup3rSecret!",
        ),
    )
    await real_session.flush()
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=author.id,
        data=CreateWorkspaceRequest(
            slug=f"ws-xss-{suffix}",
            name=f"WS XSS {suffix}",
            description=None,
        ),
    )
    await real_session.flush()
    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=author.id,
        data=CreatePostRequest(
            title=f"XSS test post {suffix}",
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
    await real_session.flush()

    payload = (
        '<script>alert(1)</script> body text <img src=x onerror=alert(2)> with <a href="javascript:alert(3)">stuff</a>'
    )
    resp = await pcs.create_authenticated(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        author_user_id=author.id,
        data=CreateAuthenticatedCommentRequest(body=payload),
    )

    assert "<script" not in (resp.body or "")
    assert "onerror" not in (resp.body or "")
    assert "javascript:" not in (resp.body or "")
    # Plain visible text survives.
    assert "body text" in (resp.body or "")

    page = await pcs.list_top_level(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 1
    listed = page.items[0].body or ""
    assert "<script" not in listed
    assert "onerror" not in listed
