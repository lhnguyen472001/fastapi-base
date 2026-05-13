"""Moderation service — pending queue, approve / reject, moderator-delete,
reconcile-engagement-counters.

Method bodies land in Phase 7 (US5) of the implementation plan
(specs/003-post-likes-comments). Phase 2 ships this file as a stub so
the DI container can wire ``post_comment_moderation_service``.
"""

from __future__ import annotations

from apps.blog.repositories import (
    PostCommentModerationRepository,
    PostRepository,
)


class PostCommentModerationService:
    """Moderator-side comment lifecycle service.

    Constructor signature is finalized in Phase 7 once the repository
    methods exist. Phase 2 ships an empty class so the container wiring
    + import graph is testable.
    """

    def __init__(
        self,
        repository: PostCommentModerationRepository,
        post_repository: PostRepository,
    ) -> None:
        self.repository = repository
        self.post_repository = post_repository
