"""Product module HTTP routes.

Public (no auth): listing and detail endpoints for products and categories.
Protected (``require_access``): create / update / delete endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from apps.auth.dependencies import get_current_user
from apps.core.database.session import session_factory
from apps.core.schemas.response import (
    APIResponse,
    JsonResponseStatuses,
    PaginatedResponse,
    ResponseCodes,
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
from apps.rbac.containers import RBACContainer
from apps.rbac.decorators import require_access

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.product.services import ProductCategoryService, ProductService
    from apps.rbac.services import AccessService
    from apps.user.models import User

router = APIRouter(prefix="/products", tags=["products"])
category_router = APIRouter(prefix="/product-categories", tags=["product-categories"])


# ---------------------------------------------------------------------------
# Public product endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=APIResponse[PaginatedResponse[ProductResponse]])
@inject
async def list_products(
    params: ListProductsRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
) -> APIResponse[PaginatedResponse[ProductResponse]]:
    """List products with filtering, pagination, and full-text search."""
    items, total = await product_service.list_products(session, params=params)
    return APIResponse[PaginatedResponse[ProductResponse]](
        code=ResponseCodes.API000,
        data=PaginatedResponse[ProductResponse](
            items=[ProductResponse.model_validate(p) for p in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        status=JsonResponseStatuses.SUCCESS,
        message="Products retrieved successfully.",
    )


@router.get("/{slug}", response_model=APIResponse[ProductResponse])
@inject
async def get_product_by_slug(
    slug: str,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
) -> APIResponse[ProductResponse]:
    """Fetch a single product by slug."""
    product = await product_service.get_by_slug(session, slug=slug)
    return APIResponse[ProductResponse](
        code=ResponseCodes.API000,
        data=ProductResponse.model_validate(product),
        status=JsonResponseStatuses.SUCCESS,
        message="Product retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# Protected product endpoints (require_access)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[ProductResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
@require_access("product", "write")
async def create_product(
    data: CreateProductRequest,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductResponse]:
    """Create a new product."""
    product = await product_service.create(session, data=data)
    return APIResponse[ProductResponse](
        code=ResponseCodes.API000,
        data=ProductResponse.model_validate(product),
        status=JsonResponseStatuses.SUCCESS,
        message="Product created successfully.",
    )


@router.patch("/{product_id}", response_model=APIResponse[ProductResponse])
@inject
@require_access("product", "write")
async def update_product(
    product_id: uuid.UUID,
    data: UpdateProductRequest,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductResponse]:
    """Partially update an existing product."""
    product = await product_service.update(session, product_id=product_id, data=data)
    return APIResponse[ProductResponse](
        code=ResponseCodes.API000,
        data=ProductResponse.model_validate(product),
        status=JsonResponseStatuses.SUCCESS,
        message="Product updated successfully.",
    )


@router.delete("/{product_id}", response_model=APIResponse[ProductResponse])
@inject
@require_access("product", "write")
async def delete_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    product_service: ProductService = Depends(Provide[ProductContainer.product_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductResponse]:
    """Soft-delete a product."""
    product = await product_service.soft_delete(session, product_id=product_id)
    return APIResponse[ProductResponse](
        code=ResponseCodes.API000,
        data=ProductResponse.model_validate(product),
        status=JsonResponseStatuses.SUCCESS,
        message="Product deleted successfully.",
    )


# ---------------------------------------------------------------------------
# Public category endpoints
# ---------------------------------------------------------------------------


@category_router.get(
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
    return APIResponse[PaginatedResponse[ProductCategoryResponse]](
        code=ResponseCodes.API000,
        data=PaginatedResponse[ProductCategoryResponse](
            items=[ProductCategoryResponse.model_validate(c) for c in items],
            total=total,
            limit=params.limit,
            offset=params.offset,
        ),
        status=JsonResponseStatuses.SUCCESS,
        message="Product categories retrieved successfully.",
    )


@category_router.get("/{slug}", response_model=APIResponse[ProductCategoryResponse])
@inject
async def get_category_by_slug(
    slug: str,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
) -> APIResponse[ProductCategoryResponse]:
    """Fetch a single product category by slug."""
    category = await product_category_service.get_by_slug(session, slug=slug)
    return APIResponse[ProductCategoryResponse](
        code=ResponseCodes.API000,
        data=ProductCategoryResponse.model_validate(category),
        status=JsonResponseStatuses.SUCCESS,
        message="Product category retrieved successfully.",
    )


# ---------------------------------------------------------------------------
# Protected category endpoints
# ---------------------------------------------------------------------------


@category_router.post(
    "",
    response_model=APIResponse[ProductCategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
@inject
@require_access("product_category", "write")
async def create_category(
    data: CreateProductCategoryRequest,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductCategoryResponse]:
    """Create a new product category."""
    category = await product_category_service.create(session, data=data)
    return APIResponse[ProductCategoryResponse](
        code=ResponseCodes.API000,
        data=ProductCategoryResponse.model_validate(category),
        status=JsonResponseStatuses.SUCCESS,
        message="Product category created successfully.",
    )


@category_router.patch("/{category_id}", response_model=APIResponse[ProductCategoryResponse])
@inject
@require_access("product_category", "write")
async def update_category(
    category_id: uuid.UUID,
    data: UpdateProductCategoryRequest,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductCategoryResponse]:
    """Partially update an existing product category."""
    category = await product_category_service.update(session, category_id=category_id, data=data)
    return APIResponse[ProductCategoryResponse](
        code=ResponseCodes.API000,
        data=ProductCategoryResponse.model_validate(category),
        status=JsonResponseStatuses.SUCCESS,
        message="Product category updated successfully.",
    )


@category_router.delete("/{category_id}", response_model=APIResponse[ProductCategoryResponse])
@inject
@require_access("product_category", "write")
async def delete_category(
    category_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    product_category_service: ProductCategoryService = Depends(Provide[ProductContainer.product_category_service]),
    access_service: AccessService = Depends(Provide[RBACContainer.access_service]),  # noqa: ARG001
    current_user: User = Depends(get_current_user),  # noqa: ARG001
) -> APIResponse[ProductCategoryResponse]:
    """Soft-delete a product category."""
    category = await product_category_service.soft_delete(session, category_id=category_id)
    return APIResponse[ProductCategoryResponse](
        code=ResponseCodes.API000,
        data=ProductCategoryResponse.model_validate(category),
        status=JsonResponseStatuses.SUCCESS,
        message="Product category deleted successfully.",
    )
