"""Content + version-row writer for posts.

Consolidates the three call sites that used to build a
``post_version_repository.add_with_retry(...)`` payload by hand
(:meth:`PostService.create`, :meth:`PostService.publish`, and the
autosave mixin's :meth:`flush_one` + :meth:`_write_post_version`) plus
the content-row insert/update branch in autosave-flush. Centralising
both makes the "what shape does a version-row write take" contract
greppable in one file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.blog.models import PostContent
from apps.blog.repositories import PostContentRepository, PostVersionRepository
from apps.blog.utils import (
    compress_content_json_async,
    compute_content_artifacts_async,
)
from apps.core.database.types import SessionType

if TYPE_CHECKING:
    from apps.blog.models import Post


@dataclass(frozen=True)
class ContentArtifacts:
    """Pre-computed Tiptap pipeline output for a content_json document."""

    content_text: str
    content_html: str
    content_hash: str
    word_count: int
    reading_minutes: int


class PostContentWriterService:
    """Owns every write into ``post_contents`` and ``post_versions``."""

    def __init__(
        self,
        content_repository: PostContentRepository,
        post_version_repository: PostVersionRepository,
    ) -> None:
        self.content_repository = content_repository
        self.post_version_repository = post_version_repository

    async def compute_artifacts(self, content_json: dict[str, Any]) -> ContentArtifacts:
        """Run the full Tiptap pipeline; pure CPU work behind a thread."""
        text, html, content_hash, words, minutes = await compute_content_artifacts_async(content_json)
        return ContentArtifacts(
            content_text=text,
            content_html=html,
            content_hash=content_hash,
            word_count=words,
            reading_minutes=minutes,
        )

    async def write_initial(
        self,
        session: SessionType,
        *,
        post: Post,
        content_json: dict[str, Any],
        artifacts: ContentArtifacts,
        workspace_id: uuid.UUID,
        author_id: uuid.UUID,
    ) -> None:
        """Insert the first ``post_contents`` row and the initial draft snapshot.

        Caller has already persisted the ``Post`` row (so we can FK to
        it) and has the artifacts in hand — passing them in avoids
        recomputing the Tiptap pipeline.
        """
        await self.content_repository.add(
            session,
            PostContent(
                post_id=post.id,
                content_json=content_json,
                content_html=artifacts.content_html,
                content_text=artifacts.content_text,
            ),
            expunge=False,
        )
        await self.post_version_repository.add_with_retry(
            session,
            data={
                "post_id": post.id,
                "workspace_id": workspace_id,
                "title": post.title,
                "content_json_compressed": await compress_content_json_async(content_json),
                "content_text": artifacts.content_text,
                "content_hash": artifacts.content_hash,
                "created_by": author_id,
                "change_note": None,
                "is_published_snapshot": False,
                "is_restored": False,
                "status_at_save": post.status,
            },
        )

    async def update_content_if_changed(
        self,
        session: SessionType,
        *,
        post: Post,
        new_content_json: dict[str, Any],
    ) -> ContentArtifacts | None:
        """Compute artifacts for ``new_content_json``; persist if hash changed.

        Returns the computed :class:`ContentArtifacts` when the content
        actually changed (so :meth:`PostService.update` can patch
        ``content_hash`` / ``word_count`` / ``reading_minutes`` on the
        post in the same transaction), or ``None`` when the hash matches
        the post's current ``content_hash`` (skip the rewrite).
        """
        artifacts = await self.compute_artifacts(new_content_json)
        if artifacts.content_hash == post.content_hash:
            return None
        existing_content = post.content
        if existing_content is None:
            await self.content_repository.add(
                session,
                PostContent(
                    post_id=post.id,
                    content_json=new_content_json,
                    content_html=artifacts.content_html,
                    content_text=artifacts.content_text,
                ),
                expunge=False,
            )
        else:
            await self.content_repository.update(
                session,
                item_id=existing_content.id,
                data={
                    "content_json": new_content_json,
                    "content_html": artifacts.content_html,
                    "content_text": artifacts.content_text,
                },
            )
        return artifacts

    async def upsert_content_for_flush(
        self,
        session: SessionType,
        *,
        post: Post,
        snapshot_content_json: dict[str, Any],
        content_html: str,
        content_text: str,
    ) -> None:
        """Autosave-flush variant: caller pre-computed html/text outside the lock.

        Branches the same way as :meth:`update_content_if_changed` —
        ``post.content is None`` → INSERT, else UPDATE — but takes the
        already-computed html/text instead of recomputing, since the
        autosave-flush path runs the Tiptap pipeline outside the
        per-post flush lock (F-PERF-4).
        """
        existing_content = post.content
        if existing_content is None:
            await self.content_repository.add(
                session,
                PostContent(
                    post_id=post.id,
                    content_json=snapshot_content_json,
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
                    "content_json": snapshot_content_json,
                    "content_html": content_html,
                    "content_text": content_text,
                },
            )

    async def persist_snapshot(
        self,
        session: SessionType,
        *,
        post: Post,
        workspace_id: uuid.UUID,
        content_text: str,
        content_hash: str,
        content_json_compressed: bytes,
        created_by: uuid.UUID,
        is_published_snapshot: bool,
        status_at_save: str,
        change_note: str | None = None,
        is_restored: bool = False,
    ) -> None:
        """Insert one row into ``post_versions`` (with the retry shim).

        Used by :meth:`PostService.publish` (publish-transition snapshot,
        ``is_published_snapshot=True``) and by the autosave mixin's
        :meth:`_write_post_version` (every flush; ``is_published_snapshot``
        flips True on the draft→published transition).
        """
        await self.post_version_repository.add_with_retry(
            session,
            data={
                "post_id": post.id,
                "workspace_id": workspace_id,
                "title": post.title,
                "content_json_compressed": content_json_compressed,
                "content_text": content_text,
                "content_hash": content_hash,
                "created_by": created_by,
                "change_note": change_note,
                "is_published_snapshot": is_published_snapshot,
                "is_restored": is_restored,
                "status_at_save": status_at_save,
            },
        )

    async def find_latest_version(self, session: SessionType, *, post: Post) -> Any | None:
        """Forward to :meth:`PostVersionRepository.find_latest_for_post`.

        Used by the autosave mixin to short-circuit the FR-004 "skip if
        unchanged vs previous version" branch.
        """
        return await self.post_version_repository.find_latest_for_post(
            session,
            post_id=post.id,
        )
