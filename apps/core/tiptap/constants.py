"""Tiptap module constants — sanitize allowlists, walker boundaries, render marks.

Single source of truth for every literal the renderer / extractor /
sanitizer rely on, per the project rule that module-level constants live
in a dedicated ``constants.py`` typed with :data:`typing.Final`.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Sanitizer allowlists
# ---------------------------------------------------------------------------

# Post allowlist — wide enough for long-form blog posts (headings, lists,
# blockquotes, images, code blocks, tables).
POST_HTML_ALLOWED_TAGS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    },
)

POST_HTML_ALLOWED_ATTRIBUTES: Final[dict[str, set[str]]] = {
    # ``rel`` is managed by nh3 when ``link_rel`` is set in :func:`sanitize_html`.
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "code": {"class"},
    "pre": {"class"},
    "span": {"class"},
}

# Comment allowlist — much narrower; bans images, headings, tables.
COMMENT_HTML_ALLOWED_TAGS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "em",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "strong",
        "u",
        "ul",
    },
)

COMMENT_HTML_ALLOWED_ATTRIBUTES: Final[dict[str, set[str]]] = {
    # ``rel`` is managed by nh3 when ``link_rel`` is set in :func:`sanitize_html`.
    "a": {"href", "title"},
    "code": {"class"},
    "pre": {"class"},
}

# Only http(s) and mailto: are safe link schemes; nh3 also drops javascript:
# and data: by default at the parser level, but we pin the allowlist
# explicitly for clarity.
ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "mailto"})

# Auto-applied ``rel`` attribute on every external link.
LINK_REL: Final[str] = "noopener noreferrer nofollow"

# ---------------------------------------------------------------------------
# Plaintext extractor walker boundaries
# ---------------------------------------------------------------------------

# Block-level node types — a newline boundary is inserted after them so the
# resulting plaintext mirrors how a reader would consume the document.
BLOCK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "blockquote",
        "bulletList",
        "codeBlock",
        "doc",
        "heading",
        "horizontalRule",
        "listItem",
        "orderedList",
        "paragraph",
        "table",
        "tableCell",
        "tableHeader",
        "tableRow",
    },
)

# Inline boundary nodes — a single space is sufficient.
INLINE_BOUNDARY_TYPES: Final[frozenset[str]] = frozenset({"hardBreak"})

# ---------------------------------------------------------------------------
# Renderer marks
# ---------------------------------------------------------------------------

# Mark → (open, close) HTML wrapper. Anchor (``link``) is handled separately
# in the renderer so the URL ends up inside the open tag.
MARK_WRAPPERS: Final[dict[str, tuple[str, str]]] = {
    "bold": ("<strong>", "</strong>"),
    "italic": ("<em>", "</em>"),
    "underline": ("<u>", "</u>"),
    "strike": ("<s>", "</s>"),
    "code": ("<code>", "</code>"),
}
