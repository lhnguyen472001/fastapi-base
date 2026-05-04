"""Blog module services — business logic for posts, categories, tags.

The Tiptap pipeline lives in :class:`PostService.create` /
:meth:`update`: ``content_json`` (client) → ``content_text`` (extractor)
→ ``content_html`` (renderer + nh3 sanitizer) → ``content_hash``
(SHA-256 of canonical JSON) → ``reading_minutes`` (word count /
WORDS_PER_MINUTE).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import uuid
from typing import TYPE_CHECKING, Any

from apps.blog.constants import BLOG_SLUG_PATTERN, EMPTY_TIPTAP_DOC, MAX_TAGS_PER_POST, WORDS_PER_MINUTE
from apps.blog.enums import PostStatus
from apps.blog.exceptions import (
    BlogResourceWorkspaceMismatchError,
    CategoryNotFoundError,
    CategorySlugConflictError,
    PostInvalidStatusTransitionError,
    PostNotFoundError,
    PostSlugConflictError,
    PostTooManyTagsError,
    TagNotFoundError,
    TagSlugConflictError,
)
from apps.blog.models import Category, Post, PostContent, Tag
from apps.core.database.transactional import transactional
from apps.core.database.utils import slugify
from apps.core.services.base import BaseSQLAlchemyService
from apps.core.tiptap import extract_text, render_html, sanitize_html

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apps.blog.repositories import (
        CategoryRepository,
        PostContentRepository,
        PostRepository,
        PostTagRepository,
        TagRepository,
    )
    from apps.blog.schemas import (
        CreateCategoryRequest,
        CreatePostRequest,
        CreateTagRequest,
        ListCategoriesRequest,
        ListPostsRequest,
        ListTagsRequest,
        UpdateCategoryRequest,
        UpdatePostRequest,
        UpdateTagRequest,
    )
    from apps.core.database.types import SessionType


# ---------------------------------------------------------------------------
# CategoryService
# ---------------------------------------------------------------------------


class CategoryService(BaseSQLAlchemyService[Category]):
    """Per-workspace category CRUD."""

    repository: CategoryRepository

    def __init__(self, repository: CategoryRepository) -> None:
        super().__init__(repository)

    @transactional
    async def create(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        data: CreateCategoryRequest,
    ) -> Category:
        slug = _normalize_slug(data.slug or slugify(data.name))
        await self._ensure_slug_available(session, workspace_id=workspace_id, slug=slug)
        category = Category(
            workspace_id=workspace_id,
            name=data.name,
            slug=slug,
            description=data.description,
            display_order=data.display_order,
            is_active=data.is_active,
        )
        return await self.repository.add(session, category, expunge=False)

    async def find_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
    ) -> Category:
        category = await self.repository.find_by_id(
            session,
            workspace_id=workspace_id,
            category_id=category_id,
        )
        if category is None:
            raise CategoryNotFoundError(message=f"Category '{category_id}' not found.")
        return category

    async def list_categories(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        params: ListCategoriesRequest,
    ) -> tuple[list[Category], int]:
        return await self.repository.list_for_workspace(
            session,
            workspace_id=workspace_id,
            is_active=params.is_active,
            limit=params.limit,
            offset=params.offset,
        )

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
        data: UpdateCategoryRequest,
    ) -> Category:
        await self.find_or_raise(session, workspace_id=workspace_id, category_id=category_id)
        payload = data.model_dump(exclude_unset=True)
        if "slug" in payload and payload["slug"] is not None:
            new_slug = _normalize_slug(payload["slug"])
            await self._ensure_slug_available(
                session,
                workspace_id=workspace_id,
                slug=new_slug,
                exclude_id=category_id,
            )
            payload["slug"] = new_slug
        updated = await self.repository.update(session, item_id=category_id, data=payload)
        if updated is None:
            raise CategoryNotFoundError(message=f"Category '{category_id}' not found.")
        return updated

    @transactional
    async def soft_delete(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
    ) -> Category:
        await self.find_or_raise(session, workspace_id=workspace_id, category_id=category_id)
        deleted = await self.repository.update(
            session,
            item_id=category_id,
            data={"deleted_at": datetime.datetime.now(datetime.UTC)},
        )
        if deleted is None:
            raise CategoryNotFoundError(message=f"Category '{category_id}' not found.")
        return deleted

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
            raise CategorySlugConflictError(message=f"Category slug '{slug}' already exists.")


# ---------------------------------------------------------------------------
# TagService
# ---------------------------------------------------------------------------


class TagService(BaseSQLAlchemyService[Tag]):
    """Per-workspace tag CRUD."""

    repository: TagRepository

    def __init__(self, repository: TagRepository) -> None:
        super().__init__(repository)

    @transactional
    async def create(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        data: CreateTagRequest,
    ) -> Tag:
        slug = _normalize_slug(data.slug or slugify(data.name))
        await self._ensure_slug_available(session, workspace_id=workspace_id, slug=slug)
        tag = Tag(workspace_id=workspace_id, name=data.name, slug=slug)
        return await self.repository.add(session, tag, expunge=False)

    async def find_or_raise(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> Tag:
        tag = await self.repository.find_by_id(session, workspace_id=workspace_id, tag_id=tag_id)
        if tag is None:
            raise TagNotFoundError(message=f"Tag '{tag_id}' not found.")
        return tag

    async def list_tags(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        params: ListTagsRequest,
    ) -> tuple[list[Tag], int]:
        return await self.repository.list_for_workspace(
            session,
            workspace_id=workspace_id,
            limit=params.limit,
            offset=params.offset,
        )

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_id: uuid.UUID,
        data: UpdateTagRequest,
    ) -> Tag:
        await self.find_or_raise(session, workspace_id=workspace_id, tag_id=tag_id)
        payload = data.model_dump(exclude_unset=True)
        if "slug" in payload and payload["slug"] is not None:
            new_slug = _normalize_slug(payload["slug"])
            await self._ensure_slug_available(
                session,
                workspace_id=workspace_id,
                slug=new_slug,
                exclude_id=tag_id,
            )
            payload["slug"] = new_slug
        updated = await self.repository.update(session, item_id=tag_id, data=payload)
        if updated is None:
            raise TagNotFoundError(message=f"Tag '{tag_id}' not found.")
        return updated

    @transactional
    async def delete(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> Tag:
        tag = await self.find_or_raise(session, workspace_id=workspace_id, tag_id=tag_id)
        deleted = await self.repository.delete(session, item_id=tag.id)
        if deleted is None:
            raise TagNotFoundError(message=f"Tag '{tag_id}' not found.")
        return deleted

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
            raise TagSlugConflictError(message=f"Tag slug '{slug}' already exists.")


# ---------------------------------------------------------------------------
# PostService
# ---------------------------------------------------------------------------


class PostService(BaseSQLAlchemyService[Post]):
    """Per-workspace post CRUD plus the Tiptap content pipeline."""

    repository: PostRepository

    def __init__(
        self,
        repository: PostRepository,
        content_repository: PostContentRepository,
        post_tag_repository: PostTagRepository,
        category_repository: CategoryRepository,
        tag_repository: TagRepository,
    ) -> None:
        super().__init__(repository)
        self.content_repository = content_repository
        self.post_tag_repository = post_tag_repository
        self.category_repository = category_repository
        self.tag_repository = tag_repository

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
        slug = _normalize_slug(data.slug or slugify(data.title))
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
        content_text, content_html, content_hash, word_count, reading_minutes = _compute_content_artifacts(
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

        if "slug" in payload and payload["slug"] is not None:
            new_slug = _normalize_slug(payload["slug"])
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

        new_content = payload.pop("content_json", None)
        if "hero_quote" in payload and payload["hero_quote"] is not None:
            payload["hero_quote"] = data.hero_quote.model_dump(mode="json") if data.hero_quote else None

        existing_content = post.content
        if new_content is not None:
            content_text, content_html, content_hash, word_count, reading_minutes = _compute_content_artifacts(
                new_content,
            )
            if content_hash != post.content_hash:
                payload["content_hash"] = content_hash
                payload["word_count"] = word_count
                payload["reading_minutes"] = reading_minutes
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

        if payload:
            await self.repository.update(session, item_id=post_id, data=payload)

        if new_tag_ids is not None:
            await self.post_tag_repository.replace_post_tags(
                session,
                post_id=post.id,
                tag_ids=new_tag_ids,
            )

        return await self._reload(session, workspace_id=workspace_id, post_id=post.id)

    @transactional
    async def publish(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        post_id: uuid.UUID,
    ) -> Post:
        post = await self.find_or_raise(session, workspace_id=workspace_id, post_id=post_id)
        if post.status not in {PostStatus.DRAFT.value, PostStatus.ARCHIVED.value}:
            raise PostInvalidStatusTransitionError(
                message=f"Cannot publish from status '{post.status}'.",
            )
        await self.repository.update(
            session,
            item_id=post_id,
            data={
                "status": PostStatus.PUBLISHED.value,
                "published_at": datetime.datetime.now(datetime.UTC),
            },
        )
        return await self._reload(session, workspace_id=workspace_id, post_id=post_id)

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
        return await self._reload(session, workspace_id=workspace_id, post_id=post_id)

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
        return await self._reload(session, workspace_id=workspace_id, post_id=post_id)

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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalize_slug(slug: str) -> str:
    """Lowercase + strip; reject if it doesn't match the blog slug pattern."""
    candidate = slug.strip().lower()
    if BLOG_SLUG_PATTERN.fullmatch(candidate) is None:
        # Slug came from the schema's min/max length validation but the regex
        # didn't match — typically uppercase or punctuation. Re-slugify and try
        # again so user-supplied "Hello World!" becomes "hello-world".
        candidate = slugify(candidate)
    return candidate


def _compute_content_artifacts(
    content_json: dict[str, Any],
) -> tuple[str, str, str, int, int]:
    """Run the Tiptap pipeline. Returns (text, html, hash, words, minutes)."""
    text = extract_text(content_json)
    html = sanitize_html(render_html(content_json))
    canonical = json.dumps(content_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    word_count = len(text.split()) if text else 0
    reading_minutes = max(1, math.ceil(word_count / WORDS_PER_MINUTE)) if word_count > 0 else 0
    return text, html, digest, word_count, reading_minutes
