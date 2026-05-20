"""Standalone autosave service (Phase B.5 promotion of ``_PostAutosaveMixin``).

Owns the Redis-first write-behind path for the editor body, the
backend flush into Postgres, and the merged-read for admins. Lives
alongside :class:`PostService` as a peer collaborator so the post
service no longer carries the autosave knobs on its own constructor.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import uuid
from typing import Any

from loguru import logger

from apps.blog.constants import WORDS_PER_MINUTE
from apps.blog.enums import PostStatus
from apps.blog.exceptions import (
    PostAutosaveOnArchivedError,
    PostAutosaveUnavailableError,
    PostInvalidStatusTransitionError,
    PostNotFoundError,
)
from apps.blog.models import Post
from apps.blog.repositories import PostRepository
from apps.blog.schemas import PostDetailResponse
from apps.blog.services._cache import PostCacheService
from apps.blog.services._content_writer import PostContentWriterService
from apps.blog.store import AutosaveSnapshot, AutosaveStore
from apps.blog.utils import (
    compress_content_json_async,
    compute_content_artifacts_async,
)
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.tiptap import extract_text


class PostAutosaveService:
    """Autosave / flush / merged-read flow for posts."""

    def __init__(
        self,
        post_repository: PostRepository,
        content_writer: PostContentWriterService,
        cache_service: PostCacheService,
        autosave_store: AutosaveStore,
    ) -> None:
        self.post_repository = post_repository
        self.content_writer = content_writer
        self.cache_service = cache_service
        self.autosave_store = autosave_store

    async def autosave(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        author_id: uuid.UUID,
        content_json: dict[str, Any],
    ) -> tuple[str, int, int, datetime.datetime, bool]:
        """Persist a draft body snapshot to Redis only.

        Returns ``(content_hash, word_count, reading_minutes, updated_at,
        persisted)`` where ``persisted`` is True iff the snapshot's hash
        already matches Postgres (so the call was a no-op short-circuit).

        Raises:
            PostAutosaveUnavailableError: If Redis is disabled / down.
            PostAutosaveOnArchivedError: If the post is archived.
            PostInvalidStatusTransitionError: If the post is published —
                live edits to a published post are out of scope for v1.
            PostNotFoundError: If the post doesn't exist in this workspace.
        """
        if not self.autosave_store.enabled:
            raise PostAutosaveUnavailableError()

        state = await self.post_repository.find_autosave_state(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )
        if state is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")
        if state.status == PostStatus.ARCHIVED.value:
            raise PostAutosaveOnArchivedError()
        if state.status != PostStatus.DRAFT.value:
            raise PostInvalidStatusTransitionError(
                message=f"Autosave is only allowed on draft posts; current status: '{state.status}'.",
            )

        text = extract_text(content_json)
        word_count = len(text.split()) if text else 0
        reading_minutes = max(1, math.ceil(word_count / WORDS_PER_MINUTE)) if word_count > 0 else 0
        canonical = json.dumps(content_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        if content_hash == state.content_hash:
            now = datetime.datetime.now(datetime.UTC)
            return content_hash, word_count, reading_minutes, now, True

        now = datetime.datetime.now(datetime.UTC)
        await self.autosave_store.save(
            post_id=post_id,
            workspace_id=workspace_id,
            author_id=author_id,
            content_json=content_json,
            content_hash=content_hash,
            word_count=word_count,
            now=now,
        )
        return content_hash, word_count, reading_minutes, now, False

    @transactional
    async def flush_one(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post | None:
        """Write the latest autosave snapshot for ``post_id`` to Postgres.

        Idempotent: returns ``None`` when there is nothing to flush.
        On success returns the reloaded post.
        """
        if not self.autosave_store.enabled:
            return None

        snapshot = await self.autosave_store.get(post_id)
        if snapshot is None or not snapshot.is_dirty:
            return None
        if snapshot.workspace_id != workspace_id:
            logger.warning(
                "PostAutosaveService - flush_one - workspace mismatch; skipping",
                expected=str(workspace_id),
                got=str(snapshot.workspace_id),
                post_id=str(post_id),
            )
            return None

        (
            content_text,
            content_html,
            content_hash,
            word_count,
            reading_minutes,
        ) = await compute_content_artifacts_async(snapshot.content_json)
        content_json_compressed = await compress_content_json_async(snapshot.content_json)

        post = await self._load_post_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )

        async with self.autosave_store.acquire_flush_lock(post_id) as got_lock:
            if not got_lock:
                return None

            if content_hash != snapshot.content_hash:
                logger.warning(
                    "PostAutosaveService - flush_one - hash drift between Redis snapshot and recompute",
                    snapshot=snapshot.content_hash,
                    recomputed=content_hash,
                    post_id=str(post_id),
                )

            await self.content_writer.upsert_content_for_flush(
                session,
                post=post,
                snapshot_content_json=snapshot.content_json,
                content_html=content_html,
                content_text=content_text,
            )

            await self.post_repository.update(
                session,
                item_id=post_id,
                data={
                    "content_hash": content_hash,
                    "word_count": word_count,
                    "reading_minutes": reading_minutes,
                },
            )

            await self._write_post_version(
                session,
                post=post,
                workspace_id=workspace_id,
                snapshot=snapshot,
                content_text=content_text,
                content_hash=content_hash,
                content_json_compressed=content_json_compressed,
            )

        await self.autosave_store.mark_flushed(post_id, content_hash=content_hash)
        await self.cache_service.invalidate_workspace(workspace_id)
        return await self._load_post_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )

    async def merge_dirty_snapshot_into_detail(
        self,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        base_detail: PostDetailResponse,
    ) -> PostDetailResponse:
        """Overlay any unflushed snapshot onto ``base_detail`` for admin reads.

        If autosave is disabled or there is no dirty snapshot for this
        post (or it is for a different workspace), returns ``base_detail``
        unchanged. Otherwise renders the snapshot body via the cached
        render service and patches the body fields of the response.
        """
        if not self.autosave_store.enabled:
            return base_detail

        snapshot = await self.autosave_store.get(post_id)
        if snapshot is None or not snapshot.is_dirty:
            return base_detail
        if snapshot.workspace_id != workspace_id:
            return base_detail

        content_text = extract_text(snapshot.content_json)
        content_html = await self.cache_service.render_html_cached(
            post_id=post_id,
            content_json=snapshot.content_json,
            content_hash=snapshot.content_hash,
        )
        return base_detail.model_copy(
            update={
                "content_json": snapshot.content_json,
                "content_text": content_text,
                "content_html": content_html,
                "content_hash": snapshot.content_hash,
                "word_count": snapshot.word_count,
                "reading_minutes": (
                    max(1, math.ceil(snapshot.word_count / WORDS_PER_MINUTE)) if snapshot.word_count > 0 else 0
                ),
            },
        )

    async def _load_post_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        load_content: bool,
    ) -> Post:
        """Same shape as :meth:`PostService.find_or_raise` / ``_reload``.

        Inlined here so the autosave service has no implicit dependency
        on the post service.
        """
        post = await self.post_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=load_content,
        )
        if post is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")
        return post

    async def _write_post_version(
        self,
        session: SessionType,
        *,
        post: Post,
        workspace_id: uuid.UUID,
        snapshot: AutosaveSnapshot,
        content_text: str,
        content_hash: str,
        content_json_compressed: bytes,
    ) -> None:
        """Append a row to ``post_versions`` reflecting this flush.

        Implements FR-001 (every persist creates a version), FR-004
        (skip when content and title are unchanged vs. the previous
        version), and FR-007 (mark ``is_published_snapshot`` on the
        version row where the post's ``status`` transitions into
        ``published``).
        """
        previous = await self.content_writer.find_latest_version(session, post=post)
        if previous is not None and previous.content_hash == content_hash and previous.title == post.title:
            return

        is_publish_transition = post.status == PostStatus.PUBLISHED.value and (
            previous is None or previous.status_at_save != PostStatus.PUBLISHED.value
        )

        await self.content_writer.persist_snapshot(
            session,
            post=post,
            workspace_id=workspace_id,
            content_text=content_text,
            content_hash=content_hash,
            content_json_compressed=content_json_compressed,
            created_by=snapshot.author_id,
            is_published_snapshot=is_publish_transition,
            status_at_save=post.status,
        )
