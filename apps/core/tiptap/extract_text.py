"""ProseMirror JSON → plaintext extraction.

The plaintext form is what feeds the Postgres ``tsvector`` column on
:class:`apps.blog.models.Post` (FTS) and powers the embedding-pipeline
content hash. The walker recurses through :class:`dict`-shaped nodes
and concatenates ``text`` leaves with sensible whitespace boundaries
between block-level nodes.
"""

from __future__ import annotations

from typing import Any

from apps.core.tiptap.constants import BLOCK_TYPES, INLINE_BOUNDARY_TYPES


def extract_text(doc: dict[str, Any] | None) -> str:
    """Walk a ProseMirror document and return its plaintext form.

    Args:
        doc: The Tiptap document JSON (root ``{"type": "doc", "content": [...]}``).
            Falsy / malformed inputs return an empty string.

    Returns:
        Whitespace-collapsed plaintext suitable for FTS or hashing.
    """
    if not doc or not isinstance(doc, dict):
        return ""

    parts: list[str] = []
    _walk(doc, parts)

    # Collapse runs of whitespace and trim.
    return " ".join("".join(parts).split())


def _walk(node: Any, out: list[str]) -> None:
    """Recursive walker — appends text chunks plus boundaries to ``out``."""
    if not isinstance(node, dict):
        return

    node_type = node.get("type")

    # Text leaves.
    if node_type == "text":
        text = node.get("text")
        if isinstance(text, str):
            out.append(text)
        return

    # Inline boundary (e.g., ``<br>``).
    if node_type in INLINE_BOUNDARY_TYPES:
        out.append(" ")
        return

    children = node.get("content")
    if isinstance(children, list):
        for child in children:
            _walk(child, out)

    # Add a newline after block-level nodes so paragraphs / list items
    # remain separated in the resulting plaintext.
    if node_type in BLOCK_TYPES:
        out.append("\n")
