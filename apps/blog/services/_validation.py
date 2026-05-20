"""Workspace-scoped validation for the blog post pipeline.

Owns the four guards that :class:`PostService.create` and
:meth:`PostService.update` apply before any write:

* slug uniqueness (per workspace, optionally excluding the row being updated)
* category exists and belongs to the workspace
* every tag id resolves within the workspace
* the per-post tag-count cap (``MAX_TAGS_PER_POST``)

Extracted from :class:`PostService` so the post service can drop
``category_repository`` and ``tag_repository`` from its constructor —
they only ever flowed through these validations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from apps.blog.constants import MAX_TAGS_PER_POST
from apps.blog.exceptions import (
    BlogResourceWorkspaceMismatchError,
    PostSlugConflictError,
    PostTooManyTagsError,
)
from apps.blog.repositories import (
    CategoryRepository,
    PostRepository,
    TagRepository,
)
from apps.core.database.types import SessionType


class PostValidationService:
    """Stateless workspace-scoped guards for post create / update."""

    def __init__(
        self,
        category_repository: CategoryRepository,
        tag_repository: TagRepository,
        post_repository: PostRepository,
    ) -> None:
        self.category_repository = category_repository
        self.tag_repository = tag_repository
        self.post_repository = post_repository

    async def ensure_slug_available(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise :class:`PostSlugConflictError` if ``slug`` already exists.

        ``exclude_id`` lets ``update`` pass over the post being updated so
        renaming a post to its own current slug is a no-op rather than a
        409.
        """
        existing = await self.post_repository.find_by_slug(
            session,
            workspace_id=workspace_id,
            slug=slug,
            exclude_id=exclude_id,
        )
        if existing is not None:
            raise PostSlugConflictError(message=f"Post slug '{slug}' already exists.")

    async def validate_category(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        category_id: uuid.UUID,
    ) -> None:
        """Raise if ``category_id`` does not exist in ``workspace_id``.

        Surfaces as :class:`BlogResourceWorkspaceMismatchError` whether the
        row is missing or simply belongs to another workspace — the public
        contract treats cross-workspace probes the same as not-found.
        """
        category = await self.category_repository.find_by_id(
            session,
            workspace_id=workspace_id,
            category_id=category_id,
        )
        if category is None:
            raise BlogResourceWorkspaceMismatchError(
                message=f"Category '{category_id}' not found in this workspace.",
            )

    async def validate_tags(
        self,
        session: SessionType,
        *,
        workspace_id: uuid.UUID,
        tag_ids: Sequence[uuid.UUID],
    ) -> None:
        """Raise if any id in ``tag_ids`` is missing from ``workspace_id``.

        Loads all tags in one batched ``IN (...)`` query (no N+1).
        """
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

    @staticmethod
    def enforce_tag_count(tag_ids: Sequence[uuid.UUID]) -> None:
        """Raise if ``len(tag_ids)`` exceeds :data:`MAX_TAGS_PER_POST`.

        Static — no I/O. The cap is independent of workspace; we keep the
        check on this service so the "what does it take to attach tags"
        contract lives in one place.
        """
        if len(tag_ids) > MAX_TAGS_PER_POST:
            raise PostTooManyTagsError(
                message=f"At most {MAX_TAGS_PER_POST} tags allowed per post.",
            )
