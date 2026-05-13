"""Blog module exceptions."""

from __future__ import annotations

import enum

from fastapi import status as http_status

from apps.core.exceptions.base import BackendError
from apps.core.exceptions.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError


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
    POSTV001 = "POSTV001"  # Post version not found
    POSTV002 = "POSTV002"  # Compare rejected: versions belong to different posts or from == to
    POSTV003 = "POSTV003"  # Post version insert conflict: unique(post_id, version) retry budget exhausted
    POSTV004 = "POSTV004"  # Post version content unreadable (decompression / decode failure)
    POSTV005 = "POSTV005"  # Diff payload exceeds POST_VERSION_DIFF_MAX_BYTES


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


class PostVersionNotFoundError(NotFoundError):
    """Raised when a (post, version) pair does not exist."""

    code: str = BlogErrorCodes.POSTV001

    def __init__(self, *, message: str = "Post version not found.") -> None:
        super().__init__(code=self.code, message=message)


class PostVersionMismatchError(BadRequestError):
    """Raised when ``/compare`` is called with versions that do not both belong to the same post,
    or with ``from == to``.
    """

    code: str = BlogErrorCodes.POSTV002

    def __init__(self, *, message: str = "Both versions must belong to the same post and differ.") -> None:
        super().__init__(code=self.code, message=message)


class PostVersionConflictError(ConflictError):
    """Raised when the version-row insert retry budget is exhausted under contention."""

    code: str = BlogErrorCodes.POSTV003

    def __init__(self, *, message: str = "Could not assign a unique version number; please retry.") -> None:
        super().__init__(code=self.code, message=message)


class PostVersionContentUnreadableError(BackendError):
    """Raised when stored compressed content cannot be decompressed or decoded.

    Surfaces as 500: the stored row is corrupt or written with an
    incompatible codec; not a user error.
    """

    code: str = BlogErrorCodes.POSTV004
    status_code: int = http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, *, message: str = "Version content is unreadable.") -> None:
        super().__init__(message=message)


class PostVersionDiffTooLargeError(BackendError):
    """Raised when the combined plaintext payload of two compared versions exceeds
    :data:`apps.blog.constants.POST_VERSION_DIFF_MAX_BYTES`.

    Surfaces as 413 Payload Too Large.
    """

    code: str = BlogErrorCodes.POSTV005
    status_code: int = http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def __init__(self, *, message: str = "Combined version content exceeds the diff size limit.") -> None:
        super().__init__(message=message)


# ---------------------------------------------------------------------------
# Engagement (post_likes + post_comments) error codes + classes
# ---------------------------------------------------------------------------


class PostEngagementErrorCodes(enum.StrEnum):
    """Stable error codes for the post engagement (likes + comments) surface."""

    ENG001 = "ENG001"  # Post is not eligible for engagement (soft-deleted / archived)
    ENG002 = "ENG002"  # Anonymous comments disabled on this workspace
    ENG003 = "ENG003"  # Comment not found (or not visible to caller)
    ENG004 = "ENG004"  # Comment body fails validation (length, whitespace-only)
    ENG005 = "ENG005"  # Reply nesting exceeds depth 1
    ENG006 = "ENG006"  # Reply parent belongs to a different post
    ENG007 = "ENG007"  # Edit attempted after the edit window expired
    ENG008 = "ENG008"  # Caller is not the author of the comment
    ENG009 = "ENG009"  # Anonymous-authored comment is not editable/self-deletable
    ENG010 = "ENG010"  # Moderation action targets a comment not in 'pending' state


class PostEngagementClosedError(ConflictError):
    """Raised when a like/comment mutation targets a post that is no
    longer open for engagement (soft-deleted or archived). FR-008 / FR-015.
    """

    code: str = PostEngagementErrorCodes.ENG001

    def __init__(self, *, message: str = "Post is not accepting engagement.") -> None:
        super().__init__(code=self.code, message=message)


class AnonymousCommentsDisabledError(NotFoundError):
    """Raised when an anonymous comment is submitted to a workspace whose
    ``allow_anonymous_comments`` flag is OFF. Surfaces as 404 — same shape
    as a not-found — to avoid leaking whether the flag is on or off
    (FR-010b).
    """

    code: str = PostEngagementErrorCodes.ENG002

    def __init__(self, *, message: str = "Post not found.") -> None:
        super().__init__(code=self.code, message=message)


class CommentNotFoundError(NotFoundError):
    """Raised when a comment cannot be located, or when the caller is not
    authorized to see the comment (cross-workspace masking)."""

    code: str = PostEngagementErrorCodes.ENG003

    def __init__(self, *, message: str = "Comment not found.") -> None:
        super().__init__(code=self.code, message=message)


class CommentBodyInvalidError(BadRequestError):
    """Raised when a comment body fails validation (empty after trim,
    whitespace-only, or exceeds the max-length limit). FR-011."""

    code: str = PostEngagementErrorCodes.ENG004

    def __init__(self, *, message: str = "Comment body is invalid.") -> None:
        super().__init__(code=self.code, message=message)


class CommentNestingTooDeepError(BadRequestError):
    """Raised when a reply attempts to nest beneath another reply
    (depth > 1). FR-013."""

    code: str = PostEngagementErrorCodes.ENG005

    def __init__(
        self,
        *,
        message: str = "Replies cannot be nested more than one level deep.",
    ) -> None:
        super().__init__(code=self.code, message=message)


class CommentParentPostMismatchError(BadRequestError):
    """Raised when a reply's parent comment belongs to a different post
    than the path's post_id. FR-014."""

    code: str = PostEngagementErrorCodes.ENG006

    def __init__(
        self,
        *,
        message: str = "Reply parent does not belong to this post.",
    ) -> None:
        super().__init__(code=self.code, message=message)


class CommentEditWindowExpiredError(ForbiddenError):
    """Raised when the author attempts to edit their comment after the
    configured window has passed (default 15 minutes). FR-019."""

    code: str = PostEngagementErrorCodes.ENG007

    def __init__(
        self,
        *,
        message: str = "Edit window has expired for this comment.",
    ) -> None:
        super().__init__(code=self.code, message=message)


class CommentAuthorForbiddenError(ForbiddenError):
    """Raised when a caller attempts to edit or self-delete a comment
    they did not author. FR-021."""

    code: str = PostEngagementErrorCodes.ENG008

    def __init__(
        self,
        *,
        message: str = "You may only edit or delete your own comment.",
    ) -> None:
        super().__init__(code=self.code, message=message)


class AnonymousAuthorImmutableError(ForbiddenError):
    """Raised when any caller attempts to edit or self-delete an
    anonymous-authored comment. Anonymous comments have no platform
    identity that can authenticate a self-edit (Q5 round 1)."""

    code: str = PostEngagementErrorCodes.ENG009

    def __init__(
        self,
        *,
        message: str = "Anonymous comments cannot be edited or self-deleted.",
    ) -> None:
        super().__init__(code=self.code, message=message)


class CommentNotPendingError(ConflictError):
    """Raised when a moderator approval / rejection action targets a
    comment that is not in the ``pending`` state. FR-010d."""

    code: str = PostEngagementErrorCodes.ENG010

    def __init__(
        self,
        *,
        message: str = "Moderation action requires a pending comment.",
    ) -> None:
        super().__init__(code=self.code, message=message)
