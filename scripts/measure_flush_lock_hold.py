"""Measure flush-lock hold time over a 50-autosave burst on a single post.

Captures the F-PERF-4 (US4) baseline before the reorder lands, and is
re-run after the reorder to confirm the regression budget. Writes a
single JSON object to stdout (or ``--output``) with median + p99
lock-hold time in milliseconds.

Pre-conditions:
    docker compose up -d postgres redis
    uv run alembic upgrade head

Usage:
    uv run python scripts/measure_flush_lock_hold.py \\
        --samples 50 --duration 10 \\
        --payload scripts/synthetic_large_post.json \\
        --output tests/fixtures/flush_lock_hold_baseline.json

The harness creates an ephemeral user / workspace / post, drives the
configured number of autosave + flush cycles paced across ``--duration``
seconds, then deletes the rows it created. Lock-hold time is captured
by wrapping :meth:`AutosaveStore.acquire_flush_lock` to record
``perf_counter`` deltas around the body of the ``async with`` block.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Importing apps.auth.models ensures the ``RefreshToken`` mapper is
# registered before SQLAlchemy resolves the ``User.refresh_tokens``
# relationship target at first query time.
from apps.auth import models as _auth_models  # noqa: F401
from apps.blog.models import Post, PostContent, PostVersion
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
from apps.core.database.engine import SQLAlchemyEngineTypes, engine_factory
from apps.core.redis import CacheManager, get_redis_client
from apps.user.models import User
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.models import Workspace, WorkspaceMember
from apps.workspace.repositories import (
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

_DEFAULT_PAYLOAD: Path = Path(__file__).resolve().parent / "synthetic_large_post.json"


def _percentile(samples: list[float], pct: float) -> float:
    """Linear-interpolation percentile (matches numpy.percentile default)."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def instrument_lock(store: AutosaveStore, holds: list[float]) -> None:
    """Wrap ``store.acquire_flush_lock`` so successful holds append to ``holds``.

    The wrap preserves the original generator semantics — it only times
    the body of the ``async with`` block executed by the caller. The
    failure path (lock not acquired) records nothing.
    """
    original = store.acquire_flush_lock

    @contextlib.asynccontextmanager
    async def wrapped(
        post_id: uuid.UUID,
        *,
        ttl_seconds: int = 30,
    ) -> AsyncIterator[bool]:
        async with original(post_id, ttl_seconds=ttl_seconds) as got:
            if not got:
                yield got
                return
            t0 = time.perf_counter()
            try:
                yield got
            finally:
                holds.append((time.perf_counter() - t0) * 1000.0)

    store.acquire_flush_lock = wrapped  # type: ignore[method-assign]


def _mutate_payload(base: dict[str, Any], iteration: int) -> dict[str, Any]:
    """Return a copy of ``base`` with a unique trailing paragraph for ``iteration``.

    The mutation must change the canonical-JSON hash so every autosave is
    treated as dirty and every flush actually runs the body pipeline.
    """
    content = list(base.get("content", []))
    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": f"edit-{iteration}"}],
        },
    )
    return {**base, "content": content}


