"""Blog module Pydantic schemas — request validation and response serialization.

Phase C.5 split ``apps/blog/schemas.py`` (582 LOC, near the file cap) into
four cohesive modules. External imports still work unchanged:

    from apps.blog.schemas import PostDetailResponse  # still valid
"""

from __future__ import annotations

from apps.blog.schemas._engagement import (
    CreateAnonymousCommentRequest,
    CreateAuthenticatedCommentRequest,
    EngagementCounters,
    LikerResponse,
    LikeState,
    ListCommentsRequest,
    ListLikersRequest,
    ListPendingCommentsRequest,
    ModerationActionRequest,
    ModeratorPostCommentResponse,
    PostCommentAuthor,
    PostCommentResponse,
    ReconcileEngagementCountersResponse,
    UpdateCommentRequest,
)
from apps.blog.schemas._posts import (
    AutosavePostRequest,
    AutosaveResponse,
    CompareVersionsHunk,
    CompareVersionsResult,
    CreatePostRequest,
    ListPostsRequest,
    ListPostVersionsRequest,
    PostDetailResponse,
    PostResponse,
    PostVersionAuthor,
    PostVersionDetailResponse,
    PostVersionResponse,
    RestorePostVersionRequest,
    RestoreVersionResult,
    UpdatePostRequest,
)
from apps.blog.schemas._shared import HeroQuote
from apps.blog.schemas._taxonomy import (
    CategoryResponse,
    CreateCategoryRequest,
    CreateTagRequest,
    ListCategoriesRequest,
    ListTagsRequest,
    TagResponse,
    UpdateCategoryRequest,
    UpdateTagRequest,
)

__all__ = (
    "AutosavePostRequest",
    "AutosaveResponse",
    "CategoryResponse",
    "CompareVersionsHunk",
    "CompareVersionsResult",
    "CreateAnonymousCommentRequest",
    "CreateAuthenticatedCommentRequest",
    "CreateCategoryRequest",
    "CreatePostRequest",
    "CreateTagRequest",
    "EngagementCounters",
    "HeroQuote",
    "LikeState",
    "LikerResponse",
    "ListCategoriesRequest",
    "ListCommentsRequest",
    "ListLikersRequest",
    "ListPendingCommentsRequest",
    "ListPostVersionsRequest",
    "ListPostsRequest",
    "ListTagsRequest",
    "ModerationActionRequest",
    "ModeratorPostCommentResponse",
    "PostCommentAuthor",
    "PostCommentResponse",
    "PostDetailResponse",
    "PostResponse",
    "PostVersionAuthor",
    "PostVersionDetailResponse",
    "PostVersionResponse",
    "ReconcileEngagementCountersResponse",
    "RestorePostVersionRequest",
    "RestoreVersionResult",
    "TagResponse",
    "UpdateCategoryRequest",
    "UpdateCommentRequest",
    "UpdatePostRequest",
    "UpdateTagRequest",
)
