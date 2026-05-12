"""Periodic flush of dirty autosave snapshots from Redis to Postgres.

Every uvicorn worker spawns one of these tasks from the FastAPI lifespan,
but only one task across the fleet does work per tick: workers race for
a single Redis leader lock and the holder runs ``sweep_once``. Followers
sleep silently and try to take over on the next tick if the leader's
lock has expired (worker crashed).

This keeps Redis SSCAN load flat as the web fleet scales — flush
parallelism is bounded by the dirty rate, not the worker count. Per-post
flush safety still relies on :meth:`AutosaveStore.acquire_flush_lock`;
leader election is a coordination optimisation, not the safety net.

Failures on individual posts are logged and skipped. The loop only exits
on ``asyncio.CancelledError`` from the lifespan teardown, after running
one final drain pass if this worker happened to be the leader.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from collections.abc import Callable
from contextlib import suppress

from loguru import logger

from apps.blog.constants import (
    AUTOSAVE_HEARTBEAT_LOG_EVERY,
    AUTOSAVE_SWEEP_BATCH,
    AUTOSAVE_SWEEP_INTERVAL,
    AUTOSAVE_SWEEPER_LEADER_TTL,
    POST_VERSION_RETENTION_LIMIT,
    POST_VERSION_SWEEP_BATCH,
    POST_VERSION_SWEEP_INTERVAL,
    POST_VERSION_SWEEPER_LEADER_TTL,
)
from apps.blog.repositories import PostVersionRepository
from apps.blog.services import PostService
from apps.blog.store import AutosaveStore
from apps.core.database.types import SessionType

# Headroom over the retention cap before a sweep targets a post. Avoids
# fighting the application on every save when a post sits at exactly
# RETENTION_LIMIT+1.
_VERSION_RETENTION_SLACK: int = 5


async def autosave_sweeper(
    session_factory: Callable[[], SessionType],
    post_service: PostService,
    autosave_store: AutosaveStore,
    *,
    interval: float = AUTOSAVE_SWEEP_INTERVAL,
    batch_size: int = AUTOSAVE_SWEEP_BATCH,
    leader_ttl_seconds: int = AUTOSAVE_SWEEPER_LEADER_TTL,
    heartbeat_every_ticks: int = AUTOSAVE_HEARTBEAT_LOG_EVERY,
) -> None:
    """Run forever as a leader-elected flush loop.

    Each iteration sleeps ``interval`` seconds, attempts to acquire or
    renew leadership in a single Lua call, and — if leader — runs one
    ``sweep_once``. The leader emits a periodic structured heartbeat so
    an observer can distinguish "idle but healthy" from "no leader at
    all"; followers stay silent.

    ``session_factory`` is the writer-bound ``async_session_factory``
    context-manager. Each flushed post gets its own short transaction.
    """
    if not autosave_store.enabled:
        logger.info("autosave_sweeper - disabled (Redis off); exiting")
        return

    token = uuid.uuid4().hex
    is_leader = False
    tick_count = 0
    flush_count = 0

    logger.info(
        "autosave_sweeper - started",
        token=token,
        interval=interval,
        batch_size=batch_size,
        leader_ttl_seconds=leader_ttl_seconds,
    )

    try:
        while True:
            await asyncio.sleep(interval)
            acquired = await autosave_store.acquire_or_renew_sweeper_leadership(
                token=token,
                ttl_seconds=leader_ttl_seconds,
            )
            if not acquired:
                if is_leader:
                    logger.warning("autosave_sweeper - lost leadership", token=token)
                is_leader = False
                continue

            if not is_leader:
                logger.info("autosave_sweeper - became leader", token=token)
            is_leader = True

            tick_count += 1
            flush_count += await sweep_once(
                session_factory,
                post_service,
                autosave_store,
                batch_size=batch_size,
            )

            if tick_count % heartbeat_every_ticks == 0:
                logger.info(
                    "autosave_sweeper - heartbeat",
                    token=token,
                    tick_count=tick_count,
                    flush_count=flush_count,
                )
    except asyncio.CancelledError:
        logger.info(
            "autosave_sweeper - cancelled",
            token=token,
            is_leader=is_leader,
            tick_count=tick_count,
            flush_count=flush_count,
        )
        if is_leader:
            with suppress(Exception):
                await sweep_once(
                    session_factory,
                    post_service,
                    autosave_store,
                    batch_size=batch_size,
                )
            await autosave_store.release_sweeper_leadership(token=token)
        raise


async def sweep_once(
    session_factory: Callable[[], SessionType],
    post_service: PostService,
    autosave_store: AutosaveStore,
    *,
    batch_size: int = AUTOSAVE_SWEEP_BATCH,
) -> int:
    """Flush up to ``batch_size`` dirty posts. Returns the number flushed.

    Public so tests can drive a single tick deterministically without
    spinning the forever loop.
    """
    flushed = 0
    seen = 0
    async for post_id in autosave_store.iter_dirty(batch_size=batch_size):
        seen += 1
        snapshot = await autosave_store.get(post_id)
        if snapshot is None or not snapshot.is_dirty:
            continue
        try:
            async with session_factory() as session:
                result = await post_service.flush_one(
                    session,
                    workspace_id=snapshot.workspace_id,
                    post_id=post_id,
                )
                if result is not None:
                    flushed += 1
                    lag_seconds = (datetime.datetime.now(datetime.UTC) - snapshot.updated_at).total_seconds()
                    logger.info(
                        "autosave_sweeper - flush ok",
                        post_id=str(post_id),
                        lag_seconds=round(lag_seconds, 3),
                    )
        except Exception:
            logger.exception(
                "autosave_sweeper - flush failed; will retry next tick",
                post_id=str(post_id),
            )

        if seen >= batch_size:
            break

    if flushed or seen:
        logger.info(
            "autosave_sweeper - tick complete",
            seen=seen,
            flushed=flushed,
        )
    return flushed


def start_sweeper_task(
    session_factory: Callable[[], SessionType],
    post_service: PostService,
    autosave_store: AutosaveStore,
) -> asyncio.Task[None]:
    """Spawn :func:`autosave_sweeper` as a background task.

    The returned task should be cancelled and awaited from the FastAPI
    lifespan teardown so the loop exits cleanly.
    """
    return asyncio.create_task(
        autosave_sweeper(session_factory, post_service, autosave_store),
        name="blog.autosave_sweeper",
    )


async def stop_sweeper_task(task: asyncio.Task[None]) -> None:
    """Cancel and await a running sweeper task; tolerant of already-done state."""
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Post-version retention sweeper
# ---------------------------------------------------------------------------
#
# Caps non-published draft history per post at
# ``POST_VERSION_RETENTION_LIMIT`` (newest-first). Published-snapshot
# rows are *never* purged — they're the audit trail for what users saw
# on the live site.
#
# Shape mirrors the autosave sweeper above: every uvicorn worker spawns
# the same forever loop, all workers race for a single Redis leader
# lock (a distinct key from the autosave one so the two sweepers do not
# block each other), and only the holder actually queries/deletes.
#
# Cadence: ``POST_VERSION_SWEEP_INTERVAL`` (default 10 minutes). The
# sweeper does not need keystroke-grade latency — newest writes are
# visible immediately; the sweeper only trims the tail.


async def post_version_sweeper(
    session_factory: Callable[[], SessionType],
    autosave_store: AutosaveStore,
    *,
    interval: float = POST_VERSION_SWEEP_INTERVAL,
    batch_size: int = POST_VERSION_SWEEP_BATCH,
    retention_limit: int = POST_VERSION_RETENTION_LIMIT,
    leader_ttl_seconds: int = POST_VERSION_SWEEPER_LEADER_TTL,
) -> None:
    """Run forever as a leader-elected retention loop.

    Each iteration sleeps ``interval`` seconds, attempts to acquire or
    renew leadership, and — if leader — runs one
    :func:`sweep_post_versions_once`. Loops only exit on cancellation
    from the lifespan teardown.
    """
    if not autosave_store.enabled:
        logger.info("post_version_sweeper - disabled (Redis off); exiting")
        return

    token = uuid.uuid4().hex
    is_leader = False
    tick_count = 0
    purged_count = 0

    logger.info(
        "post_version_sweeper - started",
        token=token,
        interval=interval,
        batch_size=batch_size,
        retention_limit=retention_limit,
    )

    try:
        while True:
            await asyncio.sleep(interval)
            acquired = await autosave_store.acquire_or_renew_version_sweeper_leadership(
                token=token,
                ttl_seconds=leader_ttl_seconds,
            )
            if not acquired:
                if is_leader:
                    logger.warning("post_version_sweeper - lost leadership", token=token)
                is_leader = False
                continue

            if not is_leader:
                logger.info("post_version_sweeper - became leader", token=token)
            is_leader = True

            tick_count += 1
            purged_count += await sweep_post_versions_once(
                session_factory,
                batch_size=batch_size,
                retention_limit=retention_limit,
            )
    except asyncio.CancelledError:
        logger.info(
            "post_version_sweeper - cancelled",
            token=token,
            is_leader=is_leader,
            tick_count=tick_count,
            purged_count=purged_count,
        )
        if is_leader:
            await autosave_store.release_version_sweeper_leadership(token=token)
        raise


async def trim_post(
    session: SessionType,
    *,
    post_id: uuid.UUID,
    retention_limit: int = POST_VERSION_RETENTION_LIMIT,
) -> int:
    """Trim non-published versions for ``post_id`` down to ``retention_limit``.

    Public so tests can drive retention against an existing rolled-back
    session without spinning a session_factory. Returns the number of
    rows deleted (zero when the post is already under cap).
    Published-snapshot rows are excluded from both the count and the
    delete predicate (FR-016).
    """
    repo = PostVersionRepository()
    keep = await repo.list_non_published_version_numbers(
        session,
        post_id=post_id,
        newest_first=True,
    )
    keep_top_n = keep[:retention_limit]
    return await repo.purge_eligible(
        session,
        post_id=post_id,
        keep_versions=keep_top_n,
    )


async def sweep_post_versions_once(
    session_factory: Callable[[], SessionType],
    *,
    batch_size: int = POST_VERSION_SWEEP_BATCH,
    retention_limit: int = POST_VERSION_RETENTION_LIMIT,
) -> int:
    """Trim up to ``batch_size`` over-cap posts. Returns total rows deleted.

    Each over-cap post is processed in its own short transaction so one
    slow / errored post can't block the rest of the batch.
    """
    repo = PostVersionRepository()
    total_purged = 0
    async with session_factory() as discover_session:
        candidates = await repo.find_posts_over_retention(
            discover_session,
            retention_limit=retention_limit,
            slack=_VERSION_RETENTION_SLACK,
            batch_size=batch_size,
        )

    if not candidates:
        return 0

    logger.info(
        "post_version_sweeper - sweep_once start",
        retention_limit=retention_limit,
        candidates=len(candidates),
    )

    for post_id in candidates:
        try:
            async with session_factory() as session, session.begin():
                deleted = await trim_post(
                    session,
                    post_id=post_id,
                    retention_limit=retention_limit,
                )
                total_purged += deleted
                if deleted:
                    logger.info(
                        "post_version_sweeper - purged",
                        post_id=str(post_id),
                        deleted=deleted,
                    )
        except Exception:
            logger.exception(
                "post_version_sweeper - purge failed; will retry next tick",
                post_id=str(post_id),
            )

    logger.info(
        "post_version_sweeper - sweep_once complete",
        total_purged=total_purged,
        candidates=len(candidates),
    )
    return total_purged


def start_post_version_sweeper_task(
    session_factory: Callable[[], SessionType],
    autosave_store: AutosaveStore,
) -> asyncio.Task[None]:
    """Spawn :func:`post_version_sweeper` as a background task.

    The returned task should be cancelled and awaited from the FastAPI
    lifespan teardown so the loop exits cleanly.
    """
    return asyncio.create_task(
        post_version_sweeper(session_factory, autosave_store),
        name="blog.post_version_sweeper",
    )


async def stop_post_version_sweeper_task(task: asyncio.Task[None]) -> None:
    """Cancel and await a running version-sweeper task; tolerant of already-done state."""
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
