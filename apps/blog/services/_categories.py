"""Per-workspace category service.

Holds slug-uniqueness validation and soft-delete; otherwise a thin
delegation to :class:`apps.blog.repositories.CategoryRepository`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from apps.blog.exceptions import CategoryNotFoundError, CategorySlugConflictError
from apps.blog.models import Category
from apps.blog.utils import normalize_slug
from apps.core.database.transactional import transactional
from apps.core.database.utils import slugify
from apps.core.services.base import BaseSQLAlchemyService

if TYPE_CHECKING:
    from apps.blog.repositories import CategoryRepository
    from apps.blog.schemas import (
        CreateCategoryRequest,
        ListCategoriesRequest,
        UpdateCategoryRequest,
    )
    from apps.core.database.types import SessionType


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
        slug = normalize_slug(data.slug or slugify(data.name))
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
            new_slug = normalize_slug(payload["slug"])
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
