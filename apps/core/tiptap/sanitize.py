"""HTML sanitization for Tiptap-rendered content.

Allowlists and URL scheme rules live in
:mod:`apps.core.tiptap.constants` per the project's centralized-config
rule. This module re-exports the public names so existing import paths
(``apps.core.tiptap.sanitize.POST_HTML_ALLOWED_TAGS`` etc.) keep working.

The sanitizer always uses :mod:`nh3` (Rust port of Mozilla's ammonia),
which guarantees a clean output: ``<script>``, ``on*`` handlers, and
``javascript:`` URLs are stripped regardless of the allowlist.
"""

from __future__ import annotations

import nh3

from apps.core.tiptap.constants import (
    ALLOWED_URL_SCHEMES,
    COMMENT_HTML_ALLOWED_ATTRIBUTES,
    COMMENT_HTML_ALLOWED_TAGS,
    LINK_REL,
    POST_HTML_ALLOWED_ATTRIBUTES,
    POST_HTML_ALLOWED_TAGS,
)

__all__ = (
    "COMMENT_HTML_ALLOWED_ATTRIBUTES",
    "COMMENT_HTML_ALLOWED_TAGS",
    "POST_HTML_ALLOWED_ATTRIBUTES",
    "POST_HTML_ALLOWED_TAGS",
    "sanitize_html",
)


def sanitize_html(
    html: str,
    *,
    allowed_tags: frozenset[str] = POST_HTML_ALLOWED_TAGS,
    allowed_attributes: dict[str, set[str]] | None = None,
) -> str:
    """Sanitize HTML using ``nh3``.

    Args:
        html: The raw HTML string to sanitize.
        allowed_tags: Set of tag names permitted. Defaults to the post allowlist.
        allowed_attributes: Per-tag attribute allowlist. Defaults to the
            post attribute allowlist.

    Returns:
        Cleaned HTML safe to serve to browsers.
    """
    if allowed_attributes is None:
        allowed_attributes = POST_HTML_ALLOWED_ATTRIBUTES

    return nh3.clean(
        html,
        tags=set(allowed_tags),
        attributes=allowed_attributes,
        url_schemes=set(ALLOWED_URL_SCHEMES),
        link_rel=LINK_REL,
    )
