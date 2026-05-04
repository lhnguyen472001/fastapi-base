"""Blog-module constants.

Module-level tunables typed with :data:`typing.Final` per the project's
centralized-config rule.
"""

from __future__ import annotations

import re
from typing import Final

# Slug pattern shared by Post / Category / Tag — URL-safe lowercase,
# alphanumeric + hyphen, must start and end with an alphanumeric.
BLOG_SLUG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,278}[a-z0-9])?$")

POST_TITLE_MAX_LENGTH: Final[int] = 255
POST_SLUG_MAX_LENGTH: Final[int] = 280
POST_EXCERPT_MAX_LENGTH: Final[int] = 500
POST_COVER_IMAGE_URL_MAX_LENGTH: Final[int] = 1024
POST_META_TITLE_MAX_LENGTH: Final[int] = 200
POST_META_DESCRIPTION_MAX_LENGTH: Final[int] = 320

CATEGORY_NAME_MAX_LENGTH: Final[int] = 150
CATEGORY_SLUG_MAX_LENGTH: Final[int] = 160
CATEGORY_DESCRIPTION_MAX_LENGTH: Final[int] = 500

TAG_NAME_MAX_LENGTH: Final[int] = 80
TAG_SLUG_MAX_LENGTH: Final[int] = 90

MAX_TAGS_PER_POST: Final[int] = 10

# hero_quote — fixed JSONB shape: {"text": str, "author": str|None, "source_url": str|None}
HERO_QUOTE_TEXT_MAX_LENGTH: Final[int] = 1000
HERO_QUOTE_AUTHOR_MAX_LENGTH: Final[int] = 200
HERO_QUOTE_SOURCE_URL_MAX_LENGTH: Final[int] = 1024

# Default empty Tiptap document (matches the column DEFAULT in the migration).
EMPTY_TIPTAP_DOC: Final[dict[str, object]] = {"type": "doc", "content": []}

# Approximate words-per-minute used to compute ``reading_minutes`` from
# the plaintext extract.
WORDS_PER_MINUTE: Final[int] = 200
