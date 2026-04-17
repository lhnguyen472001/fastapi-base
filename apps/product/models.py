"""Product module ORM models: Product, ProductCategory, ProductImage."""

import uuid
from decimal import Decimal

from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.schema import CheckConstraint, ForeignKey, Index
from sqlalchemy.sql.sqltypes import (
    Boolean,
    Numeric,
    String,
    Text,
)

from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.model import HasSoftDeletedMixin


class ProductCategory(UUIDAuditBase, HasSoftDeletedMixin):
    """Product category — admin-managed taxonomy for products."""

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(default=0, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(
        "Product",
        back_populates="category",
        lazy="raise",
    )


class Product(UUIDAuditBase, HasSoftDeletedMixin):
    """Product sold by the farm (e.g. tea, rice, herbal goods)."""

    __table_args__ = (
        CheckConstraint("retail_price >= 0", name="ck_products_retail_price_non_negative"),
        CheckConstraint(
            "wholesale_price IS NULL OR wholesale_price >= 0",
            name="ck_products_wholesale_price_non_negative",
        ),
        Index("ix_products_available_category", "is_available", "category_id"),
        Index(
            "ix_products_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(280), unique=True, nullable=False, index=True)

    # Long-form descriptive fields (Vietnamese, free-form).
    ingredients: Mapped[str | None] = mapped_column(Text, nullable=True)
    production: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing — VND only. wholesale_price NULL means "Liên hệ".
    retail_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    wholesale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_categorys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    display_order: Mapped[int] = mapped_column(default=0, nullable=False)

    # PostgreSQL full-text search vector (populated via trigger/raw SQL in migration).
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    category: Mapped["ProductCategory | None"] = relationship(
        "ProductCategory",
        back_populates="products",
        lazy="raise",
    )
    images: Mapped[list["ProductImage"]] = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.display_order",
        lazy="raise",
    )


class ProductImage(UUIDAuditBase):
    """Image attached to a product (external URL only)."""

    __table_args__ = (Index("ix_product_images_product_order", "product_id", "display_order"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_order: Mapped[int] = mapped_column(default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="images",
        lazy="raise",
    )
