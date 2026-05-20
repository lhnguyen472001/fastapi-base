"""Per-workspace cache helpers for the blog domain.

Centralises every Redis touch related to post detail caching, workspace-
level invalidation, and the Tiptap render cache. :class:`PostService` and
:class:`_PostAutosaveMixin` both depend on the same surface — keeping it
on one collaborator means there is exactly one place to grep for "what
key shape does a published-post cache write use" or "when is a workspace
invalidated".
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.blog.constants import POST_CACHE_DETAIL_TTL, POST_CACHE_KEY_PREFIX
from apps.blog.utils import invalidate_render_cache_for_post, render_html_cached
from apps.core.redis import CacheManager


class PostCacheService:
    """Versioned-prefix cache facade for posts and their rendered bodies."""

    def __init__(self, cache: CacheManager) -> None:
        self._cache = cache

    @staticmethod
    def _workspace_gen_key(workspace_id: uuid.UUID) -> str:
        """Counter key whose value is the current cache generation."""
        return f"{POST_CACHE_KEY_PREFIX}:ws:{workspace_id}:gen"

    async def _current_generation(self, workspace_id: uuid.UUID) -> int:
        """Read the current generation; ``0`` when missing or Redis is off."""
        return await self._cache.get_int(self._workspace_gen_key(workspace_id))

    async def _detail_key(self, workspace_id: uuid.UUID, slug: str) -> str:
        """Key for a single published-post detail response (gen-versioned)."""
        gen = await self._current_generation(workspace_id)
        return f"{POST_CACHE_KEY_PREFIX}:ws:{workspace_id}:v{gen}:slug:{slug}"

    async def get_detail(
        self,
        workspace_id: uuid.UUID,
        slug: str,
    ) -> Any | None:
        """Return the cached detail payload (or ``None`` on miss / Redis-off)."""
        key = await self._detail_key(workspace_id, slug)
        return await self._cache.get(key)

    async def put_detail(
        self,
        workspace_id: uuid.UUID,
        slug: str,
        payload: Any,
        *,
        ttl: int = POST_CACHE_DETAIL_TTL,
    ) -> None:
        """Persist a detail payload under the current generation key."""
        key = await self._detail_key(workspace_id, slug)
        await self._cache.set(key, payload, ttl=ttl)

    async def invalidate_workspace(self, workspace_id: uuid.UUID) -> None:
        """Bump the per-workspace generation, abandoning every prior entry.

        Cheap: one Redis ``INCR``. Every cached key under the previous
        generation prefix is orphaned in O(1) and reaped naturally via
        its existing TTL.
        """
        await self._cache.incr(self._workspace_gen_key(workspace_id))

    async def invalidate_render(self, post_id: uuid.UUID) -> int:
        """Drop every cached render for ``post_id``.

        Used after a persisted edit (:meth:`PostService.update`) so the
        next reader re-renders from the new authoritative ``content_hash``
        immediately, instead of serving a stale entry until
        ``POST_RENDER_CACHE_TTL_SECONDS`` elapses.
        """
        return await invalidate_render_cache_for_post(self._cache, post_id=post_id)

    async def render_html_cached(
        self,
        *,
        post_id: uuid.UUID,
        content_json: dict[str, Any],
        content_hash: str,
    ) -> str:
        """Render-or-fetch the cached HTML for ``(post_id, content_hash)``.

        Thin pass-through to :func:`apps.blog.utils.render_html_cached`
        kept on this service so callers (notably the autosave service's
        merged read path) do not have to thread the underlying
        :class:`CacheManager` through their own dependencies.
        """
        return await render_html_cached(
            self._cache,
            post_id=post_id,
            content_json=content_json,
            content_hash=content_hash,
        )
