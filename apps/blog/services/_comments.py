"""Post-comment service — auth + anonymous create, list, reply, edit, self-delete.

Method bodies land in Phase 4 (US2) and Phases 5+6 (US3/US4) of the
implementation plan (specs/003-post-likes-comments). Phase 2 ships this
file as a stub so the DI container can wire ``post_comment_service``.
"""

from __future__ import annotations

from apps.blog.repositories import PostCommentRepository, PostRepository


class PostCommentService:
    """Comment lifecycle service (auth + anonymous; create / read / edit / self-delete).

    Constructor signature is finalized in Phases 4/5/6 once the
    repository methods exist. Phase 2 ships an empty class so the
    container wiring + import graph is testable.
    """

    def __init__(
        self,
        repository: PostCommentRepository,
        post_repository: PostRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository
