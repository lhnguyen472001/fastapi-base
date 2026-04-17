"""Real-DB integration tests for the Product module.

Covers the public service contract:
    - Category: create / get_by_id / get_by_slug / list / update / soft_delete
    - Product: create (with nested images) / get_by_id / get_by_slug
                list / update (replace images) / soft_delete
Plus business rules: slug conflict, missing category, full-text search,
soft-delete exclusion, cascade to images.

Prerequisites:
    docker compose up -d postgres
    uv run alembic upgrade head
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.product.exceptions import (
    ProductCategoryNotFoundError,
    ProductCategorySlugConflictError,
    ProductNotFoundError,
    ProductSlugConflictError,
)
from apps.product.repositories import (
    ProductCategoryRepository,
    ProductImageRepository,
    ProductRepository,
)
from apps.product.schemas import (
    CreateProductCategoryRequest,
    CreateProductImageRequest,
    CreateProductRequest,
    ListProductCategoriesRequest,
    ListProductsRequest,
    UpdateProductCategoryRequest,
    UpdateProductRequest,
)
from apps.product.services import ProductCategoryService, ProductService


@pytest.fixture
def category_service() -> ProductCategoryService:
    return ProductCategoryService(repository=ProductCategoryRepository())


@pytest.fixture
def product_service() -> ProductService:
    return ProductService(
        repository=ProductRepository(),
        category_repository=ProductCategoryRepository(),
        image_repository=ProductImageRepository(),
    )


def _category_request(suffix: str) -> CreateProductCategoryRequest:
    return CreateProductCategoryRequest(
        name=f"Danh mục {suffix}",
        slug=f"cat-{suffix}",
        description="Seed from real-db test.",
        display_order=0,
        is_active=True,
    )


def _product_request(
    suffix: str,
    *,
    category_id: uuid.UUID | None = None,
    retail_price: Decimal = Decimal("15000"),
    images: list[CreateProductImageRequest] | None = None,
) -> CreateProductRequest:
    return CreateProductRequest(
        name=f"Sản phẩm {suffix}",
        slug=f"prod-{suffix}",
        ingredients="Lavender, hoa hồng",
        production="Thuần tự nhiên.",
        benefits="Tốt cho sức khoẻ.",
        retail_price=retail_price,
        wholesale_price=None,
        category_id=category_id,
        is_available=True,
        is_featured=False,
        display_order=0,
        images=images or [],
    )


# ---------------------------------------------------------------------------
# ProductCategoryService
# ---------------------------------------------------------------------------


class TestCategoryCreate:
    async def test_create_persists_category(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        result = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        assert result.id is not None
        assert result.name == f"Danh mục {suffix}"
        assert result.slug == f"cat-{suffix}"
        assert result.is_active is True

    async def test_create_auto_slugifies_name_when_slug_omitted(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        data = CreateProductCategoryRequest(name=f"Trà Hoa {suffix}")
        result = await category_service.create(real_session, data=data)
        await real_session.flush()

        assert result.slug.startswith("tra-hoa-")

    async def test_create_rejects_duplicate_slug(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        with pytest.raises(ProductCategorySlugConflictError):
            await category_service.create(real_session, data=_category_request(suffix))


class TestCategoryGet:
    async def test_get_by_id(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        fetched = await category_service.get_by_id(real_session, category_id=created.id)
        assert fetched.id == created.id

    async def test_get_by_id_raises_when_missing(self, real_session, category_service) -> None:
        with pytest.raises(ProductCategoryNotFoundError):
            await category_service.get_by_id(real_session, category_id=uuid.uuid4())

    async def test_get_by_slug(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        fetched = await category_service.get_by_slug(real_session, slug=created.slug)
        assert fetched.id == created.id


class TestCategoryListAndUpdate:
    async def test_list_excludes_soft_deleted(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        items_before, _ = await category_service.list_categories(
            real_session, params=ListProductCategoriesRequest(limit=100)
        )
        assert any(c.id == created.id for c in items_before)

        await category_service.soft_delete(real_session, category_id=created.id)
        await real_session.flush()

        items_after, _ = await category_service.list_categories(
            real_session, params=ListProductCategoriesRequest(limit=100)
        )
        assert not any(c.id == created.id for c in items_after)

    async def test_update_modifies_fields(self, real_session, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        updated = await category_service.update(
            real_session,
            category_id=created.id,
            data=UpdateProductCategoryRequest(name="Đổi tên", is_active=False),
        )
        await real_session.flush()

        assert updated.name == "Đổi tên"
        assert updated.is_active is False


# ---------------------------------------------------------------------------
# ProductService
# ---------------------------------------------------------------------------


class TestProductCreate:
    async def test_create_with_images_persists_all(self, real_session, product_service, category_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        category = await category_service.create(real_session, data=_category_request(suffix))
        await real_session.flush()

        data = _product_request(
            suffix,
            category_id=category.id,
            images=[
                CreateProductImageRequest(
                    url="https://cdn/a.jpg",
                    alt_text="a",
                    display_order=0,
                    is_primary=True,
                ),
                CreateProductImageRequest(
                    url="https://cdn/b.jpg",
                    alt_text="b",
                    display_order=1,
                ),
            ],
        )

        product = await product_service.create(real_session, data=data)
        await real_session.flush()

        assert product.id is not None
        assert product.slug == f"prod-{suffix}"
        assert len(product.images) == 2
        assert product.category_id == category.id

    async def test_create_rejects_duplicate_slug(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        await product_service.create(real_session, data=_product_request(suffix))
        await real_session.flush()

        with pytest.raises(ProductSlugConflictError):
            await product_service.create(real_session, data=_product_request(suffix))

    async def test_create_rejects_missing_category(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        with pytest.raises(ProductCategoryNotFoundError):
            await product_service.create(
                real_session,
                data=_product_request(suffix, category_id=uuid.uuid4()),
            )


class TestProductGet:
    async def test_get_by_id_eager_loads_images(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(
            real_session,
            data=_product_request(
                suffix,
                images=[CreateProductImageRequest(url="https://cdn/x.jpg", is_primary=True)],
            ),
        )
        await real_session.flush()

        fetched = await product_service.get_by_id(real_session, product_id=created.id)
        assert fetched.id == created.id
        # Eager-loaded — accessing .images in async context must not raise.
        assert len(fetched.images) == 1
        assert fetched.images[0].url == "https://cdn/x.jpg"

    async def test_get_by_slug(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(real_session, data=_product_request(suffix))
        await real_session.flush()

        fetched = await product_service.get_by_slug(real_session, slug=created.slug)
        assert fetched.id == created.id

    async def test_get_by_id_raises_when_missing(self, real_session, product_service) -> None:
        with pytest.raises(ProductNotFoundError):
            await product_service.get_by_id(real_session, product_id=uuid.uuid4())


class TestProductList:
    async def test_list_excludes_soft_deleted(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(real_session, data=_product_request(suffix))
        await real_session.flush()

        items_before, _ = await product_service.list_products(real_session, params=ListProductsRequest(limit=100))
        assert any(p.id == created.id for p in items_before)

        await product_service.soft_delete(real_session, product_id=created.id)
        await real_session.flush()

        items_after, _ = await product_service.list_products(real_session, params=ListProductsRequest(limit=100))
        assert not any(p.id == created.id for p in items_after)

    async def test_list_price_range_filter(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        cheap = await product_service.create(
            real_session,
            data=_product_request(f"{suffix}-cheap", retail_price=Decimal("5000")),
        )
        pricey = await product_service.create(
            real_session,
            data=_product_request(f"{suffix}-pricey", retail_price=Decimal("50000")),
        )
        await real_session.flush()

        items, _ = await product_service.list_products(
            real_session,
            params=ListProductsRequest(
                limit=100,
                min_price=Decimal("4000"),
                max_price=Decimal("10000"),
            ),
        )
        ids = {p.id for p in items}
        assert cheap.id in ids
        assert pricey.id not in ids

    async def test_list_full_text_search_on_trigger_vector(self, real_session, product_service) -> None:
        """Trigger populates ``search_vector``; ``search=...`` should hit it."""
        suffix = uuid.uuid4().hex[:8]
        needle = f"unique{suffix}token"
        created = await product_service.create(
            real_session,
            data=CreateProductRequest(
                name=f"Trà {needle} đặc biệt",
                retail_price=Decimal("15000"),
                ingredients="Lavender, hoa hồng",
            ),
        )
        await real_session.flush()

        items, total = await product_service.list_products(
            real_session,
            params=ListProductsRequest(limit=10, search=needle),
        )
        assert total >= 1
        assert any(p.id == created.id for p in items)


class TestProductUpdate:
    async def test_update_partial_fields(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(real_session, data=_product_request(suffix))
        await real_session.flush()

        updated = await product_service.update(
            real_session,
            product_id=created.id,
            data=UpdateProductRequest(
                name="Tên mới",
                retail_price=Decimal("99000"),
                is_featured=True,
            ),
        )
        await real_session.flush()

        assert updated.name == "Tên mới"
        assert updated.retail_price == Decimal("99000.00")
        assert updated.is_featured is True
        # slug unchanged because not in payload
        assert updated.slug == f"prod-{suffix}"

    async def test_update_replaces_images(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(
            real_session,
            data=_product_request(
                suffix,
                images=[
                    CreateProductImageRequest(url="https://cdn/old.jpg"),
                ],
            ),
        )
        await real_session.flush()

        updated = await product_service.update(
            real_session,
            product_id=created.id,
            data=UpdateProductRequest(
                images=[
                    CreateProductImageRequest(url="https://cdn/new-1.jpg", display_order=0),
                    CreateProductImageRequest(url="https://cdn/new-2.jpg", display_order=1),
                ]
            ),
        )
        await real_session.flush()

        urls = {img.url for img in updated.images}
        assert urls == {"https://cdn/new-1.jpg", "https://cdn/new-2.jpg"}

    async def test_update_raises_when_missing(self, real_session, product_service) -> None:
        with pytest.raises(ProductNotFoundError):
            await product_service.update(
                real_session,
                product_id=uuid.uuid4(),
                data=UpdateProductRequest(name="X"),
            )


class TestProductSoftDelete:
    async def test_soft_delete_sets_deleted_at(self, real_session, product_service) -> None:
        suffix = uuid.uuid4().hex[:8]
        created = await product_service.create(real_session, data=_product_request(suffix))
        await real_session.flush()

        deleted = await product_service.soft_delete(real_session, product_id=created.id)
        await real_session.flush()

        assert deleted.deleted_at is not None
        # Subsequent lookups should now raise NotFound.
        with pytest.raises(ProductNotFoundError):
            await product_service.get_by_id(real_session, product_id=created.id)
