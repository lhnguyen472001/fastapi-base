"""Product module exceptions."""

import enum

from apps.core.exceptions.errors import ConflictError, NotFoundError


class ProductErrorCodes(enum.StrEnum):
    """Product module error codes."""

    PRD001 = "PRD001"  # Product not found
    PRD002 = "PRD002"  # Product slug already exists
    PRD003 = "PRD003"  # Product category not found
    PRD004 = "PRD004"  # Product category slug already exists
    PRD005 = "PRD005"  # Product image not found


class ProductNotFoundError(NotFoundError):
    """Raised when a product is not found."""

    code: str = ProductErrorCodes.PRD001

    def __init__(self, *, message: str = "Product not found.") -> None:
        super().__init__(code=self.code, message=message)


class ProductSlugConflictError(ConflictError):
    """Raised when a product slug collides with an existing one."""

    code: str = ProductErrorCodes.PRD002

    def __init__(self, *, message: str = "Product slug already exists.") -> None:
        super().__init__(code=self.code, message=message)


class ProductCategoryNotFoundError(NotFoundError):
    """Raised when a product category is not found."""

    code: str = ProductErrorCodes.PRD003

    def __init__(self, *, message: str = "Product category not found.") -> None:
        super().__init__(code=self.code, message=message)


class ProductCategorySlugConflictError(ConflictError):
    """Raised when a product category slug collides with an existing one."""

    code: str = ProductErrorCodes.PRD004

    def __init__(self, *, message: str = "Product category slug already exists.") -> None:
        super().__init__(code=self.code, message=message)


class ProductImageNotFoundError(NotFoundError):
    """Raised when a product image is not found."""

    code: str = ProductErrorCodes.PRD005

    def __init__(self, *, message: str = "Product image not found.") -> None:
        super().__init__(code=self.code, message=message)
