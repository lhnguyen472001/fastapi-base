"""Blog module repositories — pure data access, all queries workspace-scoped.

Phase C.1 split the original flat ``apps/blog/repositories.py`` (1204
LOC, over the 800-LOC project cap) into one sub-module per aggregate
root. External imports keep working unchanged:

    from apps.blog.repositories import PostRepository  # still valid

Each ``_*.py`` module owns one (or in two cases, the join-table for
one) :class:`apps.core.database.repository.BaseSQLAlchemyRepository`
subclass and only the imports that subclass uses.
"""

from __future__ import annotations

from apps.blog.repositories._category import CategoryRepository
from apps.blog.repositories._post import PostRepository
from apps.blog.repositories._post_comment import PostCommentRepository
from apps.blog.repositories._post_comment_moderation import (
    PostCommentModerationRepository,
)
from apps.blog.repositories._post_content import PostContentRepository
from apps.blog.repositories._post_like import PostLikeRepository
from apps.blog.repositories._post_tag import PostTagRepository
from apps.blog.repositories._post_version import PostVersionRepository
from apps.blog.repositories._tag import TagRepository

__all__ = (
    "CategoryRepository",
    "PostCommentModerationRepository",
    "PostCommentRepository",
    "PostContentRepository",
    "PostLikeRepository",
    "PostRepository",
    "PostTagRepository",
    "PostVersionRepository",
    "TagRepository",
)
