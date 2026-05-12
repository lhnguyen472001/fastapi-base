"""Per-workspace post service: CRUD, status transitions, cached read.

Autosave / flush_one / get_for_admin live on
:class:`apps.blog.services._autosave._PostAutosaveMixin` so the host class
stays under the per-class line budget.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence

from apps.blog.constants import (
    EMPTY_TIPTAP_DOC,
    MAX_TAGS_PER_POST,
    POST_CACHE_DETAIL_TTL,
    POST_CACHE_KEY_PREFIX,
)
from apps.blog.enums import PostStatus
from apps.blog.exceptions import (
    BlogResourceWorkspaceMismatchError,
    PostInvalidStatusTransitionError,
    PostNotFoundError,
    PostSlugConflictError,
    PostTooManyTagsError,
)
from apps.blog.models import Post, PostContent
from apps.blog.repositories import (
    CategoryRepository,
    PostContentRepository,
    PostRepository,
    PostTagRepository,
    PostVersionRepository,
    TagRepository,
)
from apps.blog.schemas import (
    CategoryResponse,
    CreatePostRequest,
    ListPostsRequest,
    PostDetailResponse,
    PostResponse,
    TagResponse,
    UpdatePostRequest,
)
from apps.blog.services._autosave import _PostAutosaveMixin
from apps.blog.store import AutosaveStore
from apps.blog.utils import (
    compress_content_json,
    compute_content_artifacts,
    ensure_publish_ready,
    normalize_slug,
)
from apps.core.database.transactional import transactional
from apps.core.database.types import SessionType
from apps.core.database.utils import slugify
from apps.core.redis import CacheManager
from apps.core.services.base import BaseSQLAlchemyService


class PostService(_PostAutosaveMixin, BaseSQLAlchemyService[Post]):
    """Per-workspace post CRUD plus the Tiptap content pipeline."""

    repository: PostRepository

    def __init__(
        self,
        repository: PostRepository,
        content_repository: PostContentRepository,
        post_tag_repository: PostTagRepository,
        category_repository: CategoryRepository,
        tag_repository: TagRepository,
        post_version_repository: PostVersionRepository,
        cache: CacheManager,
        autosave_store: AutosaveStore,
    ) -> None:
        super().__init__(repository)
        self.content_repository = content_repository
        self.post_tag_repository = post_tag_repository
        self.category_repository = category_repository
        self.tag_repository = tag_repository
        self.post_version_repository = post_version_repository
        self.cache = cache
        self.autosave_store = autosave_store

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
        slug = normalize_slug(data.slug or slugify(data.title))
        await self._ensure_slug_available(session, workspace_id=workspace_id, slug=slug)

        if data.category_id is not None:
            await self._validate_category(session, workspace_id=workspace_id, category_id=data.category_id)
        if len(data.tag_ids) > MAX_TAGS_PER_POST:
            raise PostTooManyTagsError(
                message=f"At most {MAX_TAGS_PER_POST} tags allowed per post.",
            )
        if data.tag_ids:
            await self._validate_tags(session, workspace_id=workspace_id, tag_ids=data.tag_ids)

        content_json = data.content_json or dict(EMPTY_TIPTAP_DOC)
        content_text, content_html, content_hash, word_count, reading_minutes = compute_content_artifacts(
            content_json,
        )

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
            reading_minutes=reading_minutes,
            word_count=word_count,
            hero_quote=data.hero_quote.model_dump(mode="json") if data.hero_quote is not None else None,
            meta_title=data.meta_title,
            meta_description=data.meta_description,
            content_hash=content_hash,
        )
        post = await self.repository.add(session, post, expunge=False)

        content_row = PostContent(
            post_id=post.id,
            content_json=content_json,
            content_html=content_html,
            content_text=content_text,
        )
        await self.content_repository.add(session, content_row, expunge=False)

        if data.tag_ids:
            await self.post_tag_repository.replace_post_tags(
                session,
                post_id=post.id,
                tag_ids=data.tag_ids,
            )

        await self.post_version_repository.add_with_retry(
            session,
            data={
                "post_id": post.id,
                "workspace_id": workspace_id,
                "title": post.title,
                "content_json_compressed": compress_content_json(content_json),
                "content_text": content_text,
                "content_hash": content_hash,
                "created_by": author_id,
                "change_note": None,
                "is_published_snapshot": False,
                "is_restored": False,
                "status_at_save": post.status,
            },
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
        cache_key = await self._cache_key_detail(workspace_id, slug)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return PostDetailResponse.model_validate(cached)

        post = await self.get_published_by_slug(session, workspace_id=workspace_id, slug=slug)
        detail = self._build_detail(post)
        await self.cache.set(cache_key, detail.model_dump(mode="json"), ttl=POST_CACHE_DETAIL_TTL)
        return detail

    async def list_posts(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        params: ListPostsRequest,
    ) -> tuple[list[Post], int]:
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
        await self.autosave_store.discard(post_id)
        await self._invalidate_workspace_cache(workspace_id)
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
            await self._ensure_slug_available(
                session,
                workspace_id=workspace_id,
                slug=new_slug,
                exclude_id=post_id,
            )
            payload["slug"] = new_slug

        if "category_id" in payload and payload["category_id"] is not None:
            await self._validate_category(
                session,
                workspace_id=workspace_id,
                category_id=payload["category_id"],
            )

        new_tag_ids: list[uuid.UUID] | None = payload.pop("tag_ids", None)
        if new_tag_ids is not None:
            if len(new_tag_ids) > MAX_TAGS_PER_POST:
                raise PostTooManyTagsError(
                    message=f"At most {MAX_TAGS_PER_POST} tags allowed per post.",
                )
            if new_tag_ids:
                await self._validate_tags(
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

        content_text, content_html, content_hash, word_count, reading_minutes = compute_content_artifacts(
            new_content,
        )
        if content_hash == post.content_hash:
            return

        payload["content_hash"] = content_hash
        payload["word_count"] = word_count
        payload["reading_minutes"] = reading_minutes

        existing_content = post.content
        if existing_content is None:
            await self.content_repository.add(
                session,
                PostContent(
                    post_id=post.id,
                    content_json=new_content,
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
                    "content_json": new_content,
                    "content_html": content_html,
                    "content_text": content_text,
                },
            )

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
        await self.flush_one(session, workspace_id=workspace_id, post_id=post_id)

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
            await self.post_version_repository.add_with_retry(
                session,
                data={
                    "post_id": post.id,
                    "workspace_id": workspace_id,
                    "title": post.title,
                    "content_json_compressed": compress_content_json(post.content.content_json),
                    "content_text": post.content.content_text,
                    "content_hash": post.content_hash or "",
                    "created_by": post.author_id,
                    "change_note": None,
                    "is_published_snapshot": True,
                    "is_restored": False,
                    "status_at_save": PostStatus.PUBLISHED.value,
                },
            )

        reloaded = await self._reload(session, workspace_id=workspace_id, post_id=post_id)
        await self._invalidate_workspace_cache(workspace_id)
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
        await self._invalidate_workspace_cache(workspace_id)
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
        await self._invalidate_workspace_cache(workspace_id)
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
        await self._invalidate_workspace_cache(workspace_id)
        return deleted

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _ensure_slug_available(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self.repository.find_by_slug(
            session,
            workspace_id=workspace_id,
            slug=slug,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise PostSlugConflictError(message=f"Post slug '{slug}' already exists.")

    async def _validate_category(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
    ) -> None:
        category = await self.category_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            category_id=category_id,
        )
        if category is None:
            raise BlogResourceWorkspaceMismatchError(
                message=f"Category '{category_id}' not found in this workspace.",
            )

    async def _validate_tags(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_ids: Sequence[uuid.UUID],
    ) -> None:
        found = await self.tag_repository.list_by_ids(
            session,
            workspace_id=workspace_id,
            tag_ids=tag_ids,
        )
        found_ids = {tag.id for tag in found}
        missing = [tid for tid in tag_ids if tid not in found_ids]
        if missing:
            raise BlogResourceWorkspaceMismatchError(
                message=f"Tags {missing} not found in this workspace.",
            )

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

    # ------------------------------------------------------------------
    # cache helpers (versioned-prefix invalidation)
    # ------------------------------------------------------------------
    #
    # Cached entries embed a per-workspace generation counter: every
    # invalidation is a single ``INCR`` on that counter, which orphans
    # every previously-cached key under the old prefix and lets them
    # expire via their existing TTL. Reads pay one extra ``GET`` to
    # resolve the current generation; writes drop from O(workspace
    # cache size) ``SCAN`` + batched DELETE to O(1) ``INCR``.

    @staticmethod
    def _cache_key_workspace_gen(workspace_id: uuid.UUID) -> str:
        """Counter key whose value is the current cache generation."""
        return f"{POST_CACHE_KEY_PREFIX}:ws:{workspace_id}:gen"

    async def _workspace_cache_gen(self, workspace_id: uuid.UUID) -> int:
        """Read the current generation; ``0`` when missing or Redis is off."""
        return await self.cache.get_int(self._cache_key_workspace_gen(workspace_id))

    async def _cache_key_detail(self, workspace_id: uuid.UUID, slug: str) -> str:
        """Key for a single published-post detail response (gen-versioned)."""
        gen = await self._workspace_cache_gen(workspace_id)
        return f"{POST_CACHE_KEY_PREFIX}:ws:{workspace_id}:v{gen}:slug:{slug}"

    async def _invalidate_workspace_cache(self, workspace_id: uuid.UUID) -> None:
        """Bump the per-workspace generation, abandoning every prior entry."""
        await self.cache.incr(self._cache_key_workspace_gen(workspace_id))

    @staticmethod
    def _build_detail(post: Post) -> PostDetailResponse:
        """Render an ORM :class:`Post` into a :class:`PostDetailResponse`."""
        base = PostResponse.model_validate(post).model_dump()
        content = post.content
        return PostDetailResponse(
            **base,
            content_json=content.content_json if content is not None else dict(EMPTY_TIPTAP_DOC),
            content_html=content.content_html if content is not None else "",
            content_text=content.content_text if content is not None else "",
            category=CategoryResponse.model_validate(post.category) if post.category is not None else None,
            tags=[TagResponse.model_validate(tag) for tag in post.tags],
        )
