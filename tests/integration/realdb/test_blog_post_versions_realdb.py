"""Real-Postgres integration tests for the post-version-history endpoints.

Covers US1 (list), US2 (single-version detail), US3 (restore), and US4
(compare) end-to-end against a live Postgres reached via the standard
``real_session`` fixture in ``tests/integration/realdb/conftest.py``.

Each test rolls back via ``real_session``; Redis is not used by these
flows (versions are written through the relational path), so no Redis
cleanup is needed.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

import orjson
import pytest
from sqlalchemy import delete

from apps.blog.exceptions import (
    PostNotFoundError,
    PostVersionMismatchError,
    PostVersionNotFoundError,
)
from apps.blog.models import PostVersion
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import CreatePostRequest
from apps.blog.services import PostService, PostVersionService
from apps.blog.store import AutosaveStore
from apps.blog.sweeper import trim_post
from apps.blog.utils import compress_content_json
from apps.core.redis import CacheManager, get_redis_client
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_LONG_BODY: str = (
    "Initial body that comfortably exceeds the fifty character publish "
    "readiness threshold so we can exercise the publish flow."
)


def _doc(text: str) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def post_version_service() -> PostVersionService:
    return PostVersionService(
        repository=PostVersionRepository(),
        post_repository=PostRepository(),
        post_content_repository=PostContentRepository(),
        user_repository=UserRepository(),
    )


@pytest.fixture
def post_version_repo() -> PostVersionRepository:
    return PostVersionRepository()


@pytest.fixture
def workspace_service() -> WorkspaceService:
    return WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )


@pytest.fixture
def user_service() -> UserService:
    return UserService(repository=UserRepository())


# ---------------------------------------------------------------------------
# Builders — module-private helpers, deliberately not shared via conftest
# (the autosave test file builds its own; consistency is per-feature).
# ---------------------------------------------------------------------------


async def _make_user(real_session: AsyncSession, user_service: UserService, suffix: str) -> Any:
    user = await user_service.create(
        real_session,
        data=CreateUserRequest(
            email=f"pv_{suffix}@example.com",
            username=f"pv_{suffix}",
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
        data=CreateWorkspaceRequest(slug=f"pv-ws-{suffix}", name=f"PV WS {suffix}", description=None),
    )
    await real_session.flush()
    return workspace


async def _make_draft(
    real_session: AsyncSession,
    post_service: PostService,
    workspace: Any,
    user: Any,
    *,
    title: str = "Draft",
    body: str = _LONG_BODY,
) -> Any:
    post = await post_service.create(
        real_session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(title=title, slug=None, content_json=_doc(body)),
    )
    await real_session.flush()
    return post


async def _seed_version(
    real_session: AsyncSession,
    post_version_repo: PostVersionRepository,
    post: Any,
    author_id: uuid.UUID,
    *,
    title: str,
    body: str,
    is_published_snapshot: bool = False,
    is_restored: bool = False,
    status_at_save: str = "draft",
    change_note: str | None = None,
) -> Any:
    """Directly append a version row without going through autosave/flush.

    We seed history this way because :meth:`PostService.update` does not
    yet wire the version-write path (that's T029 in Phase 5). The Phase 2
    integration tests already prove that ``flush_one`` writes versions;
    these tests are about the read/list service on top.
    """
    content_json = _doc(body)
    serialized = orjson.dumps(content_json, option=orjson.OPT_SORT_KEYS)
    content_hash = hashlib.sha256(serialized).hexdigest()
    return await post_version_repo.add_with_retry(
        real_session,
        data={
            "post_id": post.id,
            "workspace_id": post.workspace_id,
            "title": title,
            "content_json_compressed": compress_content_json(content_json),
            "content_text": body,
            "content_hash": content_hash,
            "created_by": author_id,
            "change_note": change_note,
            "is_published_snapshot": is_published_snapshot,
            "is_restored": is_restored,
            "status_at_save": status_at_save,
        },
    )


# ---------------------------------------------------------------------------
# Phase 3 — US1 list versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_post_versions_returns_metadata_newest_first(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T018: 5 versions → 5 rows newest-first, no content body, paginates."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user, title="v1 title", body=_LONG_BODY)

    # _make_draft creates v1 via PostService.create. Seed 4 more so the
    # list has 5 distinct versions to page through.
    for i in range(2, 6):
        body_for_i = f"{_LONG_BODY} edit #{i} adds enough text to clear the unchanged-skip check."
        await _seed_version(
            real_session,
            post_version_repo,
            post,
            user.id,
            title=f"v{i} title",
            body=body_for_i,
        )

    page_all = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page_all.total == 5
    assert len(page_all.items) == 5
    assert [v.version for v in page_all.items] == [5, 4, 3, 2, 1]
    first = page_all.items[0]
    # Detail fields stay off the list response by design.
    payload_keys = first.model_dump().keys()
    assert "content_json" not in payload_keys
    assert "content_text" not in payload_keys
    # The hydrated author block should be populated.
    assert first.created_by.id == user.id
    assert first.created_by.username == f"pv_{suffix}"

    page_mid = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=2,
        offset=2,
    )
    assert [v.version for v in page_mid.items] == [3, 2]
    assert page_mid.total == 5
    assert page_mid.limit == 2
    assert page_mid.offset == 2


@pytest.mark.asyncio
async def test_list_post_versions_empty_when_post_has_no_versions(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Empty-post case: surgically clear versions then list returns total=0."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user)
    # _make_draft creates v1; clear it so we can exercise the empty path.
    await real_session.execute(delete(PostVersion).where(PostVersion.post_id == post.id))
    await real_session.flush()

    page = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.items == []
    assert page.total == 0


@pytest.mark.asyncio
async def test_list_post_versions_rejects_cross_workspace_access(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T019: a caller in a different workspace gets the post-not-found shape."""
    suffix = uuid.uuid4().hex[:6]
    owner = await _make_user(real_session, user_service, suffix)
    workspace_a = await _make_workspace(real_session, workspace_service, owner, f"{suffix}-a")
    post = await _make_draft(real_session, post_service, workspace_a, owner)

    other_owner = await _make_user(real_session, user_service, f"{suffix}-other")
    workspace_b = await _make_workspace(real_session, workspace_service, other_owner, f"{suffix}-b")

    with pytest.raises(PostNotFoundError):
        await post_version_service.list_for_post(
            real_session,
            workspace_id=workspace_b.id,
            post_id=post.id,
            limit=10,
            offset=0,
        )


# ---------------------------------------------------------------------------
# Phase 4 — US2 view single version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_post_version_returns_decompressed_content(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T022: full content round-trip + frozen title + 404 + cross-workspace 404."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)

    # _make_draft seeds v1 with title="Original" and an initial body.
    post = await _make_draft(real_session, post_service, workspace, user, title="Original", body=_LONG_BODY)

    v2_body = "Body for version two — must be different from v1 and long enough to clear publish gate."
    v3_body = "Body for version three — also distinct, also long enough to satisfy any downstream check."
    await _seed_version(real_session, post_version_repo, post, user.id, title="Original at v2", body=v2_body)
    await _seed_version(real_session, post_version_repo, post, user.id, title="Renamed at v3", body=v3_body)

    detail = await post_version_service.get_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=2,
    )
    assert detail.version == 2
    assert detail.title == "Original at v2"
    assert detail.content_text == v2_body
    assert detail.content_json == _doc(v2_body)
    assert detail.created_by.id == user.id

    # Frozen-title regression: v1's title remains the original even after later renames.
    v1 = await post_version_service.get_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=1,
    )
    assert v1.title == "Original"

    with pytest.raises(PostVersionNotFoundError):
        await post_version_service.get_for_post(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            version=999,
        )

    # Cross-workspace request collapses to PostNotFoundError (no leakage).
    other = await _make_user(real_session, user_service, f"{suffix}-other")
    workspace_b = await _make_workspace(real_session, workspace_service, other, f"{suffix}-b")
    with pytest.raises(PostNotFoundError):
        await post_version_service.get_for_post(
            real_session,
            workspace_id=workspace_b.id,
            post_id=post.id,
            version=1,
        )


