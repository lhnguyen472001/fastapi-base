"""Product module HTTP routes.

Public (no auth): listing and detail endpoints for products and categories.
Protected (``access_required``): create / update / delete endpoints.
"""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.session import session_factory
from apps.core.schemas.response import (
    APIResponse,
    PaginatedResponse,
)
from apps.product.containers import ProductContainer
from apps.product.schemas import (
    CreateProductCategoryRequest,
    CreateProductRequest,
    ListProductCategoriesRequest,
    ListProductsRequest,
    ProductCategoryResponse,
    ProductResponse,
    UpdateProductCategoryRequest,
    UpdateProductRequest,
)
from apps.product.services import ProductCategoryService, ProductService
from apps.rbac.dependencies import access_required
from apps.user.models import User

product_router = APIRouter(prefix="/products", tags=["products"])
product_category_router = APIRouter(prefix="/product-categories", tags=["product-categories"])


# ---------------------------------------------------------------------------
# Public product endpoints
# ---------------------------------------------------------------------------


@product_router.get("", response_model=APIResponse[PaginatedResponse[ProductResponse]])
@inject
async def list_products(
    params: ListProductsRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
) -> APIResponse[PaginatedResponse[ProductResponse]]:
    """List products with filtering, pagination, and full-text search."""
    items, total = await product_service.list_products(session, params=params)
    return APIResponse[PaginatedResponse[ProductResponse]].success(
        data=PaginatedResponse[ProductResponse](
            items=[ProductResponse.model_validate(p) for p in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Products retrieved successfully.",
    )


@product_router.get("/{slug}", response_model=APIResponse[ProductResponse])
@inject
async def get_product_by_slug(
    slug: str,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
) -> APIResponse[ProductResponse]:
    """Fetch a single product by slug."""
    product = await product_service.get_by_slug(session, slug=slug)
    return APIResponse[ProductResponse].success(
        data=ProductResponse.model_validate(product), message="Product retrieved successfully."
    )


# ---------------------------------------------------------------------------
# Protected product endpoints (require_access)
# ---------------------------------------------------------------------------


@product_router.post(
    "",
    response_model=APIResponse[ProductResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_product(
    data: CreateProductRequest,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    _: User = Depends(access_required("product", "write")),
) -> APIResponse[ProductResponse]:
    """Create a new product."""
    product = await product_service.create(session, data=data)
    return APIResponse[ProductResponse].success(
        data=ProductResponse.model_validate(product), message="Product created successfully."
    )


@product_router.patch("/{product_id}", response_model=APIResponse[ProductResponse])
@inject
async def update_product(
    product_id: uuid.UUID,
    data: UpdateProductRequest,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    _: User = Depends(access_required("product", "write")),
) -> APIResponse[ProductResponse]:
    """Partially update an existing product."""
    product = await product_service.update(session, product_id=product_id, data=data)
    return APIResponse[ProductResponse].success(
        data=ProductResponse.model_validate(product), message="Product updated successfully."
    )


@product_router.delete("/{product_id}", response_model=APIResponse[ProductResponse])
@inject
async def delete_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    _: User = Depends(access_required("product", "write")),
) -> APIResponse[ProductResponse]:
    """Soft-delete a product."""
    product = await product_service.soft_delete(session, product_id=product_id)
    return APIResponse[ProductResponse].success(
        data=ProductResponse.model_validate(product), message="Product deleted successfully."
    )


# ---------------------------------------------------------------------------
# Public category endpoints
# ---------------------------------------------------------------------------


@product_category_router.get(
    "",
    response_model=APIResponse[PaginatedResponse[ProductCategoryResponse]],
)
@inject
async def list_categories(
    params: ListProductCategoriesRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
) -> APIResponse[PaginatedResponse[ProductCategoryResponse]]:
    """List product categories with pagination."""
    items, total = await product_category_service.list_categories(session, params=params)
    return APIResponse[PaginatedResponse[ProductCategoryResponse]].success(
        data=PaginatedResponse[ProductCategoryResponse](
            items=[ProductCategoryResponse.model_validate(c) for c in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        message="Product categories retrieved successfully.",
    )


@product_category_router.get("/{slug}", response_model=APIResponse[ProductCategoryResponse])
@inject
async def get_category_by_slug(
    slug: str,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
) -> APIResponse[ProductCategoryResponse]:
    """Fetch a single product category by slug."""
    category = await product_category_service.get_by_slug(session, slug=slug)
    return APIResponse[ProductCategoryResponse].success(
        data=ProductCategoryResponse.model_validate(category), message="Product category retrieved successfully."
    )


# ---------------------------------------------------------------------------
# Protected category endpoints
# ---------------------------------------------------------------------------


@product_category_router.post(
    "",
    response_model=APIResponse[ProductCategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_category(
    data: CreateProductCategoryRequest,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    _: User = Depends(access_required("product_category", "write")),
) -> APIResponse[ProductCategoryResponse]:
    """Create a new product category."""
    category = await product_category_service.create(session, data=data)
    return APIResponse[ProductCategoryResponse].success(
        data=ProductCategoryResponse.model_validate(category), message="Product category created successfully."
    )


@product_category_router.patch("/{category_id}", response_model=APIResponse[ProductCategoryResponse])
@inject
async def update_category(
    category_id: uuid.UUID,
    data: UpdateProductCategoryRequest,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    _: User = Depends(access_required("product_category", "write")),
) -> APIResponse[ProductCategoryResponse]:
    """Partially update an existing product category."""
    category = await product_category_service.update(session, category_id=category_id, data=data)
    return APIResponse[ProductCategoryResponse].success(
        data=ProductCategoryResponse.model_validate(category), message="Product category updated successfully."
    )


@product_category_router.delete("/{category_id}", response_model=APIResponse[ProductCategoryResponse])
@inject
async def delete_category(
    category_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    _: User = Depends(access_required("product_category", "write")),
) -> APIResponse[ProductCategoryResponse]:
    """Soft-delete a product category."""
    category = await product_category_service.soft_delete(session, category_id=category_id)
    return APIResponse[ProductCategoryResponse].success(
        data=ProductCategoryResponse.model_validate(category), message="Product category deleted successfully."
    )
