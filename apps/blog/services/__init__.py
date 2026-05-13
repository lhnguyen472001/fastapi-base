"""Blog services package — re-exports the public services.

The package decomposition mirrors :mod:`apps.auth.services`:

* :mod:`._categories` — :class:`CategoryService`
* :mod:`._tags` — :class:`TagService`
* :mod:`._posts` — :class:`PostService` (composes :class:`._autosave._PostAutosaveMixin`)
* :mod:`._versions` — :class:`PostVersionService`
* :mod:`._likes` — :class:`PostLikeService` (engagement; Phase 3 of 003)
* :mod:`._comments` — :class:`PostCommentService` (engagement; Phase 4 of 003)
* :mod:`._comment_moderation` — :class:`PostCommentModerationService`
  (engagement; Phase 7 of 003)

Importers should keep using ``from apps.blog.services import ...``.
"""

from apps.blog.services._categories import CategoryService
from apps.blog.services._comment_moderation import PostCommentModerationService
from apps.blog.services._comments import PostCommentService
from apps.blog.services._likes import PostLikeService
from apps.blog.services._posts import PostService
from apps.blog.services._tags import TagService
from apps.blog.services._versions import PostVersionService

__all__ = (
    "CategoryService",
    "PostCommentModerationService",
    "PostCommentService",
    "PostLikeService",
    "PostService",
    "PostVersionService",
    "TagService",
)
