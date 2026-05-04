"""Redis-backed autosave store for the blog post body.

The naive autosave path (``UPDATE posts; UPDATE post_contents``) on every
keystroke is a write-amplification disaster: WAL fsync, replication lag,
JSONB whole-document copies under MVCC, vacuum churn. This module routes
autosave traffic into Redis (HASH per post) and lets writes coalesce; a
periodic sweeper or an explicit save (``PATCH`` / ``/publish``) flushes
the latest snapshot to Postgres exactly once.

Schema in Redis:

* ``blog:autosave:post:{post_id}`` — HASH per draft, TTL 7 days.
  Fields: ``content_json`` (str), ``content_hash`` (str),
  ``flushed_hash`` (str), ``word_count`` (int as str),
  ``updated_at`` (ISO8601 str), ``workspace_id`` (uuid str),
  ``author_id`` (uuid str).
* ``blog:autosave:dirty`` — SET of post-ids with unflushed changes.
* ``blog:autosave:lock:{post_id}`` — SET-NX lock, TTL 30s, holding the
  flush across multiple workers.

All public methods short-circuit safely when ``RedisClient`` is ``None``
(Redis disabled). Callers gate on :attr:`AutosaveStore.enabled`.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from loguru import logger

from apps.blog.constants import (
    AUTOSAVE_DIRTY_SET,
    AUTOSAVE_FLUSH_LOCK_TTL,
    AUTOSAVE_KEY_PREFIX,
    AUTOSAVE_LOCK_PREFIX,
    AUTOSAVE_TTL_SECONDS,
)
from apps.core.redis import RedisClient

# Lua script: delete the lock key only if its current value matches the
# token we wrote on acquire — prevents one worker from releasing another's
# lock after a TTL expiry.
_LOCK_RELEASE_SCRIPT: str = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)

# Lua script: atomically rewrite the autosave HASH while preserving the
# existing flushed_hash (or seeding it to "" on first write), then refresh the
# TTL and add the post-id to the dirty set. Folds the previous read-then-write
# sequence (which had a TOCTOU window where a concurrent mark_flushed could be
# clobbered) into a single EVAL.
_SAVE_SCRIPT: str = """
-- KEYS[1] = post HASH key (e.g. blog:autosave:post:<uuid>)
-- KEYS[2] = dirty SET key (blog:autosave:dirty)
-- ARGV[1] = post-id (string, dirty set member)
-- ARGV[2] = ttl_seconds (string)
-- ARGV[3..9] = post_id, workspace_id, author_id, content_json,
--              content_hash, word_count, updated_at
local existing = redis.call('hget', KEYS[1], 'flushed_hash')
if not existing then existing = '' end
redis.call('hset', KEYS[1],
  'post_id', ARGV[3],
  'workspace_id', ARGV[4],
  'author_id', ARGV[5],
  'content_json', ARGV[6],
  'content_hash', ARGV[7],
  'flushed_hash', existing,
  'word_count', ARGV[8],
  'updated_at', ARGV[9])
