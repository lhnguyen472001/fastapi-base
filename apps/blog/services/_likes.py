"""Post-like service — like / unlike / liker-list / liked-by-me probe.

Method bodies for the like flow land in Phase 3 (US1) of the
implementation plan (specs/003-post-likes-comments). Phase 2 ships this
file as a stub so the DI container can wire ``post_like_service`` and so
the new ORM models register their import chain cleanly.

See plan.md §"Phase 3" for the full task list mapped to this module.
"""

from __future__ import annotations

from apps.blog.repositories import PostLikeRepository, PostRepository


class PostLikeService:
    """Like flow on a post.

    Constructor signature is finalized in Phase 3 (T028) once the
    repository methods exist. Phase 2 ships an empty class so the
    container wiring + import graph is testable.
    """

    def __init__(
        self,
        repository: PostLikeRepository,
        post_repository: PostRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository
