"""Product module Pydantic schemas."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import Field

from apps.core.schemas.request import OffsetPaginationRequestSchema, RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema

# ---------------------------------------------------------------------------
# Product image schemas
# ---------------------------------------------------------------------------


class CreateProductImageRequest(RequestObjectSchema):
    """Nested image payload for product create/update."""

    url: str = Field(..., max_length=1024, description="External image URL (e.g. S3 / CDN).")
    alt_text: str | None = Field(default=None, max_length=255)
    display_order: int = Field(default=0, ge=0)
    is_primary: bool = Field(default=False)


class ProductImageResponse(ResponseObjectSchema):
    """Serialized product image."""

    id: uuid.UUID
    url: str
    alt_text: str | None
    display_order: int
    is_primary: bool


# ---------------------------------------------------------------------------
# Product category schemas
# ---------------------------------------------------------------------------


class CreateProductCategoryRequest(RequestObjectSchema):
    """Schema for creating a product category."""

    name: str = Field(..., min_length=1, max_length=150)
    slug: str | None = Field(
        default=None,
        max_length=160,
        description="Optional; auto-generated from name if omitted.",
    )
    description: str | None = Field(default=None)
    display_order: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)


class UpdateProductCategoryRequest(RequestObjectSchema):
    """Schema for partially updating a product category."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = Field(default=None)


class ListProductCategoriesRequest(OffsetPaginationRequestSchema):
    """Schema for listing product categories."""

    is_active: bool | None = Field(default=None)


class ProductCategoryResponse(ResponseObjectSchema):
    """Serialized product category (without nested products)."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    display_order: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------------------------------------------------------------------------
# Product schemas
# ---------------------------------------------------------------------------


class CreateProductRequest(RequestObjectSchema):
    """Schema for creating a product."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        max_length=280,
        description="Optional; auto-generated from name if omitted.",
    )
    ingredients: str | None = Field(default=None, description="Thành phần")
    production: str | None = Field(default=None, description="Sản xuất")
    benefits: str | None = Field(default=None, description="Công dụng")
    retail_price: Decimal = Field(..., ge=0, description="Giá lẻ (VND).")
    wholesale_price: Decimal | None = Field(default=None, ge=0, description="Giá sĩ (VND); null means 'Liên hệ'.")
    category_id: uuid.UUID | None = Field(default=None)
    is_available: bool = Field(default=True)
    is_featured: bool = Field(default=False)
    display_order: int = Field(default=0, ge=0)
    images: list[CreateProductImageRequest] = Field(default_factory=list)


class UpdateProductRequest(RequestObjectSchema):
    """Schema for partially updating a product.

    Only fields present in the request body are applied. If ``images`` is
    provided, the existing image set is replaced entirely.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=280)
    ingredients: str | None = Field(default=None)
    production: str | None = Field(default=None)
    benefits: str | None = Field(default=None)
    retail_price: Decimal | None = Field(default=None, ge=0)
    wholesale_price: Decimal | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = Field(default=None)
    is_available: bool | None = Field(default=None)
    is_featured: bool | None = Field(default=None)
    display_order: int | None = Field(default=None, ge=0)
    images: list[CreateProductImageRequest] | None = Field(default=None)


class ListProductsRequest(OffsetPaginationRequestSchema):
    """Schema for listing products."""

    category_id: uuid.UUID | None = Field(default=None)
    is_available: bool | None = Field(default=None)
    is_featured: bool | None = Field(default=None)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    search: str | None = Field(default=None, max_length=255)


class ProductResponse(ResponseObjectSchema):
    """Full product response including nested category and images."""

    id: uuid.UUID
    name: str
    slug: str
    ingredients: str | None
    production: str | None
    benefits: str | None
    retail_price: Decimal
    wholesale_price: Decimal | None
    category_id: uuid.UUID | None
    category: ProductCategoryResponse | None
    is_available: bool
    is_featured: bool
    display_order: int
    images: list[ProductImageResponse]
    created_at: datetime.datetime
    updated_at: datetime.datetime
