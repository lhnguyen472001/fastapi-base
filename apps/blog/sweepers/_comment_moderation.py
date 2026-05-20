"""Comment-moderation retention sweeper.

Hard-deletes ``state='pending'`` rows on ``post_comments`` that have been
sitting in the moderation queue beyond
``POST_COMMENT_MODERATION_PENDING_TTL_SECONDS`` (default 30 days). The
delete is counter-neutral because ``pending`` rows never contributed to
``posts.comment_count``.

Shape mirrors the post-version sweeper: every uvicorn worker spawns the
same forever loop, all workers race for a single Redis leader lock
(distinct key so the three sweepers do not block each other), and only
the holder actually issues the DELETE.

Cadence: ``POST_COMMENT_MODERATION_SWEEP_INTERVAL`` (default 1 hour). The
sweeper is a janitor — it does not need keystroke-grade latency.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from collections.abc import Callable
from contextlib import suppress

from loguru import logger

from apps.blog.constants import (
    POST_COMMENT_MODERATION_PENDING_TTL_SECONDS,
    POST_COMMENT_MODERATION_SWEEP_BATCH,
    POST_COMMENT_MODERATION_SWEEP_INTERVAL,
    POST_COMMENT_MODERATION_SWEEPER_LEADER_TTL,
)
from apps.blog.repositories import PostCommentRepository
from apps.blog.store import AutosaveStore
from apps.core.database.types import SessionType


async def delete_stale_pending_comments(
    session: SessionType,
    *,
    cutoff_seconds: float,
    batch_size: int = POST_COMMENT_MODERATION_SWEEP_BATCH,
) -> int:
    """Run one bounded DELETE against ``post_comments``. Returns rows removed.

    Public so tests can drive a single pass against an existing rolled-back
    session without spinning up the forever loop or the leader-election. The
    DELETE is bounded by ``batch_size`` so even a misconfigured TTL of zero
    cannot stall the writer.
    """
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=cutoff_seconds)
    repo = PostCommentRepository()
    return await repo.delete_stale_pending(session, cutoff=cutoff, limit=batch_size)


async def sweep_pending_comments_once(
    session_factory: Callable[[], SessionType],
    *,
    pending_ttl_seconds: int = POST_COMMENT_MODERATION_PENDING_TTL_SECONDS,
    batch_size: int = POST_COMMENT_MODERATION_SWEEP_BATCH,
) -> int:
    """Open one short transaction and drain up to ``batch_size`` stale rows.

    Logs INFO when any rows are purged and DEBUG-on-error so transient DB
    issues don't cascade into a sweeper crash. Returns the count purged so
    the loop can keep a running total for heartbeat logging.
    """
    try:
        async with session_factory() as session, session.begin():
            purged = await delete_stale_pending_comments(
                session,
                cutoff_seconds=pending_ttl_seconds,
                batch_size=batch_size,
            )
    except Exception:
        logger.exception(
            "comment_moderation_sweeper - purge failed; will retry next tick",
            pending_ttl_seconds=pending_ttl_seconds,
            batch_size=batch_size,
        )
        return 0

    if purged:
        logger.info(
            "comment_moderation_sweeper - purged",
            purged=purged,
            pending_ttl_seconds=pending_ttl_seconds,
        )
    return purged


async def comment_moderation_sweeper(
    session_factory: Callable[[], SessionType],
    autosave_store: AutosaveStore,
    *,
    interval: float = POST_COMMENT_MODERATION_SWEEP_INTERVAL,
    batch_size: int = POST_COMMENT_MODERATION_SWEEP_BATCH,
    pending_ttl_seconds: int = POST_COMMENT_MODERATION_PENDING_TTL_SECONDS,
    leader_ttl_seconds: int = POST_COMMENT_MODERATION_SWEEPER_LEADER_TTL,
) -> None:
    """Run forever as a leader-elected retention loop for moderation pending rows.

    Each iteration sleeps ``interval`` seconds, attempts to acquire or renew
    leadership on the moderation-sweeper Redis key, and — if leader — runs
    one :func:`sweep_pending_comments_once`. Loop only exits on cancellation
    from the lifespan teardown.

    When Redis is disabled (``autosave_store.enabled is False``) the loop
    exits silently — retention is treated as best-effort, matching the
    autosave + version sweeper contract.
    """
    if not autosave_store.enabled:
        logger.info("comment_moderation_sweeper - disabled (Redis off); exiting")
        return

    token = uuid.uuid4().hex
    is_leader = False
    tick_count = 0
    purged_count = 0

    logger.info(
        "comment_moderation_sweeper - started",
        token=token,
        interval=interval,
        batch_size=batch_size,
        pending_ttl_seconds=pending_ttl_seconds,
    )

    try:
        while True:
            await asyncio.sleep(interval)
            acquired = await autosave_store.acquire_or_renew_comment_moderation_sweeper_leadership(
                token=token,
                ttl_seconds=leader_ttl_seconds,
            )
            if not acquired:
                if is_leader:
                    logger.warning("comment_moderation_sweeper - lost leadership", token=token)
                is_leader = False
                continue

            if not is_leader:
                logger.info("comment_moderation_sweeper - became leader", token=token)
            is_leader = True

            tick_count += 1
            purged_count += await sweep_pending_comments_once(
                session_factory,
                pending_ttl_seconds=pending_ttl_seconds,
                batch_size=batch_size,
            )
    except asyncio.CancelledError:
        logger.info(
            "comment_moderation_sweeper - cancelled",
            token=token,
            is_leader=is_leader,
            tick_count=tick_count,
            purged_count=purged_count,
        )
        if is_leader:
            await autosave_store.release_comment_moderation_sweeper_leadership(token=token)
        raise


def start_comment_moderation_sweeper_task(
    session_factory: Callable[[], SessionType],
    autosave_store: AutosaveStore,
) -> asyncio.Task[None]:
    """Spawn :func:`comment_moderation_sweeper` as a background task.

    The returned task should be cancelled and awaited from the FastAPI
    lifespan teardown so the loop exits cleanly.
    """
    return asyncio.create_task(
        comment_moderation_sweeper(session_factory, autosave_store),
        name="blog.comment_moderation_sweeper",
    )


async def stop_comment_moderation_sweeper_task(task: asyncio.Task[None]) -> None:
    """Cancel and await a running moderation-sweeper task; tolerant of already-done state."""
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
