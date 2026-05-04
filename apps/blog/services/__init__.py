"""Blog services package — re-exports the three public services.

The package decomposition mirrors :mod:`apps.auth.services`:

* :mod:`._categories` — :class:`CategoryService`
* :mod:`._tags` — :class:`TagService`
* :mod:`._posts` — :class:`PostService` (composes :class:`._autosave._PostAutosaveMixin`)

Importers should keep using ``from apps.blog.services import ...``.
"""

from apps.blog.services._categories import CategoryService
from apps.blog.services._posts import PostService
from apps.blog.services._tags import TagService

__all__ = ("CategoryService", "PostService", "TagService")
