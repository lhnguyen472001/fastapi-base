"""Per-workspace post service: CRUD, status transitions, cached read.

Autosave / flush / merged-read live on
:class:`apps.blog.services._autosave_service.PostAutosaveService`; this
service holds a thin facade to that collaborator so route call-sites
keep their existing ``post_service.autosave(...)`` etc. shape.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from apps.blog.constants import EMPTY_TIPTAP_DOC
from apps.blog.enums import PostStatus
from apps.blog.exceptions import (
    PostInvalidStatusTransitionError,
    PostNotFoundError,
)
from apps.blog.models import Post
from apps.blog.repositories import (
    PostRepository,
    PostTagRepository,
)
from apps.blog.schemas import (
    CreatePostRequest,
    ListPostsRequest,
    PostDetailResponse,
    UpdatePostRequest,
)
from apps.blog.services._autosave_service import PostAutosaveService
from apps.blog.services._cache import PostCacheService
from apps.blog.services._content_writer import PostContentWriterService
from apps.blog.services._detail import build_post_detail
from apps.blog.services._validation import PostValidationService
from apps.blog.utils import (
    compress_content_json_async,
    ensure_publish_ready,
    normalize_slug,
)
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.database.utils import slugify
from apps.core.services.base import BaseSQLAlchemyService


class PostService(BaseSQLAlchemyService[Post]):
    """Per-workspace post CRUD plus the Tiptap content pipeline."""

    repository: PostRepository

    def __init__(
        self,
        repository: PostRepository,
        post_tag_repository: PostTagRepository,
        validation_service: PostValidationService,
        content_writer: PostContentWriterService,
        cache_service: PostCacheService,
        autosave_service: PostAutosaveService,
    ) -> None:
        super().__init__(repository)
        self.post_tag_repository = post_tag_repository
        self.validation_service = validation_service
        self.content_writer = content_writer
        self.cache_service = cache_service
        self.autosave_service = autosave_service

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    @transactional
    async def create(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        author_id: uuid.UUID,
        data: CreatePostRequest,
    ) -> Post:
        """Create a draft post, its content row, and the first version snapshot.

        Multi-statement write wrapped in ``@transactional``: the post,
        ``post_contents`` row, optional tag links, and the initial
        ``post_versions`` snapshot all commit atomically. Computes
        ``content_html`` / ``content_text`` / ``content_hash`` / word
        count / reading minutes from the Tiptap doc at this point so the
        list-published query can paginate without re-rendering.

        Args:
            session: Active async session.
            workspace_id: Owning workspace.
            author_id: Authoring user.
            data: Validated request body.

        Returns:
            The persisted :class:`Post` (re-fetched with category + tags loaded).

        Raises:
            PostSlugConflictError: Slug already in use within the workspace.
            PostCategoryNotFoundError: ``data.category_id`` does not exist.
            PostTagsNotFoundError: One or more ``data.tag_ids`` do not exist.
            PostTooManyTagsError: ``data.tag_ids`` exceeds ``MAX_TAGS_PER_POST``.
        """
        slug = normalize_slug(data.slug or slugify(data.title))
        await self.validation_service.ensure_slug_available(
            session, workspace_id=workspace_id, slug=slug,
        )

        if data.category_id is not None:
            await self.validation_service.validate_category(
                session, workspace_id=workspace_id, category_id=data.category_id,
            )
        self.validation_service.enforce_tag_count(data.tag_ids)
        if data.tag_ids:
            await self.validation_service.validate_tags(
                session, workspace_id=workspace_id, tag_ids=data.tag_ids,
            )

        content_json = data.content_json or dict(EMPTY_TIPTAP_DOC)
        artifacts = await self.content_writer.compute_artifacts(content_json)

        post = Post(
            workspace_id=workspace_id,
            author_id=author_id,
            category_id=data.category_id,
            title=data.title,
            slug=slug,
            excerpt=data.excerpt,
            cover_image_url=data.cover_image_url,
            status=PostStatus.DRAFT.value,
            published_at=None,
            reading_minutes=artifacts.reading_minutes,
            word_count=artifacts.word_count,
            hero_quote=data.hero_quote.model_dump(mode="json") if data.hero_quote is not None else None,
            meta_title=data.meta_title,
            meta_description=data.meta_description,
            content_hash=artifacts.content_hash,
        )
        post = await self.repository.add(session, post, expunge=False)

        await self.content_writer.write_initial(
            session,
            post=post,
            content_json=content_json,
            artifacts=artifacts,
            workspace_id=workspace_id,
            author_id=author_id,
        )

        if data.tag_ids:
            await self.post_tag_repository.replace_post_tags(
                session,
                post_id=post.id,
                tag_ids=data.tag_ids,
            )

        return await self._reload(session, workspace_id=workspace_id, post_id=post.id)

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    async def find_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        load_content: bool = False,
    ) -> Post:
        """Fetch a post by id within ``workspace_id`` or raise :class:`PostNotFoundError`.

        Args:
            session: Active async session.
            workspace_id: Workspace scope (cross-workspace lookups go through
                :meth:`PostRepository.find_by_id_any_workspace` and the
                RBAC-gated moderation paths).
            post_id: Post id.
            load_content: When True, eager-loads the ``post_contents`` row
                via ``selectinload`` — pay for it only when the caller will
                read ``post.content``.

        Returns:
            The hydrated :class:`Post`.

        Raises:
            PostNotFoundError: No row matches in this workspace.
        """
        post = await self.repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=load_content,
        )
        if post is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")
        return post

    async def get_published_by_slug(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
    ) -> Post:
        """Return the published post for ``slug`` with content eagerly loaded.

        Used by the public reader path. Soft-deleted and non-published
        posts are excluded so unpublishing a post hides it immediately
        from the public surface.

        Args:
            session: Active async session.
            workspace_id: Owning workspace.
            slug: URL slug.

        Returns:
            The published :class:`Post` (with ``post.content`` populated).

        Raises:
            PostNotFoundError: No published row matches the slug.
        """
        post = await self.repository.find_by_slug(
            session,
            workspace_id=workspace_id,
            slug=slug,
            status=PostStatus.PUBLISHED,
            load_content=True,
        )
        if post is None:
            raise PostNotFoundError(message=f"Published post '{slug}' not found.")
        return post

    async def get_published_detail_by_slug(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
    ) -> PostDetailResponse:
        """Read-through cache for the public detail response."""
        cached = await self.cache_service.get_detail(workspace_id, slug)
        if cached is not None:
            return PostDetailResponse.model_validate(cached)

        post = await self.get_published_by_slug(session, workspace_id=workspace_id, slug=slug)
        detail = build_post_detail(post)
        await self.cache_service.put_detail(workspace_id, slug, detail.model_dump(mode="json"))
        return detail

    async def list_posts(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        params: ListPostsRequest,
    ) -> tuple[list[Post], int]:
        """Workspace-scoped, paginated post list with optional filters.

        Hits the composite ``ix_posts_workspace_status_published_at``
        index when ``status`` is constrained. Returns the same shape used
        by the admin list endpoint.

        Args:
            session: Active async session.
            workspace_id: Owning workspace.
            params: Filter + pagination payload (``status``,
                ``category_id``, ``tag_id``, ``search``, ``limit``,
                ``offset``).

        Returns:
            ``(rows, total)`` where ``total`` is the count under the
            same filter (independent of ``limit`` / ``offset``).
        """
        return await self.repository.list_for_workspace(
            session,
            workspace_id=workspace_id,
            status=params.status,
            category_id=params.category_id,
            tag_id=params.tag_id,
            search=params.search,
            limit=params.limit,
            offset=params.offset,
        )

    # ------------------------------------------------------------------
    # update / status transitions
    # ------------------------------------------------------------------

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        data: UpdatePostRequest,
    ) -> Post:
        """Apply a partial update to a post; the authoritative save path.

        Multi-statement write wrapped in ``@transactional``. Normalises
        the slug, validates category / tags / hero-quote, recomputes
        content artifacts (and skips the rewrite when ``content_hash``
        hasn't changed), persists tag links, then discards any pending
        autosave and invalidates the workspace cache — PATCH is the
        canonical save, so a stale Redis autosave from before the PATCH
        must not overwrite the commit on the next sweeper tick.

        Args:
            session: Active async session.
            workspace_id: Owning workspace.
            post_id: Post id.
            data: Validated partial-update payload (``exclude_unset``
                semantics).

        Returns:
            The reloaded :class:`Post` with category + tags + content
            populated.

        Raises:
            PostNotFoundError: ``post_id`` not in this workspace.
            PostSlugConflictError: New slug collides with another post.
            PostCategoryNotFoundError / PostTagsNotFoundError /
                PostTooManyTagsError: validation failures on the
                respective fields.
        """
        post = await self.find_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        payload = data.model_dump(exclude_unset=True)
        new_tag_ids = await self._resolve_update_payload(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            data=data,
            payload=payload,
        )
        await self._apply_content_change(session, post=post, payload=payload)

        if payload:
            await self.repository.update(session, item_id=post_id, data=payload)

        if new_tag_ids is not None:
            await self.post_tag_repository.replace_post_tags(
                session,
                post_id=post.id,
                tag_ids=new_tag_ids,
            )

        reloaded = await self._reload(session, workspace_id=workspace_id, post_id=post.id)
        # PATCH is the authoritative save: discard any pending autosave so
        # we don't overwrite this commit with stale Redis state on the next sweeper tick.
        await self.autosave_service.autosave_store.discard(post_id)
        await self.cache_service.invalidate_workspace(workspace_id)
        # MED-2: drop every cached render for this post so the next fetch
        # re-renders from the new authoritative content_hash immediately
        # rather than serving a stale entry until POST_RENDER_CACHE_TTL_SECONDS.
        await self.cache_service.invalidate_render(post.id)
        return reloaded

    async def _resolve_update_payload(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        data: UpdatePostRequest,
        payload: dict,
    ) -> Sequence[uuid.UUID] | None:
        """Validate slug/category/tags and normalize ``payload`` in place.

        Returns the normalized tag-id list when ``tag_ids`` was supplied
        (popped from ``payload``), or ``None`` when tags should be left untouched.
        """
        if "slug" in payload and payload["slug"] is not None:
            new_slug = normalize_slug(payload["slug"])
            await self.validation_service.ensure_slug_available(
                session,
                workspace_id=workspace_id,
                slug=new_slug,
                exclude_id=post_id,
            )
            payload["slug"] = new_slug

        if "category_id" in payload and payload["category_id"] is not None:
            await self.validation_service.validate_category(
                session,
                workspace_id=workspace_id,
                category_id=payload["category_id"],
            )

        new_tag_ids: list[uuid.UUID] | None = payload.pop("tag_ids", None)
        if new_tag_ids is not None:
            self.validation_service.enforce_tag_count(new_tag_ids)
            if new_tag_ids:
                await self.validation_service.validate_tags(
                    session,
                    workspace_id=workspace_id,
                    tag_ids=new_tag_ids,
                )

        if "hero_quote" in payload and payload["hero_quote"] is not None:
            payload["hero_quote"] = data.hero_quote.model_dump(mode="json") if data.hero_quote else None

        return new_tag_ids

    async def _apply_content_change(
        self,
        session: SessionType,
        *,
        post: Post,
        payload: dict,
    ) -> None:
        """If ``payload`` carries new content_json, recompute artifacts and persist."""
        new_content = payload.pop("content_json", None)
        if new_content is None:
            return
        artifacts = await self.content_writer.update_content_if_changed(
            session,
            post=post,
            new_content_json=new_content,
        )
        if artifacts is None:
            return
        payload["content_hash"] = artifacts.content_hash
        payload["word_count"] = artifacts.word_count
        payload["reading_minutes"] = artifacts.reading_minutes

    @transactional
    async def publish(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        # Flush any pending autosave first so the published version
        # reflects the most recent keystrokes the editor saw.
        await self.autosave_service.flush_one(session, workspace_id=workspace_id, post_id=post_id)

        post = await self.find_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        if post.status not in {PostStatus.DRAFT.value, PostStatus.ARCHIVED.value}:
            raise PostInvalidStatusTransitionError(
                message=f"Cannot publish from status '{post.status}'.",
            )

        ensure_publish_ready(post)
        await self.repository.update(
            session,
            item_id=post_id,
            data={
                "status": PostStatus.PUBLISHED.value,
                "published_at": datetime.datetime.now(datetime.UTC),
            },
        )

        # FR-007: the transition into published produces a retention-exempt
        # snapshot row. The preceding ``flush_one`` already wrote any
        # in-flight content changes; this row captures the same content
        # but with ``status_at_save=published`` so the retention sweeper
        # keeps it forever.
        if post.content is not None:
            await self.content_writer.persist_snapshot(
                session,
                post=post,
                workspace_id=workspace_id,
                content_text=post.content.content_text,
                content_hash=post.content_hash or "",
                content_json_compressed=await compress_content_json_async(post.content.content_json),
                created_by=post.author_id,
                is_published_snapshot=True,
                status_at_save=PostStatus.PUBLISHED.value,
            )

        reloaded = await self._reload(session, workspace_id=workspace_id, post_id=post_id)
        await self.cache_service.invalidate_workspace(workspace_id)
        return reloaded

    @transactional
    async def unpublish(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        post = await self.find_or_raise(session, workspace_id=workspace_id, post_id=post_id)
        if post.status != PostStatus.PUBLISHED.value:
            raise PostInvalidStatusTransitionError(
                message=f"Cannot unpublish from status '{post.status}'.",
            )
        await self.repository.update(
            session,
            item_id=post_id,
            data={"status": PostStatus.DRAFT.value, "published_at": None},
        )
        reloaded = await self._reload(session, workspace_id=workspace_id, post_id=post_id)
        await self.cache_service.invalidate_workspace(workspace_id)
        return reloaded

    @transactional
    async def archive(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        post = await self.find_or_raise(session, workspace_id=workspace_id, post_id=post_id)
        if post.status == PostStatus.ARCHIVED.value:
            return post
        await self.repository.update(
            session,
            item_id=post_id,
            data={"status": PostStatus.ARCHIVED.value},
        )
        reloaded = await self._reload(session, workspace_id=workspace_id, post_id=post_id)
        await self.cache_service.invalidate_workspace(workspace_id)
        return reloaded

    @transactional
    async def soft_delete(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        await self.find_or_raise(session, workspace_id=workspace_id, post_id=post_id)
        deleted = await self.repository.update(
            session,
            item_id=post_id,
            data={"deleted_at": datetime.datetime.now(datetime.UTC)},
        )
        if deleted is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found.")
        await self.cache_service.invalidate_workspace(workspace_id)
        return deleted

    # ------------------------------------------------------------------
    # autosave facades — delegate to :class:`PostAutosaveService` so the
    # route call-sites (``post_service.autosave(...)`` etc.) keep their
    # existing shape after Phase B.5 promoted the mixin to a service.
    # ------------------------------------------------------------------

    async def autosave(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
        author_id: uuid.UUID,
        content_json: dict[str, Any],
    ) -> tuple[str, int, int, datetime.datetime, bool]:
        """Forward to :meth:`PostAutosaveService.autosave`."""
        return await self.autosave_service.autosave(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            author_id=author_id,
            content_json=content_json,
        )

    async def flush_one(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post | None:
        """Forward to :meth:`PostAutosaveService.flush_one`."""
        return await self.autosave_service.flush_one(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
        )

    async def get_for_admin(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> PostDetailResponse:
        """Admin-side detail read; merges any unflushed autosave snapshot."""
        post = await self.find_or_raise(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        base_detail = build_post_detail(post)
        return await self.autosave_service.merge_dirty_snapshot_into_detail(
            workspace_id=workspace_id,
            post_id=post_id,
            base_detail=base_detail,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _reload(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        """Re-fetch the post with eager relations after a write."""
        reloaded = await self.repository.find_by_id(
            session,
            workspace_id=workspace_id,
            post_id=post_id,
            load_content=True,
        )
        if reloaded is None:
            raise PostNotFoundError(message=f"Post '{post_id}' not found after write.")
        return reloaded

