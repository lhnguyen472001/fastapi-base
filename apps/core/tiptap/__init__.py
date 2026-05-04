"""Server-side Tiptap (ProseMirror) helpers.

The blog feature stores user content as Tiptap's ProseMirror JSON
document. This package exposes three pure functions used by the post and
comment services:

* :func:`apps.core.tiptap.sanitize.sanitize_html` — nh3-backed HTML
  sanitizer with separate allowlists for posts vs. comments.
* :func:`apps.core.tiptap.extract_text.extract_text` — recursive walker
  that produces a plaintext string for full-text search.
* :func:`apps.core.tiptap.render.render_html` — minimal ProseMirror
  → HTML renderer covering the core node and mark types.

Render output is always passed through the sanitizer before persistence.
"""

from apps.core.tiptap.extract_text import extract_text
from apps.core.tiptap.render import render_html
from apps.core.tiptap.sanitize import (
    COMMENT_HTML_ALLOWED_ATTRIBUTES,
    COMMENT_HTML_ALLOWED_TAGS,
    POST_HTML_ALLOWED_ATTRIBUTES,
    POST_HTML_ALLOWED_TAGS,
    sanitize_html,
)

__all__ = (
    "COMMENT_HTML_ALLOWED_ATTRIBUTES",
    "COMMENT_HTML_ALLOWED_TAGS",
    "POST_HTML_ALLOWED_ATTRIBUTES",
    "POST_HTML_ALLOWED_TAGS",
    "extract_text",
    "render_html",
    "sanitize_html",
)
