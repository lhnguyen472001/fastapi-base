"""Post version history service — list / get / restore / compare.

Method bodies for the four user-story endpoints (US1-US4) land across
Phases 3-6 of the implementation plan. Phase 2 ships this file as a
stub so the DI container can wire ``post_version_service`` and so
:func:`flush_one` (Phase 2 T012) can be implemented without forward
references.

The version-row INSERT path itself lives in
:class:`apps.blog.services._autosave._PostAutosaveMixin.flush_one`,
calling :meth:`PostVersionRepository.add_with_retry` directly. The
service object here is for the user-facing endpoints, not the create
side.
"""

from __future__ import annotations

import uuid

from apps.blog.constants import POST_VERSION_DIFF_MAX_BYTES
from apps.blog.exceptions import (
    PostNotFoundError,
    PostVersionMismatchError,
    PostVersionNotFoundError,
)
from apps.blog.models import Post, PostContent, PostVersion
from apps.blog.repositories import (
    PostContentRepository,
    PostRepository,
    PostVersionRepository,
)
from apps.blog.schemas import (
    CompareVersionsResult,
    PostVersionAuthor,
    PostVersionDetailResponse,
    PostVersionResponse,
    RestoreVersionResult,
)
from apps.blog.utils import (
    compress_content_json,
    compute_content_artifacts,
    decompress_content_json,
    diff_versions,
)
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.schemas.response import PaginatedResponse
from apps.user.models import User
from apps.user.repositories import UserRepository


