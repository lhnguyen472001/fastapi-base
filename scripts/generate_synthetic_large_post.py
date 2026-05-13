"""Generate a synthetic large Tiptap document for SC-001 latency-budget tests.

Writes a single JSON file shaped like a ProseMirror/Tiptap document, sized
at or above the byte target. Used by ``tests/integration/realdb/`` and the
latency-budget harness in ``quickstart.md`` to drive editor saves that
cross ``BLOG_LARGE_CONTENT_BYTES``.

Usage:
    uv run python scripts/generate_synthetic_large_post.py \
        --target-bytes 131072 \
        --output scripts/synthetic_large_post.json

The generator emits text-only paragraphs (no images, marks, or nested
nodes) so the output is deterministic and easy to diff if it ever changes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 480 ASCII chars per paragraph. ASCII keeps the JSON serialization size
# close to the raw text size and avoids multi-byte UTF-8 surprises.
_LOREM_LINE: str = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do "
    "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut "
    "enim ad minim veniam, quis nostrud exercitation ullamco laboris "
    "nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in "
    "reprehenderit in voluptate velit esse cillum dolore eu fugiat "
    "nulla pariatur. Excepteur sint occaecat cupidatat non proident, "
    "sunt in culpa qui officia deserunt mollit anim id est laborum."
)


def build_document(target_bytes: int) -> dict[str, object]:
    """Build a Tiptap doc whose serialized JSON byte length is >= target_bytes."""
    paragraphs: list[dict[str, object]] = []
    while True:
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": _LOREM_LINE}],
            },
        )
        if len(paragraphs) % 32 == 0:
            doc = {"type": "doc", "content": paragraphs}
            if len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) >= target_bytes:
                return doc
        if len(paragraphs) > 100_000:
            msg = f"Generator did not reach target {target_bytes} bytes after 100k paragraphs"
            raise RuntimeError(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-bytes",
        type=int,
        default=128 * 1024,
        help="Minimum serialized byte size of the output (default: 128 KiB).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/synthetic_large_post.json"),
        help="Output JSON path (default: scripts/synthetic_large_post.json).",
    )
    args = parser.parse_args()

    doc = build_document(target_bytes=args.target_bytes)
    payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    args.output.write_text(payload, encoding="utf-8")
    print(f"wrote {args.output} ({len(payload.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
