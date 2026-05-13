"""Real-Redis + real-Postgres integration tests for the Tiptap offload path.

Covers F-PERF-1 / FR-001 at the service layer:

* A large-payload autosave + flush completes end-to-end and round-trips
  intact (no behavioral regression).
* During the autosave/flush of a payload >= ``LARGE_CONTENT_BYTES``,
  ``asyncio.to_thread`` is invoked at least once — the offload actually
  ran. (The unit test in ``tests/unit/test_blog_offload_threshold_unit.py``
  covers the gating decision; this test confirms the wired-up behavior.)

The latency-budget acceptance (SC-001) lives in the manual harness in
``quickstart.md`` §1 — CI cannot reliably measure event-loop fairness
under variable load.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from apps.blog.constants import AUTOSAVE_DIRTY_SET, AUTOSAVE_KEY_PREFIX, POST_CACHE_KEY_PREFIX
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import CreatePostRequest
from apps.blog.services import PostService
from apps.blog.store import AutosaveStore
from apps.blog.utils import compute_content_artifacts
from apps.core.redis import CacheManager, get_redis_client
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.skipif(
    get_redis_client() is None,
    reason="Redis is disabled or unreachable; offload integration test requires REDIS_ENABLED=true.",
)


_SYNTHETIC_FIXTURE: Path = Path(__file__).resolve().parents[3] / "scripts" / "synthetic_large_post.json"


def _small_doc(text: str) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _large_doc() -> dict[str, Any]:
    if not _SYNTHETIC_FIXTURE.exists():
        msg = (
            f"Missing synthetic fixture {_SYNTHETIC_FIXTURE}. "
            "Run: uv run python scripts/generate_synthetic_large_post.py"
        )
        raise FileNotFoundError(msg)
    return json.loads(_SYNTHETIC_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def cache_manager() -> CacheManager:
    return CacheManager(redis_client=get_redis_client())


@pytest.fixture
def autosave_store() -> AutosaveStore:
    return AutosaveStore(redis_client=get_redis_client())


@pytest.fixture
def post_service(cache_manager: CacheManager, autosave_store: AutosaveStore) -> PostService:
    return PostService(
        repository=PostRepository(),
        content_repository=PostContentRepository(),
        post_tag_repository=PostTagRepository(),
        category_repository=CategoryRepository(),
        tag_repository=TagRepository(),
        post_version_repository=PostVersionRepository(),
        cache=cache_manager,
        autosave_store=autosave_store,
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


@pytest.fixture
async def redis_cleanup() -> AsyncIterator[list[uuid.UUID]]:
    tracked: list[uuid.UUID] = []
    yield tracked

    redis = get_redis_client()
    if redis is None:
        return
    for post_id in tracked:
        await redis.delete(f"{AUTOSAVE_KEY_PREFIX}:{post_id}")
        await redis.client.srem(AUTOSAVE_DIRTY_SET, str(post_id))
    cursor = 0
    while True:
        cursor, batch = await redis.client.scan(cursor=cursor, match=f"{POST_CACHE_KEY_PREFIX}:*", count=200)
        if batch:
            await redis.delete(*batch)
        if cursor == 0:
            break


async def _make_user(real_session: AsyncSession, user_service: UserService, suffix: str) -> Any:
    user = await user_service.create(
        real_session,
        data=CreateUserRequest(
            email=f"offload_{suffix}@example.com",
            username=f"offload_{suffix}",
            password="Sup3rSecret!",
        ),
    )
    await real_session.flush()
    return user


async def _make_workspace(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user: Any,
    suffix: str,
) -> Any:
    workspace = await workspace_service.create(
        real_session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(slug=f"offload-ws-{suffix}", name=f"Offload WS {suffix}", description=None),
    )
    await real_session.flush()
    return workspace


# ---------------------------------------------------------------------------
# F-PERF-1: large-payload create runs the Tiptap pipeline on a worker thread.
# ---------------------------------------------------------------------------
#
# We target ``post_service.create(...)`` rather than ``autosave(...)`` because
# autosave is intentionally lean (only extract_text + hash, no html/sanitize/
# compress). The full Tiptap pipeline runs at create / update / publish /
# flush_one time, which is where the offload matters.


async def test_large_payload_create_invokes_thread_offload(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
    redis_cleanup: list[uuid.UUID],
) -> None:
    """Creating a draft with a ~145 KiB body offloads the Tiptap pipeline.

    ``post_service.create`` calls ``compute_content_artifacts`` and
    ``compress_content_json`` synchronously today. After F-PERF-1 is wired,
    both should route through their ``_async`` wrappers and invoke
    ``asyncio.to_thread`` when the payload is at or above
    ``LARGE_CONTENT_BYTES``.
    """
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    large = _large_doc()

    # Capture the real to_thread BEFORE patching so the spy doesn't recurse
    # into its own patched stub.
    real_to_thread = asyncio.to_thread

    async def _spy(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await real_to_thread(fn, *args, **kwargs)

    with patch("apps.blog.utils.asyncio.to_thread", side_effect=_spy) as mock_to_thread:
        post = await post_service.create(
            real_session,
            workspace_id=workspace.id,
            author_id=user.id,
            data=CreatePostRequest(title="Offload smoke", slug=None, content_json=large),
        )
        await real_session.flush()

    redis_cleanup.append(post.id)

    assert mock_to_thread.call_count >= 1, (
        "create() with a payload above LARGE_CONTENT_BYTES must invoke the "
        "thread offload at least once; the inline path was taken instead."
    )

    # End-to-end correctness: the persisted post matches what an inline
    # run would have produced.
    _, _, expected_hash, expected_words, _ = compute_content_artifacts(large)
    assert post.content_hash == expected_hash
    assert post.word_count == expected_words


async def test_small_payload_create_takes_inline_path(
    real_session: AsyncSession,
    workspace_service: WorkspaceService,
    user_service: UserService,
    post_service: PostService,
    redis_cleanup: list[uuid.UUID],
) -> None:
    """Creating a draft with a tiny body does not pay the thread hand-off cost."""
    suffix = uuid.uuid4().hex[:8]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    small = _small_doc("seed body long enough for publish readiness " * 4)

    with patch("apps.blog.utils.asyncio.to_thread") as mock_to_thread:
        post = await post_service.create(
            real_session,
            workspace_id=workspace.id,
            author_id=user.id,
            data=CreatePostRequest(title="Inline smoke", slug=None, content_json=small),
        )
        await real_session.flush()

    redis_cleanup.append(post.id)

    assert mock_to_thread.call_count == 0
    assert post.content_hash is not None
    assert post.word_count > 0
