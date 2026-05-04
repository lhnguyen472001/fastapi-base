"""Periodic flush of dirty autosave snapshots from Redis to Postgres.

The sweeper is a single ``asyncio`` task launched from the FastAPI
lifespan. Each tick it scans the dirty set, looks up each post's
workspace via the snapshot HASH, and calls
:meth:`apps.blog.services.PostService.flush_one` under a per-post Redis
lock — so even when multiple uvicorn workers run the sweeper, every post
gets flushed at most once per tick.

Failures on individual posts are logged and skipped; the loop never
crashes, only ``asyncio.CancelledError`` from the lifespan teardown
breaks it out.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress

from loguru import logger

from apps.blog.constants import AUTOSAVE_SWEEP_BATCH, AUTOSAVE_SWEEP_INTERVAL
from apps.blog.services import PostService
from apps.blog.store import AutosaveStore
from apps.core.database.types import SessionType


async def autosave_sweeper(
    session_factory: Callable[[], SessionType],
    post_service: PostService,
    autosave_store: AutosaveStore,
    *,
    interval: float = AUTOSAVE_SWEEP_INTERVAL,
    batch_size: int = AUTOSAVE_SWEEP_BATCH,
) -> None:
    """Run forever, flushing dirty autosave snapshots in bounded batches.

    ``session_factory`` is an async-session context-manager factory
    invoked once per flushed post so each flush gets its own short
    transaction. We use the project's ``async_session_factory``
    (writer-bound) directly rather than the request-scoped
    ``session_factory`` dependency.
    """
    if not autosave_store.enabled:
        logger.info("autosave_sweeper - disabled (Redis off); exiting")
        return

    logger.info(
        "autosave_sweeper - started",
        interval=interval,
        batch_size=batch_size,
    )

    try:
        while True:
            await asyncio.sleep(interval)
            await sweep_once(session_factory, post_service, autosave_store, batch_size=batch_size)
    except asyncio.CancelledError:
        logger.info("autosave_sweeper - cancelled; exiting")
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
