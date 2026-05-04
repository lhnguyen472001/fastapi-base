"""Per-workspace tag service.

Holds slug-uniqueness validation and hard delete; otherwise a thin
delegation to :class:`apps.blog.repositories.TagRepository`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from apps.blog.exceptions import TagNotFoundError, TagSlugConflictError
from apps.blog.models import Tag
from apps.blog.utils import normalize_slug
from apps.core.database.transactional import transactional
from apps.core.database.utils import slugify
from apps.core.services.base import BaseSQLAlchemyService

if TYPE_CHECKING:
    from apps.blog.repositories import TagRepository
    from apps.blog.schemas import CreateTagRequest, ListTagsRequest, UpdateTagRequest
    from apps.core.database.types import SessionType


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
        slug = normalize_slug(data.slug or slugify(data.name))
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
            new_slug = normalize_slug(payload["slug"])
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
