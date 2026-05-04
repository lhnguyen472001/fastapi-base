"""Tiptap content pipeline helpers shared across post services.

The pipeline runs in two paths:

* The cheap autosave path (text extract + word count + JSON hash) lives
  inline in :meth:`apps.blog.services.PostService.autosave` so it can
  short-circuit before touching Postgres.
* The full path (text + sanitized HTML + hash + word count + reading
  minutes) lives in :func:`compute_content_artifacts` below and runs at
  create / update / publish / flush_one time.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from apps.blog.constants import BLOG_SLUG_PATTERN, MIN_PUBLISH_BODY_CHARS, WORDS_PER_MINUTE
from apps.blog.exceptions import PostPublishContentError
from apps.blog.models import Post
from apps.core.database.utils import slugify
from apps.core.tiptap import extract_text, render_html, sanitize_html


def normalize_slug(slug: str) -> str:
    """Lowercase + strip; reject if it doesn't match the blog slug pattern."""
    candidate = slug.strip().lower()
    if BLOG_SLUG_PATTERN.fullmatch(candidate) is None:
        # Slug came from the schema's min/max length validation but the regex
        # didn't match — typically uppercase or punctuation. Re-slugify and try
        # again so user-supplied "Hello World!" becomes "hello-world".
        candidate = slugify(candidate)
    return candidate


def ensure_publish_ready(post: Post) -> None:
    """Raise :class:`PostPublishContentError` if the post is not ready.

    Readiness rules (kept minimal on purpose):

    * ``title`` must have at least one non-whitespace char.
    * ``content_text`` (the FTS plaintext extract) must be at least
      :data:`MIN_PUBLISH_BODY_CHARS` non-whitespace chars long. We use
      ``content_text`` rather than counting the JSON because it
      excludes Tiptap markup, image alt text, etc.
    """
    if not post.title or not post.title.strip():
        raise PostPublishContentError(message="Post title is required to publish.")

    content_text = post.content.content_text if post.content is not None else ""
    if len(content_text.strip()) < MIN_PUBLISH_BODY_CHARS:
        raise PostPublishContentError(
            message=(f"Post body must be at least {MIN_PUBLISH_BODY_CHARS} characters to publish."),
        )


def compute_content_artifacts(content_json: dict[str, Any]) -> tuple[str, str, str, int, int]:
    """Run the full Tiptap pipeline. Returns ``(text, html, hash, words, minutes)``."""
    text = extract_text(content_json)
    html = sanitize_html(render_html(content_json))
    canonical = json.dumps(content_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    word_count = len(text.split()) if text else 0
    reading_minutes = max(1, math.ceil(word_count / WORDS_PER_MINUTE)) if word_count > 0 else 0
    return text, html, digest, word_count, reading_minutes
