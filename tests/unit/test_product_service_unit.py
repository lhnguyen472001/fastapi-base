"""Unit tests for Product and ProductCategory services.

These tests stub the repositories and use a mocked AsyncSession (with
``in_transaction=True`` so ``@transactional`` joins the fake outer txn) to
exercise pure business logic: slug auto-generation, conflict detection,
category existence validation, payload mapping, and soft-delete timestamps.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.product.exceptions import (
    ProductCategoryNotFoundError,
    ProductCategorySlugConflictError,
    ProductNotFoundError,
    ProductSlugConflictError,
)
from apps.product.models import Product, ProductCategory
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

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> MagicMock:
    """Mocked AsyncSession; ``in_transaction=True`` keeps ``@transactional``
    from opening a real begin() against a mock."""
    sess = MagicMock(spec=AsyncSession, name="AsyncSession")
    sess.in_transaction.return_value = True
    sess.flush = AsyncMock()
    sess.refresh = AsyncMock()
    sess.add = MagicMock()
    return sess


@pytest.fixture
def product_repo() -> AsyncMock:
    r = AsyncMock()
    r.find_by_id = AsyncMock(return_value=None)
    r.find_by_slug = AsyncMock(return_value=None)
    r.search_and_count = AsyncMock(return_value=([], 0))
    r.add = AsyncMock()
    r.update = AsyncMock()
    return r


@pytest.fixture
def category_repo() -> AsyncMock:
    r = AsyncMock()
    r.find_by_id = AsyncMock(return_value=None)
    r.find_by_slug = AsyncMock(return_value=None)
    r.list_and_count = AsyncMock(return_value=([], 0))
    r.add = AsyncMock()
    r.update = AsyncMock()
    return r


@pytest.fixture
def image_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def category_service(category_repo: AsyncMock) -> ProductCategoryService:
    return ProductCategoryService(repository=category_repo)


@pytest.fixture
def product_service(
    product_repo: AsyncMock,
    category_repo: AsyncMock,
    image_repo: AsyncMock,
) -> ProductService:
    return ProductService(
        repository=product_repo,
        category_repository=category_repo,
        image_repository=image_repo,
    )


# ---------------------------------------------------------------------------
# ProductCategoryService
# ---------------------------------------------------------------------------


class TestProductCategoryServiceCreate:
    async def test_create_auto_generates_slug_from_name(self, session, category_service, category_repo) -> None:
        data = CreateProductCategoryRequest(name="Trà Thảo Mộc")
        category_repo.find_by_slug.return_value = None
        category_repo.add.return_value = ProductCategory(name=data.name, slug="tra-thao-moc")

        result = await category_service.create(session, data=data)

        assert result.slug == "tra-thao-moc"
        category_repo.add.assert_awaited_once()
        payload = category_repo.add.await_args.args[1]
        assert payload["slug"] == "tra-thao-moc"
        assert payload["name"] == "Trà Thảo Mộc"

    async def test_create_uses_explicit_slug_when_provided(self, session, category_service, category_repo) -> None:
        data = CreateProductCategoryRequest(name="Rice", slug="custom-slug")
        category_repo.add.return_value = ProductCategory(name="Rice", slug="custom-slug")

        await category_service.create(session, data=data)

        payload = category_repo.add.await_args.args[1]
        assert payload["slug"] == "custom-slug"

    async def test_create_rejects_slug_conflict(self, session, category_service, category_repo) -> None:
        category_repo.find_by_slug.return_value = ProductCategory(name="X", slug="dup")
        with pytest.raises(ProductCategorySlugConflictError):
            await category_service.create(
                session,
                data=CreateProductCategoryRequest(name="X", slug="dup"),
            )
        category_repo.add.assert_not_called()


class TestProductCategoryServiceGet:
    async def test_get_by_id_raises_when_missing(self, session, category_service, category_repo) -> None:
        category_repo.find_by_id.return_value = None
        with pytest.raises(ProductCategoryNotFoundError):
            await category_service.find_or_raise(session, category_id=uuid.uuid4())

    async def test_get_by_slug_raises_when_missing(self, session, category_service, category_repo) -> None:
        category_repo.find_by_slug.return_value = None
        with pytest.raises(ProductCategoryNotFoundError):
            await category_service.get_by_slug(session, slug="missing")


class TestProductCategoryServiceUpdate:
    async def test_update_detects_slug_conflict(self, session, category_service, category_repo) -> None:
        cid = uuid.uuid4()
        category_repo.find_by_id.return_value = ProductCategory(id=cid, name="X", slug="old")
        # Slug uniqueness check returns a conflicting other category
        category_repo.find_by_slug.return_value = ProductCategory(id=uuid.uuid4(), name="Other", slug="taken")
        with pytest.raises(ProductCategorySlugConflictError):
            await category_service.update(
                session,
                category_id=cid,
                data=UpdateProductCategoryRequest(slug="taken"),
            )


class TestProductCategoryServiceList:
    async def test_list_categories_forwards_pagination(self, session, category_service, category_repo) -> None:
        category_repo.list_and_count.return_value = ([], 0)
        params = ListProductCategoriesRequest(limit=5, offset=10, is_active=True)

        await category_service.list_categories(session, params=params)

        category_repo.list_and_count.assert_awaited_once()
        call = category_repo.list_and_count.await_args
        # First positional after session is the pagination filter instance.
        pagination_filter = call.args[1]
        assert pagination_filter.limit == 5
        assert pagination_filter.offset == 10
        assert call.kwargs["is_active"] is True
        assert call.kwargs["deleted_at"] is None


# ---------------------------------------------------------------------------
# ProductService
# ---------------------------------------------------------------------------


def _base_create_payload(**overrides) -> CreateProductRequest:
    defaults = {
        "name": "Trà Lavender",
        "ingredients": "Lavender, hoa hồng",
        "production": "Sản xuất thủ công.",
        "benefits": "Giúp thư giãn.",
        "retail_price": Decimal("15000"),
        "wholesale_price": None,
        "category_id": None,
        "images": [],
    }
    defaults.update(overrides)
    return CreateProductRequest(**defaults)


class TestProductServiceCreate:
    async def test_create_auto_slug_and_persists_images(self, session, product_service, product_repo) -> None:
        data = _base_create_payload(
            images=[
                CreateProductImageRequest(
                    url="https://cdn/a.jpg",
                    alt_text="a",
                    display_order=0,
                    is_primary=True,
                ),
                CreateProductImageRequest(url="https://cdn/b.jpg", alt_text="b", display_order=1),
            ]
        )

        product = await product_service.create(session, data=data)

        assert product.slug == "tra-lavender"
        assert product.name == "Trà Lavender"
        assert len(product.images) == 2
        assert product.images[0].url == "https://cdn/a.jpg"
        assert product.images[0].is_primary is True
        session.add.assert_called_once_with(product)
        session.flush.assert_awaited()

    async def test_create_rejects_slug_conflict(self, session, product_service, product_repo) -> None:
        product_repo.find_by_slug.return_value = Product(name="X", slug="dup")
        with pytest.raises(ProductSlugConflictError):
            await product_service.create(session, data=_base_create_payload(slug="dup"))
        session.add.assert_not_called()

    async def test_create_rejects_missing_category(self, session, product_service, category_repo) -> None:
        category_repo.find_by_id.return_value = None
        missing = uuid.uuid4()
        with pytest.raises(ProductCategoryNotFoundError):
            await product_service.create(session, data=_base_create_payload(category_id=missing))


class TestProductServiceGet:
    async def test_get_by_id_raises_when_missing(self, session, product_service, product_repo) -> None:
        product_repo.find_by_id.return_value = None
        with pytest.raises(ProductNotFoundError):
            await product_service.find_or_raise(session, product_id=uuid.uuid4())

    async def test_get_by_slug_raises_when_missing(self, session, product_service, product_repo) -> None:
        product_repo.find_by_slug.return_value = None
        with pytest.raises(ProductNotFoundError):
            await product_service.get_by_slug(session, slug="missing")


class TestProductServiceList:
    async def test_list_products_forwards_filters(self, session, product_service, product_repo) -> None:
        product_repo.search_and_count.return_value = ([], 0)
        params = ListProductsRequest(
            limit=10,
            offset=0,
            is_available=True,
            is_featured=True,
            min_price=Decimal("5000"),
            max_price=Decimal("20000"),
            search="lavender",
        )

        await product_service.list_products(session, params=params)

        kwargs = product_repo.search_and_count.await_args.kwargs
        assert kwargs["limit"] == 10
        assert kwargs["is_available"] is True
        assert kwargs["is_featured"] is True
        assert kwargs["min_price"] == 5000.0
        assert kwargs["max_price"] == 20000.0
        assert kwargs["search"] == "lavender"


class TestProductServiceUpdate:
    async def test_update_partial_mutates_fields(self, session, product_service, product_repo) -> None:
        pid = uuid.uuid4()
        existing = Product(
            id=pid,
            name="Old",
            slug="old",
            retail_price=Decimal("10000"),
            is_available=True,
            is_featured=False,
            display_order=0,
        )
        existing.images = []
        product_repo.find_by_id.return_value = existing

        await product_service.update(
            session,
            product_id=pid,
            data=UpdateProductRequest(name="New", is_featured=True),
        )

        assert existing.name == "New"
        assert existing.is_featured is True
        # slug left untouched because not in payload
        assert existing.slug == "old"

    async def test_update_replaces_images_when_provided(self, session, product_service, product_repo) -> None:
        pid = uuid.uuid4()
        existing = Product(
            id=pid,
            name="X",
            slug="x",
            retail_price=Decimal("1000"),
            is_available=True,
            is_featured=False,
            display_order=0,
        )
        existing.images = []
        product_repo.find_by_id.return_value = existing

        await product_service.update(
            session,
            product_id=pid,
            data=UpdateProductRequest(images=[CreateProductImageRequest(url="https://cdn/new.jpg", is_primary=True)]),
        )

        assert len(existing.images) == 1
        assert existing.images[0].url == "https://cdn/new.jpg"


class TestProductServiceSoftDelete:
    async def test_soft_delete_sets_deleted_at(self, session, product_service, product_repo) -> None:
        pid = uuid.uuid4()
        existing = Product(id=pid, name="X", slug="x", retail_price=Decimal("1000"))
        existing.images = []
        existing.deleted_at = None
        product_repo.find_by_id.return_value = existing

        result = await product_service.soft_delete(session, product_id=pid)

        assert result is existing
        assert existing.deleted_at is not None
