"""Blog module enums — post lifecycle status."""

from __future__ import annotations

import enum


class PostStatus(enum.StrEnum):
    """Post lifecycle states.

    * ``DRAFT`` — author work-in-progress; not visible to public read.
    * ``PUBLISHED`` — visible at the public read-by-slug endpoint.
      ``published_at`` is set when the transition happens; clearing it on
      unpublish flips the status back to ``DRAFT``.
    * ``ARCHIVED`` — was published, now hidden, but kept for permalink
      consistency / audit. Public read returns 404.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