# ---------------------------------------------------------------------------
# Phase 5 — US3 restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_replaces_working_copy_and_appends_new_version(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T025: post with v1/v2/v3 → restore v1 → working copy matches v1, new v4 with is_restored=True."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user, title="v1 title", body=_LONG_BODY)
    v1_body = _LONG_BODY
    v2_body = "Second revision body, distinct from v1 and long enough to clear publish gate cleanly."
    v3_body = "Third revision body, also distinct, also comfortably over the fifty-character threshold."
    await _seed_version(real_session, post_version_repo, post, user.id, title="v2 title", body=v2_body)
    await _seed_version(real_session, post_version_repo, post, user.id, title="v3 title", body=v3_body)

    result = await post_version_service.restore(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=1,
        actor_id=user.id,
        change_note=None,
    )
    await real_session.flush()

    # New version row exists with is_restored=True and the synthesized change_note.
    assert result.restored_from_version == 1
    assert result.new_version.version == 4
    assert result.new_version.is_restored is True
    assert result.new_version.change_note == "Restored from version 1"
    assert result.new_version.title == "v1 title"

    # Working copy in posts + post_contents now matches v1.
    reloaded = await post_service.find_or_raise(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        load_content=True,
    )
    assert reloaded.title == "v1 title"
    assert reloaded.content is not None
    assert reloaded.content.content_text == v1_body

    # v2 and v3 are still retrievable.
    v2 = await post_version_service.get_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=2,
    )
    v3 = await post_version_service.get_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=3,
    )
    assert v2.content_text == v2_body
    assert v3.content_text == v3_body
    # Sanity: there are exactly 4 versions now (1 from create, 2 seeded, 1 from restore).
    page = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=10,
        offset=0,
    )
    assert page.total == 4