redis.call('expire', KEYS[1], ARGV[2])
redis.call('sadd', KEYS[2], ARGV[1])
return 1
"""

# Lua script: compare-and-set on content_hash — only mark the snapshot flushed
# and remove from the dirty set when the in-Redis content_hash still matches
# the value the caller is recording. If a concurrent autosave advanced
# content_hash mid-flush, the script returns 0 and the post stays dirty for
# the next sweeper tick.
_MARK_FLUSHED_SCRIPT: str = """
-- KEYS[1] = post HASH key
-- KEYS[2] = dirty SET key
-- ARGV[1] = post-id (dirty set member)
-- ARGV[2] = expected/recorded content_hash (set as flushed_hash on success)
local current = redis.call('hget', KEYS[1], 'content_hash')
if not current or current ~= ARGV[2] then return 0 end
redis.call('hset', KEYS[1], 'flushed_hash', ARGV[2])
redis.call('srem', KEYS[2], ARGV[1])
return 1
"""


@dataclass(frozen=True)
class AutosaveSnapshot:
    """Immutable view of the autosave HASH read back from Redis."""

    post_id: uuid.UUID
    workspace_id: uuid.UUID
    author_id: uuid.UUID
    content_json: dict[str, Any]
    content_hash: str
    flushed_hash: str
    word_count: int
    updated_at: datetime.datetime

    @property
    def is_dirty(self) -> bool:
        """True iff the in-Redis content has not been flushed to Postgres."""
        return self.content_hash != self.flushed_hash


class AutosaveStore:
    """Per-post Redis HASH store + dirty index + flush lock for autosave."""

    def __init__(self, redis_client: RedisClient | None) -> None:
        """Hold the underlying client; pass ``None`` to disable autosave."""
        self._redis = redis_client

    @property
    def enabled(self) -> bool:
        """Whether the underlying Redis client is configured and reachable."""
        return self._redis is not None

    # ------------------------------------------------------------------
    # write / read
    # ------------------------------------------------------------------

    async def save(
        self,
        *,
        post_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: uuid.UUID,
        content_json: dict[str, Any],
        content_hash: str,
        word_count: int,
        now: datetime.datetime | None = None,
    ) -> bool:
        """Persist a new snapshot for ``post_id`` and mark it dirty.

        The HASH is rewritten in full and the dirty set gets the post id.
        ``flushed_hash`` is preserved if the key already exists; on first
        write it is initialized to an empty string so
        :attr:`AutosaveSnapshot.is_dirty` is True.

        The HGET-flushed-then-HSET-all sequence runs inside a single Lua
        ``EVAL`` so a concurrent :meth:`mark_flushed` cannot interleave
        and have its ``flushed_hash`` write clobbered by this save's
        stale read.

        Returns:
            True on success, False when Redis is disabled or the
            connection is down.
        """
        if self._redis is None:
            return False

        timestamp = (now or datetime.datetime.now(datetime.UTC)).isoformat()
        await self._redis.client.eval(
            _SAVE_SCRIPT,
            2,
            self._post_key(post_id),
            AUTOSAVE_DIRTY_SET,
            str(post_id),
            str(AUTOSAVE_TTL_SECONDS),
            str(post_id),
            str(workspace_id),
            str(author_id),
            json.dumps(content_json, ensure_ascii=False, separators=(",", ":")),
            content_hash,
            str(word_count),
            timestamp,
        )
        return True

    async def get(self, post_id: uuid.UUID) -> AutosaveSnapshot | None:
        """Return the current snapshot or ``None`` (also when disabled)."""
        if self._redis is None:
            return None
        raw = await self._redis.hgetall(self._post_key(post_id))
        if not raw:
            return None
        return _parse_snapshot(raw)

    async def mark_flushed(self, post_id: uuid.UUID, *, content_hash: str) -> bool:
        """Record that ``content_hash`` has been written to Postgres.

        Compare-and-set: only updates ``flushed_hash`` and removes the
        post from the dirty set when the in-Redis ``content_hash`` still
        matches the value being marked flushed. If a concurrent
        :meth:`save` advanced the snapshot mid-flush, the CAS returns
        False and the post stays in the dirty set for the next sweeper
        tick (which will re-flush the new content). The whole sequence
        runs in a single Lua ``EVAL`` so HGET and HSET are atomic.

        Returns:
            True when the snapshot was marked flushed, False when the
            CAS rejected (newer save raced, or Redis is disabled).
        """
        if self._redis is None:
            return False
        result = await self._redis.client.eval(
            _MARK_FLUSHED_SCRIPT,
            2,
            self._post_key(post_id),
            AUTOSAVE_DIRTY_SET,
            str(post_id),
            content_hash,
        )
        return bool(result)

    async def discard(self, post_id: uuid.UUID) -> None:
        """Drop the snapshot entirely (used when the post is hard-deleted)."""
        if self._redis is None:
            return
        await self._redis.delete(self._post_key(post_id))
        await self._redis.client.srem(AUTOSAVE_DIRTY_SET, str(post_id))

    async def iter_dirty(self, *, batch_size: int = 100) -> AsyncIterator[uuid.UUID]:
        """Yield post-ids in the dirty set without loading them all at once."""
        if self._redis is None:
            return

        cursor = 0
        while True:
            cursor, batch = await self._redis.client.sscan(
                AUTOSAVE_DIRTY_SET,
                cursor=cursor,
                count=batch_size,
            )
            for raw_id in batch:
                try:
                    yield uuid.UUID(raw_id)
                except (ValueError, TypeError):
                    logger.warning(
                        "AutosaveStore - iter_dirty - skipping non-UUID member",
                        member=raw_id,
                    )
            if cursor == 0:
                break

    # ------------------------------------------------------------------
    # locking
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire_flush_lock(
        self,
        post_id: uuid.UUID,
        *,
        ttl_seconds: int = AUTOSAVE_FLUSH_LOCK_TTL,
    ) -> AsyncIterator[bool]:
        """Acquire a per-post flush lock. Yields True on success, else False.

        Uses ``SET NX EX`` for acquire and a Lua compare-and-del on release
        so a worker can't accidentally clear a lock its TTL already expired
        and another worker re-acquired.
        """
        if self._redis is None:
            yield False
            return

        token = uuid.uuid4().hex
        lock_key = self._lock_key(post_id)
        acquired = await self._redis.set(lock_key, token, ex=ttl_seconds, nx=True)

        try:
            yield bool(acquired)
        finally:
            if acquired:
                try:
                    await self._redis.client.eval(_LOCK_RELEASE_SCRIPT, 1, lock_key, token)
                except Exception:
                    logger.warning(
                        "AutosaveStore - release_lock - eval failed; relying on TTL",
                        post_id=str(post_id),
                    )

    # ------------------------------------------------------------------
    # key builders
    # ------------------------------------------------------------------

    @staticmethod
    def _post_key(post_id: uuid.UUID) -> str:
        return f"{AUTOSAVE_KEY_PREFIX}:{post_id}"

    @staticmethod
    def _lock_key(post_id: uuid.UUID) -> str:
        return f"{AUTOSAVE_LOCK_PREFIX}:{post_id}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_snapshot(raw: dict[str, str]) -> AutosaveSnapshot | None:
    """Parse a raw HGETALL into :class:`AutosaveSnapshot`; ``None`` on bad data."""
    try:
        return AutosaveSnapshot(
            post_id=uuid.UUID(raw["post_id"]),
            workspace_id=uuid.UUID(raw["workspace_id"]),
            author_id=uuid.UUID(raw["author_id"]),
            content_json=json.loads(raw["content_json"]),
            content_hash=raw["content_hash"],
            flushed_hash=raw.get("flushed_hash", ""),
            word_count=int(raw.get("word_count", "0")),
            updated_at=datetime.datetime.fromisoformat(raw["updated_at"]),
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("AutosaveStore - _parse_snapshot - corrupt HASH; treating as miss")
        return None
