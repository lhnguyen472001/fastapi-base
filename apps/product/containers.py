"""Dependency injection container for the Product module."""

from dependency_injector import containers, providers

from apps.product.repositories import (
    ProductCategoryRepository,
    ProductImageRepository,
    ProductRepository,
)
from apps.product.services import ProductCategoryService, ProductService


class ProductContainer(containers.DeclarativeContainer):
    """Wires Product repositories -> services and activates @inject in routes."""

    wiring_config = containers.WiringConfiguration(modules=["apps.product.routes"])

    product_repository = providers.Factory(ProductRepository)
    product_category_repository = providers.Factory(ProductCategoryRepository)
    product_image_repository = providers.Factory(ProductImageRepository)

    product_category_service = providers.Factory(
        ProductCategoryService,
        repository=product_category_repository,
    )
    product_service = providers.Factory(
        ProductService,
        repository=product_repository,
        category_repository=product_category_repository,
        image_repository=product_image_repository,
    )


# Module-level instance so the wiring runs on import.
product_container = ProductContainer()
