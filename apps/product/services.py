"""Product module services — business logic and orchestration."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from apps.core.database.filters import LimitOffsetPaginationFilter
from apps.core.database.transactional import transactional
from apps.core.database.utils import slugify
from apps.core.services.base import SQLAlchemyService
from apps.product.exceptions import (
    ProductCategoryNotFoundError,
    ProductCategorySlugConflictError,
    ProductNotFoundError,
    ProductSlugConflictError,
)
from apps.product.models import Product, ProductCategory, ProductImage
from apps.product.schemas import (
    CreateProductCategoryRequest,
    CreateProductImageRequest,
    CreateProductRequest,
    ListProductCategoriesRequest,
    ListProductsRequest,
    UpdateProductCategoryRequest,
    UpdateProductRequest,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from apps.core.database.types import SessionType
    from apps.product.repositories import (
        ProductCategoryRepository,
        ProductImageRepository,
        ProductRepository,
    )

# ---------------------------------------------------------------------------
# ProductCategoryService
# ---------------------------------------------------------------------------


class ProductCategoryService(SQLAlchemyService[ProductCategory]):
    """Business logic for product categories."""

    repository: ProductCategoryRepository

    def __init__(self, repository: ProductCategoryRepository) -> None:
        super().__init__(repository)

    @transactional
    async def create(
        self,
        session: SessionType,
        *,
        data: CreateProductCategoryRequest,
    ) -> ProductCategory:
        """Create a new product category."""
        slug = data.slug or slugify(data.name)
        await self._ensure_slug_available(session, slug=slug)

        payload: dict = {
            "name": data.name,
            "slug": slug,
            "description": data.description,
            "display_order": data.display_order,
            "is_active": data.is_active,
        }
        return await self.repository.add(session, payload, expunge=False)

    async def find_or_raise(self, session: SessionType, *, category_id: uuid.UUID) -> ProductCategory:
        """Fetch a category by ID or raise :class:`ProductCategoryNotFoundError`.

        Distinct name from the base ``get_by_id`` (which returns ``T | None``)
        to avoid the LSP violation that an override otherwise introduces.
        """
        category = await self.repository.find_by_id(session, category_id=category_id)
        if category is None:
            raise ProductCategoryNotFoundError(message=f"Product category with id '{category_id}' not found.")
        return category

    async def get_by_slug(self, session: SessionType, *, slug: str) -> ProductCategory:
        """Fetch an active category by slug."""
        category = await self.repository.find_by_slug(session, slug=slug)
        if category is None:
            raise ProductCategoryNotFoundError(message=f"Product category with slug '{slug}' not found.")
        return category

    async def list_categories(
        self,
        session: SessionType,
        *,
        params: ListProductCategoriesRequest,
    ) -> tuple[Sequence[ProductCategory], int]:
        """List active categories with pagination."""
        filter_kwargs: dict = {"deleted_at": None}
        if params.is_active is not None:
            filter_kwargs["is_active"] = params.is_active
        return await self.repository.list_and_count(
            session,
            LimitOffsetPaginationFilter(limit=params.limit, offset=params.offset),
            **filter_kwargs,
        )

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        category_id: uuid.UUID,
        data: UpdateProductCategoryRequest,
    ) -> ProductCategory:
        """Partially update a category."""
        await self.find_or_raise(session, category_id=category_id)

        payload = data.model_dump(exclude_unset=True)
        if "slug" in payload and payload["slug"] is not None:
            await self._ensure_slug_available(session, slug=payload["slug"], exclude_id=category_id)

        updated = await self.repository.update(session, item_id=category_id, data=payload)
        if updated is None:
            raise ProductCategoryNotFoundError(message=f"Product category with id '{category_id}' not found.")
        return updated

    @transactional
    async def soft_delete(self, session: SessionType, *, category_id: uuid.UUID) -> ProductCategory:
        """Soft delete a category. Products keep their rows but lose the FK."""
        await self.find_or_raise(session, category_id=category_id)
        deleted = await self.repository.update(
            session,
            item_id=category_id,
            data={"deleted_at": datetime.datetime.now(datetime.UTC)},
        )
        if deleted is None:
            raise ProductCategoryNotFoundError(message=f"Product category with id '{category_id}' not found.")
        return deleted

    async def _ensure_slug_available(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self.repository.find_by_slug(session, slug=slug, exclude_id=exclude_id)
        if existing is not None:
            raise ProductCategorySlugConflictError(message=f"Product category with slug '{slug}' already exists.")


# ---------------------------------------------------------------------------
# ProductService
# ---------------------------------------------------------------------------


class ProductService(SQLAlchemyService[Product]):
    """Business logic for products."""

    repository: ProductRepository

    def __init__(
        self,
        repository: ProductRepository,
        category_repository: ProductCategoryRepository,
        image_repository: ProductImageRepository,
    ) -> None:
        super().__init__(repository)
        self.category_repository = category_repository
        self.image_repository = image_repository

    @transactional
    async def create(self, session: SessionType, *, data: CreateProductRequest) -> Product:
        """Create a new product with nested images."""
        if data.category_id is not None:
            await self._ensure_category_exists(session, category_id=data.category_id)

        slug = data.slug or slugify(data.name)
        await self._ensure_slug_available(session, slug=slug)

        product = Product(
            name=data.name,
            slug=slug,
            ingredients=data.ingredients,
            production=data.production,
            benefits=data.benefits,
            retail_price=data.retail_price,
            wholesale_price=data.wholesale_price,
            category_id=data.category_id,
            is_available=data.is_available,
            is_featured=data.is_featured,
            display_order=data.display_order,
        )
        for image in data.images:
            product.images.append(self._build_image(image))

        product = await self.repository.add(session, product, expunge=False)
        reloaded = await self.repository.find_by_id(session, product_id=product.id)
        if reloaded is None:
            raise ProductNotFoundError(message=f"Product with id '{product.id}' not found after create.")
        return reloaded

    async def find_or_raise(self, session: SessionType, *, product_id: uuid.UUID) -> Product:
        """Fetch a product by ID or raise :class:`ProductNotFoundError`.

        Distinct name from the base ``get_by_id`` (which returns ``T | None``)
        to avoid the LSP violation that an override otherwise introduces.
        """
        product = await self.repository.find_by_id(session, product_id=product_id)
        if product is None:
            raise ProductNotFoundError(message=f"Product with id '{product_id}' not found.")
        return product

    async def get_by_slug(self, session: SessionType, *, slug: str) -> Product:
        """Fetch an active product by slug."""
        product = await self.repository.find_by_slug(session, slug=slug)
        if product is None:
            raise ProductNotFoundError(message=f"Product with slug '{slug}' not found.")
        return product

    async def list_products(self, session: SessionType, *, params: ListProductsRequest) -> tuple[list[Product], int]:
        """List products with filters, pagination, and full-text search."""
        return await self.repository.search_and_count(
            session,
            limit=params.limit,
            offset=params.offset,
            category_id=params.category_id,
            is_available=params.is_available,
            is_featured=params.is_featured,
            min_price=float(params.min_price) if params.min_price is not None else None,
            max_price=float(params.max_price) if params.max_price is not None else None,
            search=params.search,
        )

    @transactional
    async def update(
        self,
        session: SessionType,
        *,
        product_id: uuid.UUID,
        data: UpdateProductRequest,
    ) -> Product:
        """Partially update a product; optionally replace its images."""
        await self.find_or_raise(session, product_id=product_id)

        payload = data.model_dump(exclude_unset=True)
        new_images = payload.pop("images", None)

        if "category_id" in payload and payload["category_id"] is not None:
            await self._ensure_category_exists(session, category_id=payload["category_id"])

        if "slug" in payload and payload["slug"] is not None:
            await self._ensure_slug_available(session, slug=payload["slug"], exclude_id=product_id)

        if payload:
            await self.repository.update(session, item_id=product_id, data=payload)

        if new_images is not None:
            await self.image_repository.delete_where(session, ProductImage.product_id == product_id)
            if new_images:
                await self.image_repository.add_many(
                    session,
                    [
                        {
                            **CreateProductImageRequest(**image_data).model_dump(),
                            "product_id": product_id,
                        }
                        for image_data in new_images
                    ],
                    expunge=False,
                )

        reloaded = await self.repository.find_by_id(session, product_id=product_id)
        if reloaded is None:
            raise ProductNotFoundError(message=f"Product with id '{product_id}' not found.")
        return reloaded

    @transactional
    async def soft_delete(self, session: SessionType, *, product_id: uuid.UUID) -> Product:
        """Soft delete a product."""
        await self.find_or_raise(session, product_id=product_id)
        deleted = await self.repository.update(
            session,
            item_id=product_id,
            data={"deleted_at": datetime.datetime.now(datetime.UTC)},
        )
        if deleted is None:
            raise ProductNotFoundError(message=f"Product with id '{product_id}' not found.")
        return deleted

    async def _ensure_slug_available(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        existing = await self.repository.find_by_slug(session, slug=slug, exclude_id=exclude_id)
        if existing is not None:
            raise ProductSlugConflictError(message=f"Product with slug '{slug}' already exists.")

    async def _ensure_category_exists(self, session: SessionType, *, category_id: uuid.UUID) -> None:
        category = await self.category_repository.find_by_id(session, category_id=category_id)
        if category is None:
            raise ProductCategoryNotFoundError(message=f"Product category with id '{category_id}' not found.")

    @staticmethod
    def _build_image(data: CreateProductImageRequest) -> ProductImage:
        return ProductImage(
            url=data.url,
            alt_text=data.alt_text,
            display_order=data.display_order,
            is_primary=data.is_primary,
        )
