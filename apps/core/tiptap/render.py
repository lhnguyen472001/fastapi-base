"""ProseMirror JSON → HTML renderer.

A small, deterministic renderer covering the node + mark surface used by
the default Tiptap ``StarterKit`` plus images and links. The output is
always passed through :func:`apps.core.tiptap.sanitize.sanitize_html`
before persistence — the renderer does not need to defend against
hostile attribute values; the sanitizer is the bottleneck.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any, Final

from apps.core.tiptap.constants import MARK_WRAPPERS


def render_html(doc: dict[str, Any] | None) -> str:
    """Render a ProseMirror document to HTML.

    Args:
        doc: ``{"type": "doc", "content": [...]}``. Falsy inputs render as ``""``.

    Returns:
        HTML string. Caller MUST sanitize before persistence.
    """
    if not doc or not isinstance(doc, dict):
        return ""
    return _render_node(doc)


# ---------------------------------------------------------------------------
# core walkers
# ---------------------------------------------------------------------------


def _render_children(node: dict[str, Any]) -> str:
    children = node.get("content")
    if not isinstance(children, list):
        return ""
    return "".join(_render_node(child) for child in children)


def _render_text(node: dict[str, Any]) -> str:
    raw = node.get("text", "")
    if not isinstance(raw, str):
        return ""
    text = html.escape(raw)
    marks = node.get("marks")
    if not isinstance(marks, list):
        return text
    return _wrap_with_marks(text, marks)


def _wrap_with_marks(text: str, marks: list[Any]) -> str:
    open_tags: list[str] = []
    close_tags: list[str] = []
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        if mark_type == "link":
            attrs = mark.get("attrs", {}) or {}
            href = html.escape(str(attrs.get("href", "")), quote=True)
            open_tags.append(f'<a href="{href}">')
            close_tags.append("</a>")
            continue
        wrapper = MARK_WRAPPERS.get(str(mark_type))
        if wrapper is None:
            continue
        open_tags.append(wrapper[0])
        close_tags.append(wrapper[1])
    # Close in reverse order so nesting is balanced.
    return "".join(open_tags) + text + "".join(reversed(close_tags))


def _render_image(attrs: dict[str, Any]) -> str:
    src = html.escape(str(attrs.get("src", "")), quote=True)
    if not src:
        return ""
    alt = html.escape(str(attrs.get("alt", "")), quote=True)
    parts = [f'<img src="{src}" alt="{alt}"']
    width = attrs.get("width")
    if isinstance(width, (int, str)):
        parts.append(f' width="{html.escape(str(width), quote=True)}"')
    height = attrs.get("height")
    if isinstance(height, (int, str)):
        parts.append(f' height="{html.escape(str(height), quote=True)}"')
    parts.append(">")
    return "".join(parts)


# ---------------------------------------------------------------------------
# per-node helpers + dispatch table
# ---------------------------------------------------------------------------


def _wrap(tag: str) -> Callable[[dict[str, Any]], str]:
    """Build a renderer that wraps children in a fixed tag pair."""

    def _render(node: dict[str, Any]) -> str:
        return f"<{tag}>{_render_children(node)}</{tag}>"

    return _render


def _render_heading(node: dict[str, Any]) -> str:
    level = node.get("attrs", {}).get("level", 1)
    if not isinstance(level, int) or level < 1 or level > 6:
        level = 1
    return f"<h{level}>{_render_children(node)}</h{level}>"


def _render_code_block(node: dict[str, Any]) -> str:
    # ``codeBlock`` content is plaintext only — escape and wrap.
    inner = "".join(_render_text(child) for child in node.get("content", []) if isinstance(child, dict))
    return f"<pre><code>{inner}</code></pre>"


def _render_image_node(node: dict[str, Any]) -> str:
    attrs = node.get("attrs", {}) or {}
    return _render_image(attrs)


def _render_hr(_node: dict[str, Any]) -> str:
    return "<hr>"


def _render_br(_node: dict[str, Any]) -> str:
    return "<br>"


# Dispatch table — single lookup, easy to extend.
_NODE_RENDERERS: Final[dict[str, Callable[[dict[str, Any]], str]]] = {
    "doc": _render_children,
    "text": _render_text,
    "paragraph": _wrap("p"),
    "heading": _render_heading,
    "blockquote": _wrap("blockquote"),
    "bulletList": _wrap("ul"),
    "orderedList": _wrap("ol"),
    "listItem": _wrap("li"),
    "codeBlock": _render_code_block,
    "horizontalRule": _render_hr,
    "hardBreak": _render_br,
    "image": _render_image_node,
}


def _render_node(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    renderer = _NODE_RENDERERS.get(str(node.get("type", "")))
    if renderer is None:
        # Unknown node — fall through to children so we don't drop user content.
        return _render_children(node)
    return renderer(node)