class PostVersionService:
    """Business logic for the four post-version endpoints.

    The version-row INSERT path itself runs inside
    :meth:`PostService.flush_one` /
    :meth:`PostService.create` / :meth:`PostService.publish`. This
    service is read-and-restore only — it never writes a version row
    that wasn't asked for by an endpoint.
    """

    def __init__(
        self,
        repository: PostVersionRepository,
        post_repository: PostRepository,
        post_content_repository: PostContentRepository,
        user_repository: UserRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository
        self.post_content_repository = post_content_repository
        self.user_repository = user_repository

    async def list_for_post(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> PaginatedResponse[PostVersionResponse]:
        """Paginated newest-first list of versions for ``post_id``.

        Verifies the post exists in ``workspace_id`` before listing so
        callers outside the workspace get the same ``PostNotFoundError``
        shape they would get from :meth:`PostService.find_or_raise`.
        Hydrates ``created_by`` with a single batch query over the
        distinct author ids on the page.
        """
        await self._ensure_post_visible(session, workspace_id=workspace_id, post_id=post_id)

        rows, total = await self.repository.list_for_post(
            session,
            post_id=post_id,
            limit=limit,
            offset=offset,
        )
        author_map = await self._hydrate_authors(session, rows=rows)

        items = [self._to_response(row, author_map=author_map) for row in rows]
        return PaginatedResponse[PostVersionResponse](
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_for_post(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        version: int,
    ) -> PostVersionDetailResponse:
        """Return full historical content of one version.

        Decompression failures surface as
        :class:`PostVersionContentUnreadableError` (POSTV004 / 500) — a
        corrupt stored row is operational corruption, not a user error.
        Missing (post, version) pairs raise
        :class:`PostVersionNotFoundError` (POSTV001 / 404).
        """
        await self._ensure_post_visible(session, workspace_id=workspace_id, post_id=post_id)

        row = await self.repository.find_by_post_and_version(
            session,
            post_id=post_id,
            version=version,
        )
        if row is None:
            raise PostVersionNotFoundError(
                message=f"Version {version} not found for post '{post_id}'.",
            )

        content_json = self._decompress_or_raise(row)
        author_map = await self._hydrate_authors(session, rows=[row])
        return self._to_detail_response(row, content_json=content_json, author_map=author_map)

    @transactional
    async def restore(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        version: int,
        actor_id: uuid.UUID,
        change_note: str | None = None,
    ) -> RestoreVersionResult:
        """Restore a historical version as the post's current working copy.

        Replaces the ``posts`` + ``post_contents`` body with the chosen
        version's content, then appends a new version row reflecting the
        restored state so the restore itself is reversible
        (FR-005, FR-013). Does NOT change ``status`` / ``published_at``
        (FR-014) — restoring a draft-era body on a published post leaves
        the post published.

        Raises:
            PostNotFoundError: post is outside ``workspace_id`` or missing.
            PostVersionNotFoundError: no row with the given ``version``.
            PostVersionContentUnreadableError: stored payload is corrupt.
        """
        post = await self._load_post_or_raise(session, workspace_id=workspace_id, post_id=post_id)
        source = await self.repository.find_by_post_and_version(
            session,
            post_id=post_id,
            version=version,
        )
        if source is None:
            raise PostVersionNotFoundError(
                message=f"Version {version} not found for post '{post_id}'.",
            )

        content_json = self._decompress_or_raise(source)
        content_text, content_html, content_hash, word_count, reading_minutes = compute_content_artifacts(
            content_json,
        )

        await self._apply_restored_body(
            session,
            post=post,
            title=source.title,
            content_json=content_json,
            content_text=content_text,
            content_html=content_html,
            content_hash=content_hash,
            word_count=word_count,
            reading_minutes=reading_minutes,
        )

        new_row = await self.repository.add_with_retry(
            session,
            data={
                "post_id": post.id,
                "workspace_id": workspace_id,
                "title": source.title,
                "content_json_compressed": compress_content_json(content_json),
                "content_text": content_text,
                "content_hash": content_hash,
                "created_by": actor_id,
                "change_note": change_note or f"Restored from version {version}",
                "is_published_snapshot": False,
                "is_restored": True,
                "status_at_save": post.status,
            },
        )

        author_map = await self._hydrate_authors(session, rows=[new_row])
        return RestoreVersionResult(
            post_id=post.id,
            restored_from_version=version,
            new_version=self._to_response(new_row, author_map=author_map),
        )

    async def compare(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        from_version: int,
        to_version: int,
    ) -> CompareVersionsResult:
        """Diff two versions of the same post.

        Both ``from_version`` and ``to_version`` MUST belong to
        ``post_id``; cross-post or self-self requests raise
        :class:`PostVersionMismatchError` (POSTV002 / 422). Either
        version missing raises :class:`PostVersionNotFoundError`
        (POSTV001 / 404). Combined plaintext exceeding
        :data:`POST_VERSION_DIFF_MAX_BYTES` raises
        :class:`PostVersionDiffTooLargeError` (POSTV005 / 413).
        """
        if from_version == to_version:
            raise PostVersionMismatchError(
                message="from_version and to_version must differ.",
            )

        await self._ensure_post_visible(session, workspace_id=workspace_id, post_id=post_id)

        pair = await self.repository.find_pair_for_compare(
            session,
            post_id=post_id,
            versions=(from_version, to_version),
        )
        try:
            source = pair[from_version]
            target = pair[to_version]
        except KeyError as exc:
            missing = [v for v in (from_version, to_version) if v not in pair]
            raise PostVersionNotFoundError(
                message=f"Versions {missing} not found for post '{post_id}'.",
            ) from exc

        return diff_versions(
            post_id=post_id,
            from_version=from_version,
            from_title=source.title,
            from_text=source.content_text,
            to_version=to_version,
            to_title=target.title,
            to_text=target.content_text,
            max_bytes=POST_VERSION_DIFF_MAX_BYTES,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _ensure_post_visible(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> None:
        """Authz seam: the post must exist in this workspace, else 404.

        Mirrors :meth:`PostService.find_or_raise`'s error shape so a
        caller outside the workspace sees the same response as a caller
        asking for a non-existent post — never leaks existence.
        """
        post = await self.post_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )
        if post is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")

    async def _load_post_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        """Like :meth:`_ensure_post_visible` but returns the eager-loaded post.

        Used by :meth:`restore` so we can rewrite the 1:1 content row
        without paying for a second SELECT.
        """
        post = await self.post_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        if post is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")
        return post

    async def _apply_restored_body(
        self,
        session: SessionType,
        *,
        post: Post,
        title: str,
        content_json: dict,
        content_text: str,
        content_html: str,
        content_hash: str,
        word_count: int,
        reading_minutes: int,
    ) -> None:
        """Overwrite the post's working copy in place.

        Touches only the title + content fields and the derived metadata
        (hash, word_count, reading_minutes). Status / published_at /
        category / tags are intentionally untouched per FR-014.
        """
        existing_content = post.content
        if existing_content is None:
            await self.post_content_repository.add(
                session,
                PostContent(
                    post_id=post.id,
                    content_json=content_json,
                    content_html=content_html,
                    content_text=content_text,
                ),
                expunge=False,
            )
        else:
            await self.post_content_repository.update(
                session,
                item_id=existing_content.id,
                data={
                    "content_json": content_json,
                    "content_html": content_html,
                    "content_text": content_text,
                },
            )

        await self.post_repository.update(
            session,
            item_id=post.id,
            data={
                "title": title,
                "content_hash": content_hash,
                "word_count": word_count,
                "reading_minutes": reading_minutes,
            },
        )

    async def _hydrate_authors(
        self,
        session: SessionType,
        *,
        rows: list[PostVersion],
    ) -> dict[uuid.UUID, User]:
        """Single-query batch load of every distinct ``created_by`` id."""
        if not rows:
            return {}
        distinct_ids = list({row.created_by for row in rows})
        users = await self.user_repository.find_by_ids(
            session,
            user_ids=distinct_ids,
            include_deleted=True,
        )
        return {user.id: user for user in users}

    @staticmethod
    def _to_response(
        row: PostVersion,
        *,
        author_map: dict[uuid.UUID, User],
    ) -> PostVersionResponse:
        """Convert one ORM row to its metadata response shape."""
        return PostVersionResponse(
            post_id=row.post_id,
            version=row.version,
            title=row.title,
            content_hash=row.content_hash,
            change_note=row.change_note,
            is_published_snapshot=row.is_published_snapshot,
            is_restored=row.is_restored,
            status_at_save=row.status_at_save,
            created_at=row.created_at,
            created_by=_author_or_placeholder(row.created_by, author_map),
        )

    @staticmethod
    def _to_detail_response(
        row: PostVersion,
        *,
        content_json: dict,
        author_map: dict[uuid.UUID, User],
    ) -> PostVersionDetailResponse:
        """Convert one ORM row plus its decompressed body into the detail shape."""
        return PostVersionDetailResponse(
            post_id=row.post_id,
            version=row.version,
            title=row.title,
            content_hash=row.content_hash,
            change_note=row.change_note,
            is_published_snapshot=row.is_published_snapshot,
            is_restored=row.is_restored,
            status_at_save=row.status_at_save,
            created_at=row.created_at,
            created_by=_author_or_placeholder(row.created_by, author_map),
            content_json=content_json,
            content_text=row.content_text,
        )

    @staticmethod
    def _decompress_or_raise(row: PostVersion) -> dict:
        """Decompress ``row.content_json_compressed`` with a typed failure mode.

        Thin pass-through to :func:`decompress_content_json` so callers
        can swap implementations without importing the codec helper.
        Decode failures surface as
        :class:`PostVersionContentUnreadableError` (POSTV004 / 500).
        """
        return decompress_content_json(bytes(row.content_json_compressed))


def _author_or_placeholder(
    user_id: uuid.UUID,
    author_map: dict[uuid.UUID, User],
) -> PostVersionAuthor:
    """Lookup the author row; fall back to a synthetic stub if the user is gone.

    Versions outlive users (``created_by`` is RESTRICT, but soft-deleted
    users still appear here). The placeholder keeps the response shape
    stable for the editor instead of erroring on a dangling reference.
    """
    user = author_map.get(user_id)
    if user is None:
        return PostVersionAuthor(id=user_id, username="(deleted)", display_name=None)
    return PostVersionAuthor(id=user.id, username=user.username, display_name=None)
