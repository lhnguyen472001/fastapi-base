"""Autosave / flush / merged-read mixin for :class:`PostService`."""

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
from apps.blog.models import Post, PostContent
from apps.blog.repositories import (
    PostContentRepository,
    PostRepository,
    PostVersionRepository,
)
from apps.blog.schemas import PostDetailResponse
from apps.blog.store import AutosaveSnapshot, AutosaveStore
from apps.blog.utils import compress_content_json, compute_content_artifacts
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.redis import CacheManager
from apps.core.tiptap import extract_text, render_html, sanitize_html


class _PostAutosaveMixin:
    """Mixin: autosave / flush_one / get_for_admin behaviour for :class:`PostService`.

    The host class must provide ``find_or_raise``, ``_build_detail``,
    ``_invalidate_workspace_cache``, and ``_reload`` — these are resolved
    at runtime through MRO from :class:`PostService` itself.
    """

    repository: PostRepository
    content_repository: PostContentRepository
    post_version_repository: PostVersionRepository
    cache: CacheManager
    autosave_store: AutosaveStore

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

        # Lean projection — autosave only needs (workspace_id, status,
        # content_hash). Avoids the selectinload(category, tags) round-
        # trips that find_or_raise / find_by_id pay for on every keystroke.
        state = await self.repository.find_autosave_state(
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

        Idempotent: returns ``None`` when there is nothing to flush
        (no snapshot, hash already flushed, or the per-post lock is held
        by another worker). On success returns the reloaded post.

        The full Tiptap pipeline (text + html + sanitize) runs here, not
        on every autosave, so we pay it once per flush regardless of how
        many keystrokes coalesced.
        """
        if not self.autosave_store.enabled:
            return None

        async with self.autosave_store.acquire_flush_lock(post_id) as got_lock:
            if not got_lock:
                return None

            snapshot = await self.autosave_store.get(post_id)
            if snapshot is None or not snapshot.is_dirty:
                return None
            if snapshot.workspace_id != workspace_id:
                # Defensive: never flush across workspaces; treat as no-op.
                logger.warning(
                    "PostService - flush_one - workspace mismatch; skipping",
                    expected=str(workspace_id),
                    got=str(snapshot.workspace_id),
                    post_id=str(post_id),
                )
                return None

            post = await self.find_or_raise(
                session,
                workspace_id=workspace_id,
                post_id=post_id,
                load_content=True,
            )

            content_text, content_html, content_hash, word_count, reading_minutes = compute_content_artifacts(
                snapshot.content_json,
            )

            # Cross-check: snapshot.content_hash must equal the recomputed
            # hash, otherwise something corrupted the JSON in Redis.
            if content_hash != snapshot.content_hash:
                logger.warning(
                    "PostService - flush_one - hash drift between Redis snapshot and recompute",
                    snapshot=snapshot.content_hash,
                    recomputed=content_hash,
                    post_id=str(post_id),
                )

            existing_content = post.content
            if existing_content is None:
                await self.content_repository.add(
                    session,
                    PostContent(
                        post_id=post.id,
                        content_json=snapshot.content_json,
                        content_html=content_html,
                        content_text=content_text,
                    ),
                    expunge=False,
                )
            else:
                await self.content_repository.update(
                    session,
                    item_id=existing_content.id,
                    data={
                        "content_json": snapshot.content_json,
                        "content_html": content_html,
                        "content_text": content_text,
                    },
                )

            await self.repository.update(
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
            )

            await self.autosave_store.mark_flushed(post_id, content_hash=content_hash)
            await self._invalidate_workspace_cache(workspace_id)
            return await self._reload(session, workspace_id=workspace_id, post_id=post_id)

    async def _write_post_version(
        self,
        session: SessionType,
        *,
        post: Post,
        workspace_id: uuid.UUID,
        snapshot: AutosaveSnapshot,
        content_text: str,
        content_hash: str,
    ) -> None:
        """Append a row to ``post_versions`` reflecting this flush.

        Implements FR-001 (every persist creates a version), FR-004
        (skip when content and title are unchanged vs. the previous
        version), and FR-007 (mark ``is_published_snapshot`` on the
        version row where the post's ``status`` transitions into
        ``published``).
        """
        previous = await self.post_version_repository.find_latest_for_post(
            session,
            post_id=post.id,
        )
        if (
            previous is not None
            and previous.content_hash == content_hash
            and previous.title == post.title
        ):
            return

        is_publish_transition = post.status == PostStatus.PUBLISHED.value and (
            previous is None or previous.status_at_save != PostStatus.PUBLISHED.value
        )

        await self.post_version_repository.add_with_retry(
            session,
            data={
                "post_id": post.id,
                "workspace_id": workspace_id,
                "title": post.title,
                "content_json_compressed": compress_content_json(snapshot.content_json),
                "content_text": content_text,
                "content_hash": content_hash,
                "created_by": snapshot.author_id,
                "change_note": None,
                "is_published_snapshot": is_publish_transition,
                "is_restored": False,
                "status_at_save": post.status,
            },
        )

    async def get_for_admin(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> PostDetailResponse:
        """Admin-side detail read that merges any unflushed autosave snapshot.

        Editors should always see their latest in-Redis keystrokes when
        they reopen the editor; otherwise a tab refresh would jump back
        to the last flushed state.
        """
        post = await self.find_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        detail = self._build_detail(post)

        if not self.autosave_store.enabled:
            return detail

        snapshot = await self.autosave_store.get(post_id)
        if snapshot is None or not snapshot.is_dirty:
            return detail
        if snapshot.workspace_id != workspace_id:
            return detail

        # Override body fields with the dirty snapshot. We re-run the
        # cheap text extract + html render so the editor still gets a
        # consistent payload (clients sometimes display content_html
        # rather than re-rendering content_json themselves).
        content_text = extract_text(snapshot.content_json)
        content_html = sanitize_html(render_html(snapshot.content_json))
        return detail.model_copy(
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
