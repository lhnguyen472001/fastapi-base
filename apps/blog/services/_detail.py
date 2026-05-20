"""Pure projection: ORM :class:`Post` → :class:`PostDetailResponse`.

Lives at module scope so :class:`PostService` and the autosave service can
both call it without one having to import from the other (which would
re-introduce the inheritance coupling Phase B is dismantling).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.blog.constants import EMPTY_TIPTAP_DOC
from apps.blog.schemas import (
    CategoryResponse,
    PostDetailResponse,
    PostResponse,
    TagResponse,
)

if TYPE_CHECKING:
    from apps.blog.models import Post


def build_post_detail(post: Post) -> PostDetailResponse:
    """Render an ORM :class:`Post` into a :class:`PostDetailResponse`.

    Assumes ``post.category`` and ``post.tags`` are eager-loaded; the
    function never touches the session. When ``post.content`` is missing
    (legacy data only — :meth:`PostService.create` writes it inline) the
    empty Tiptap doc is substituted so the response shape stays stable.
    """
    base = PostResponse.model_validate(post).model_dump()
    content = post.content
    return PostDetailResponse(
        **base,
        content_json=content.content_json if content is not None else dict(EMPTY_TIPTAP_DOC),
        content_html=content.content_html if content is not None else "",
        content_text=content.content_text if content is not None else "",
        category=CategoryResponse.model_validate(post.category) if post.category is not None else None,
        tags=[TagResponse.model_validate(tag) for tag in post.tags],
    )