@pytest.mark.asyncio
async def test_restore_does_not_change_publish_status(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T026: published post + restore draft-era version → status and published_at unchanged (FR-014)."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user, title="Initial", body=_LONG_BODY)

    # Seed a "draft-era" v2 row with status_at_save='draft' (the body we'll restore).
    draft_era_body = "Draft-era body that we will restore later, long enough to clear the publish gate."
    await _seed_version(
        real_session,
        post_version_repo,
        post,
        user.id,
        title="Draft-era title",
        body=draft_era_body,
        status_at_save="draft",
    )

    # Publish the post — this captures a snapshot at status='published'.
    published = await post_service.publish(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
    )
    await real_session.flush()
    assert published.status == "published"
    original_published_at = published.published_at
    assert original_published_at is not None

    # Restore the draft-era version. Status and published_at must NOT move.
    result = await post_version_service.restore(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        version=2,
        actor_id=user.id,
        change_note="Bring back draft v2 body",
    )
    await real_session.flush()
    assert result.new_version.is_restored is True
    assert result.new_version.change_note == "Bring back draft v2 body"

    reloaded = await post_service.find_or_raise(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        load_content=True,
    )
    assert reloaded.status == "published"
    assert reloaded.published_at == original_published_at
    assert reloaded.content is not None
    assert reloaded.content.content_text == draft_era_body
    # The new restore row was stamped with the current status (published),
    # not the source row's status.
    assert result.new_version.status_at_save == "published"


@pytest.mark.asyncio
async def test_restore_missing_version_raises_not_found(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """Restore against a non-existent version surfaces POSTV001 (404)."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user)

    with pytest.raises(PostVersionNotFoundError):
        await post_version_service.restore(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            version=999,
            actor_id=user.id,
            change_note=None,
        )


# ---------------------------------------------------------------------------
# Phase 6 — US4 compare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_versions_returns_structured_diff(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T032: end-to-end compare returns the expected structured diff."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user, title="v1", body=_LONG_BODY)
    v2_body = f"{_LONG_BODY}\nNew paragraph added in v2 that comfortably exceeds the floor."
    await _seed_version(real_session, post_version_repo, post, user.id, title="v2", body=v2_body)

    result = await post_version_service.compare(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        from_version=1,
        to_version=2,
    )
    assert result.post_id == post.id
    assert result.from_version == 1
    assert result.to_version == 2
    assert result.title_changed is True
    # v2 keeps everything from v1 and adds one new line.
    ops = {h.op for h in result.hunks}
    assert "added" in ops
    # The hunk inventory must mention the new sentence (case-insensitive on prefix).
    assert any(h.op == "added" and "New paragraph added in v2" in h.line for h in result.hunks)


@pytest.mark.asyncio
async def test_compare_versions_rejects_identical_from_to(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T032: from==to is 422 / POSTV002 at the service layer."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user)

    with pytest.raises(PostVersionMismatchError):
        await post_version_service.compare(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            from_version=1,
            to_version=1,
        )


@pytest.mark.asyncio
async def test_compare_versions_404s_when_either_version_missing(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user)

    with pytest.raises(PostVersionNotFoundError):
        await post_version_service.compare(
            real_session,
            workspace_id=workspace.id,
            post_id=post.id,
            from_version=1,
            to_version=999,
        )


# ---------------------------------------------------------------------------
# Phase 7 — retention sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retention_sweep_trims_drafts_but_keeps_published(
    real_session: AsyncSession,
    post_service: PostService,
    post_version_service: PostVersionService,
    post_version_repo: PostVersionRepository,
    workspace_service: WorkspaceService,
    user_service: UserService,
) -> None:
    """T036: 25 non-published + 2 published → after sweep, top 20 non-published + both published remain."""
    suffix = uuid.uuid4().hex[:6]
    user = await _make_user(real_session, user_service, suffix)
    workspace = await _make_workspace(real_session, workspace_service, user, suffix)
    post = await _make_draft(real_session, post_service, workspace, user)
    # _make_draft seeds v1 (non-published). Seed 24 more non-published rows so
    # we have a total of 25 non-published rows, then 2 published snapshots on top.
    for i in range(2, 26):
        await _seed_version(
            real_session,
            post_version_repo,
            post,
            user.id,
            title=f"draft v{i}",
            body=f"{_LONG_BODY} draft edit #{i} clears the publish gate cleanly.",
        )
    # Two published snapshots — these must survive the sweep.
    await _seed_version(
        real_session,
        post_version_repo,
        post,
        user.id,
        title="published v26",
        body=f"{_LONG_BODY} first publish snapshot body.",
        is_published_snapshot=True,
        status_at_save="published",
    )
    await _seed_version(
        real_session,
        post_version_repo,
        post,
        user.id,
        title="published v27",
        body=f"{_LONG_BODY} second publish snapshot body.",
        is_published_snapshot=True,
        status_at_save="published",
    )
    await real_session.flush()

    # Sanity: 27 versions total before sweep.
    pre = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=100,
        offset=0,
    )
    assert pre.total == 27

    deleted = await trim_post(real_session, post_id=post.id, retention_limit=20)
    await real_session.flush()

    # 5 non-published rows (v1..v5) deleted; v6..v25 + v26 + v27 remain → 22 total.
    assert deleted == 5
    post_after = await post_version_service.list_for_post(
        real_session,
        workspace_id=workspace.id,
        post_id=post.id,
        limit=100,
        offset=0,
    )
    assert post_after.total == 22
    versions_remaining = sorted([v.version for v in post_after.items])
    # All five published-snapshot version numbers must be present (none purged).
    published_versions = {v.version for v in post_after.items if v.is_published_snapshot}
    assert published_versions == {26, 27}
    # 20 non-published survivors are the newest 20 draft version numbers.
    non_published = sorted(v.version for v in post_after.items if not v.is_published_snapshot)
    assert non_published == list(range(6, 26))
    # Defensive: confirmed via direct numerical check above; ``versions_remaining``
    # is the union of both sets sorted ascending.
    assert versions_remaining == sorted([*non_published, 26, 27])
