"""Blog module exceptions."""

from __future__ import annotations

import enum

from fastapi import status as http_status

from apps.core.exceptions.base import BackendError
from apps.core.exceptions.errors import BadRequestError, ConflictError, NotFoundError


class BlogErrorCodes(enum.StrEnum):
    """Stable error codes for the blog module."""

    BLOG001 = "BLOG001"  # Post not found
    BLOG002 = "BLOG002"  # Post slug already exists in this workspace
    BLOG003 = "BLOG003"  # Category not found
    BLOG004 = "BLOG004"  # Category slug already exists in this workspace
    BLOG005 = "BLOG005"  # Tag not found
    BLOG006 = "BLOG006"  # Tag slug already exists in this workspace
    BLOG007 = "BLOG007"  # Invalid post status transition
    BLOG008 = "BLOG008"  # Too many tags attached to the post
    BLOG009 = "BLOG009"  # Cross-resource workspace mismatch (e.g. tag/category from another workspace)
    BLOG019 = "BLOG019"  # Post cannot be published — content readiness check failed
    BLOG020 = "BLOG020"  # Autosave attempted on a post in an unsupported status (e.g. ARCHIVED)
    BLOG021 = "BLOG021"  # Autosave subsystem unavailable (Redis disabled / unreachable)


class PostNotFoundError(NotFoundError):
    """Raised when a post cannot be located in the active workspace."""

    code: str = BlogErrorCodes.BLOG001

    def __init__(self, *, message: str = "Post not found.") -> None:
        super().__init__(code=self.code, message=message)


class PostSlugConflictError(ConflictError):
    """Raised when a post slug collides within a workspace."""

    code: str = BlogErrorCodes.BLOG002

    def __init__(self, *, message: str = "Post slug already exists in this workspace.") -> None:
        super().__init__(code=self.code, message=message)


class CategoryNotFoundError(NotFoundError):
    """Raised when a category cannot be located in the active workspace."""

    code: str = BlogErrorCodes.BLOG003

    def __init__(self, *, message: str = "Category not found.") -> None:
        super().__init__(code=self.code, message=message)


class CategorySlugConflictError(ConflictError):
    """Raised when a category slug collides within a workspace."""

    code: str = BlogErrorCodes.BLOG004

    def __init__(self, *, message: str = "Category slug already exists in this workspace.") -> None:
        super().__init__(code=self.code, message=message)


class TagNotFoundError(NotFoundError):
    """Raised when a tag cannot be located in the active workspace."""

    code: str = BlogErrorCodes.BLOG005

    def __init__(self, *, message: str = "Tag not found.") -> None:
        super().__init__(code=self.code, message=message)


class TagSlugConflictError(ConflictError):
    """Raised when a tag slug collides within a workspace."""

    code: str = BlogErrorCodes.BLOG006

    def __init__(self, *, message: str = "Tag slug already exists in this workspace.") -> None:
        super().__init__(code=self.code, message=message)


class PostInvalidStatusTransitionError(BadRequestError):
    """Raised when ``publish``/``unpublish``/``archive`` is called from a forbidden state."""

    code: str = BlogErrorCodes.BLOG007

    def __init__(self, *, message: str = "Invalid post status transition.") -> None:
        super().__init__(code=self.code, message=message)


class PostTooManyTagsError(BadRequestError):
    """Raised when the request would exceed :data:`MAX_TAGS_PER_POST`."""

    code: str = BlogErrorCodes.BLOG008

    def __init__(self, *, message: str = "Too many tags attached to the post.") -> None:
        super().__init__(code=self.code, message=message)


class BlogResourceWorkspaceMismatchError(BadRequestError):
    """Raised when a referenced category/tag/author belongs to a different workspace."""

    code: str = BlogErrorCodes.BLOG009

    def __init__(self, *, message: str = "Referenced resource belongs to a different workspace.") -> None:
        super().__init__(code=self.code, message=message)


class PostPublishContentError(BadRequestError):
    """Raised when ``/publish`` is called on a post that fails readiness checks (empty body, etc.)."""

    code: str = BlogErrorCodes.BLOG019

    def __init__(self, *, message: str = "Post is not ready to publish.") -> None:
        super().__init__(code=self.code, message=message)


class PostAutosaveOnArchivedError(BadRequestError):
    """Raised when autosave targets an archived post; archived posts must be unpublished first."""

    code: str = BlogErrorCodes.BLOG020

    def __init__(self, *, message: str = "Autosave is not allowed on archived posts.") -> None:
        super().__init__(code=self.code, message=message)


class PostAutosaveUnavailableError(BackendError):
    """Raised when the autosave subsystem (Redis) is disabled or unreachable.

    Surfaces as 503 because the feature presumes a functioning Redis; the
    plan explicitly rejected the silent-fallback variant.
    """

    code: str = BlogErrorCodes.BLOG021
    status_code: int = http_status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, *, message: str = "Autosave is currently unavailable.") -> None:
        super().__init__(message=message)