async def _seed_fixtures(
    session: AsyncSession,
    post_service: PostService,
    suffix: str,
    payload: dict[str, Any],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_service = UserService(repository=UserRepository())
    workspace_service = WorkspaceService(
        repository=WorkspaceRepository(),
        member_repository=WorkspaceMemberRepository(),
    )

    user = await user_service.create(
        session,
        data=CreateUserRequest(
            email=f"flushlock_{suffix}@example.com",
            username=f"flushlock_{suffix}",
            password="Sup3rSecret!",  # noqa: S106  synthetic harness fixture
        ),
    )
    await session.flush()

    workspace = await workspace_service.create(
        session,
        owner_user_id=user.id,
        data=CreateWorkspaceRequest(
            slug=f"flushlock-{suffix}",
            name=f"FlushLock {suffix}",
            description=None,
        ),
    )
    await session.flush()

    post = await post_service.create(
        session,
        workspace_id=workspace.id,
        author_id=user.id,
        data=CreatePostRequest(
            title=f"FlushLock {suffix}",
            slug=None,
            content_json=payload,
        ),
    )
    await session.flush()
    return user.id, workspace.id, post.id


async def _cleanup_fixtures(
    session_maker: async_sessionmaker[AsyncSession],
    redis_client: Any,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    post_id: uuid.UUID,
) -> None:
    async with session_maker() as session, session.begin():
        await session.execute(delete(PostVersion).where(PostVersion.post_id == post_id))
        await session.execute(delete(PostContent).where(PostContent.post_id == post_id))
        await session.execute(delete(Post).where(Post.id == post_id))
        await session.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.execute(delete(User).where(User.id == user_id))
    if redis_client is not None:
        await redis_client.delete(f"blog:autosave:post:{post_id}")
        await redis_client.client.srem("blog:autosave:dirty", str(post_id))


async def measure(
    *,
    samples: int,
    duration: float,
    payload: dict[str, Any],
    warmup: int = 5,
) -> dict[str, Any]:
    """Drive the measurement loop and return summary statistics.

    Args:
        samples: Number of measured autosave+flush cycles.
        duration: Wall-clock seconds across which the measured cycles
            are paced.
        payload: Tiptap document used as the autosave body.
        warmup: Number of untracked flushes to run before measurement
            begins (default 5). The warmup primes Postgres connection
            state, Redis cache lines, and asyncpg's prepared-statement
            cache so the first measured sample doesn't see cold-start
            outliers when the harness runs after other CI tests.

    Returns:
        Dict with ``median_ms``, ``p99_ms``, ``mean_ms``, ``count``,
        ``samples_ms``.

    Raises:
        RuntimeError: If Redis is disabled / unreachable.
    """
    redis_client = get_redis_client()
    if redis_client is None:
        msg = "Redis disabled — set REDIS_ENABLED=true and ensure Redis is reachable."
        raise RuntimeError(msg)

    writer_engine = engine_factory(SQLAlchemyEngineTypes.WRITER)
    session_maker = async_sessionmaker(bind=writer_engine, expire_on_commit=False, class_=AsyncSession)
    cache_manager = CacheManager(redis_client=redis_client)
    autosave_store = AutosaveStore(redis_client=redis_client)
    post_service = PostService(
        repository=PostRepository(),
        content_repository=PostContentRepository(),
        post_tag_repository=PostTagRepository(),
        category_repository=CategoryRepository(),
        tag_repository=TagRepository(),
        post_version_repository=PostVersionRepository(),
        cache=cache_manager,
        autosave_store=autosave_store,
    )

    holds: list[float] = []
    instrument_lock(autosave_store, holds)

    suffix = uuid.uuid4().hex[:8]
    async with session_maker() as session, session.begin():
        user_id, workspace_id, post_id = await _seed_fixtures(
            session,
            post_service,
            suffix,
            payload,
        )

    # Warmup pass: drive a few iterations without recording. The holds
    # list is cleared after warmup so only steady-state samples count
    # — primes Postgres connection state, Redis cache lines, and
    # asyncpg's prepared-statement cache.
    for w in range(warmup):
        warmup_doc = _mutate_payload(payload, -1 - w)
        async with session_maker() as warmup_session, warmup_session.begin():
            await post_service.autosave(
                warmup_session,
                workspace_id=workspace_id,
                post_id=post_id,
                author_id=user_id,
                content_json=warmup_doc,
            )
        async with session_maker() as warmup_flush_session:
            await post_service.flush_one(
                warmup_flush_session,
                workspace_id=workspace_id,
                post_id=post_id,
            )
    holds.clear()

    interval = duration / samples
    try:
        for i in range(samples):
            iteration_start = time.perf_counter()
            doc = _mutate_payload(payload, i)

            async with session_maker() as autosave_session, autosave_session.begin():
                await post_service.autosave(
                    autosave_session,
                    workspace_id=workspace_id,
                    post_id=post_id,
                    author_id=user_id,
                    content_json=doc,
                )

            async with session_maker() as flush_session:
                await post_service.flush_one(
                    flush_session,
                    workspace_id=workspace_id,
                    post_id=post_id,
                )

            elapsed = time.perf_counter() - iteration_start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
    finally:
        await _cleanup_fixtures(session_maker, redis_client, user_id, workspace_id, post_id)
        await writer_engine.dispose()

    return {
        "median_ms": statistics.median(holds) if holds else 0.0,
        "p99_ms": _percentile(holds, 99.0),
        "mean_ms": statistics.fmean(holds) if holds else 0.0,
        "count": len(holds),
        "samples_ms": holds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--payload", type=Path, default=_DEFAULT_PAYLOAD)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON to this path instead of stdout.",
    )
    args = parser.parse_args()

    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    result = asyncio.run(measure(samples=args.samples, duration=args.duration, payload=payload))
    serialized = json.dumps(result, separators=(",", ":")) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
