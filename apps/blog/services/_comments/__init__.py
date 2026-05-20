"""Post-comment service package.

Phase C.3 split the original flat ``_comments.py`` (698 LOC) into a
package: helpers stay together in ``_helpers.py``, the
:class:`PostCommentService` class lives in ``_service.py``. External
imports keep working:

    from apps.blog.services._comments import PostCommentService
    from apps.blog.services._comments import _sanitize_comment_body
"""

from __future__ import annotations

from apps.blog.services._comments._helpers import (
    _DELETED_USER_DISPLAY,
    _author_from_row,
    _parse_ip,
    _row_to_response,
    _sanitize_comment_body,
)
from apps.blog.services._comments._service import PostCommentService

__all__ = (
    "_DELETED_USER_DISPLAY",
    "PostCommentService",
    "_author_from_row",
    "_parse_ip",
    "_row_to_response",
    "_sanitize_comment_body",
)
