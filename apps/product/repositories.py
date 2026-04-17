"""Product module repositories.

Thin wrappers over :class:`BaseSQLAlchemyRepository` — all data access
delegates to the base's ``get_one``, ``list_and_count``, ``apply_filter``,
etc. Product-specific needs (eager loading, full-text search) are expressed
either by overriding ``self.statement`` in ``__init__`` or by passing extra
``ColumnElement[bool]`` conditions to base methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from apps.core.database.filters import LimitOffsetPaginationFilter
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.product.models import Product, ProductCategory, ProductImage

if TYPE_CHECKING:
    import uuid

    from apps.core.database.types import SessionType


class ProductCategoryRepository(BaseSQLAlchemyRepository[ProductCategory]):
    """Concrete repository for :class:`ProductCategory`."""

    model_type = ProductCategory

    async def find_by_id(
        self,
        session: SessionType,
        *,
        category_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> ProductCategory | None:
        """Find a category by ID, excluding soft-deleted rows by default."""
        conditions: list[Any] = [ProductCategory.id == category_id]
        if not include_deleted:
            conditions.append(ProductCategory.deleted_at.is_(None))
        return await self.get_one(session, *conditions)

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
    ) -> ProductCategory | None:
        """Find an active (non-deleted) category by slug."""
        conditions: list[Any] = [
            ProductCategory.slug == slug,
            ProductCategory.deleted_at.is_(None),
        ]
        if exclude_id is not None:
            conditions.append(ProductCategory.id != exclude_id)
        return await self.get_one(session, *conditions)


class ProductRepository(BaseSQLAlchemyRepository[Product]):
    """Concrete repository for :class:`Product`.

    The default statement is pre-loaded with ``category`` and ``images``
    relationships so every ``get_one`` / ``list_and_count`` call returns
    fully hydrated rows — no lazy-load errors in async context.
    """

    model_type = Product

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Override the default select(Product) with a relation-loaded one so
        # every base method (get_one, list_and_count, ...) returns hydrated
        # rows without further intervention. Both use selectinload so the
        # window-function pagination strategy works (joinedload produces
        # cartesian products that break COUNT(*) OVER()).
        self.statement = select(Product).options(
            selectinload(Product.category),
            selectinload(Product.images),
        )

    async def find_by_id(
        self,
        session: SessionType,
        *,
        product_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Product | None:
        """Fetch a product by ID with eager-loaded relations."""
        conditions: list[Any] = [Product.id == product_id]
        if not include_deleted:
            conditions.append(Product.deleted_at.is_(None))
        return await self.get_one(session, *conditions)

    async def find_by_slug(
        self,
        session: SessionType,
        *,
        slug: str,
        exclude_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> Product | None:
        """Fetch a product by slug with eager-loaded relations."""
        conditions: list[Any] = [Product.slug == slug]
        if not include_deleted:
            conditions.append(Product.deleted_at.is_(None))
        if exclude_id is not None:
            conditions.append(Product.id != exclude_id)
        return await self.get_one(session, *conditions)

    async def search_and_count(
        self,
        session: SessionType,
        *,
        limit: int,
        offset: int,
        category_id: uuid.UUID | None = None,
        is_available: bool | None = None,
        is_featured: bool | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        search: str | None = None,
    ) -> tuple[list[Product], int]:
        """List products matching filters, ordered by display_order.

        ``search`` is matched against the PostgreSQL ``tsvector`` column
        populated by a BEFORE-INSERT/UPDATE trigger (see the product module
        migration). Delegates pagination, counting, and execution to the
        base repository's :meth:`list_and_count`.
        """
        conditions: list[Any] = [Product.deleted_at.is_(None)]
        if category_id is not None:
            conditions.append(Product.category_id == category_id)
        if is_available is not None:
            conditions.append(Product.is_available == is_available)
        if is_featured is not None:
            conditions.append(Product.is_featured == is_featured)
        if min_price is not None:
            conditions.append(Product.retail_price >= min_price)
        if max_price is not None:
            conditions.append(Product.retail_price <= max_price)
        if search:
            # plainto_tsquery tolerates arbitrary user input without escaping.
            conditions.append(Product.search_vector.op("@@")(func.plainto_tsquery("simple", search)))

        items, total = await self.list_and_count(
            session,
            *conditions,
            LimitOffsetPaginationFilter(limit=limit, offset=offset),
            order_by=[
                (Product.display_order, False),  # ascending
                (Product.created_at, True),  # descending
            ],
            uniquify=True,
        )
        return list(items), total


class ProductImageRepository(BaseSQLAlchemyRepository[ProductImage]):
    """Concrete repository for :class:`ProductImage`."""

    model_type = ProductImage
