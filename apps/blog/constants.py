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

# ---------------------------------------------------------------------------
# Cache (read-through cache for public post detail responses)
# ---------------------------------------------------------------------------

# Versioned prefix so we can rev the key namespace cleanly when the cached
# response shape changes (e.g. PostDetailResponse gains a field).
POST_CACHE_KEY_PREFIX: Final[str] = "blog:post:v1"
POST_CACHE_DETAIL_TTL: Final[int] = 300
POST_CACHE_LIST_TTL: Final[int] = 60

# ---------------------------------------------------------------------------
# Autosave (Redis-first write-behind for the Tiptap body)
# ---------------------------------------------------------------------------

AUTOSAVE_KEY_PREFIX: Final[str] = "blog:autosave:post"
AUTOSAVE_DIRTY_SET: Final[str] = "blog:autosave:dirty"
AUTOSAVE_LOCK_PREFIX: Final[str] = "blog:autosave:lock"
AUTOSAVE_TTL_SECONDS: Final[int] = 7 * 24 * 3600
AUTOSAVE_FLUSH_LOCK_TTL: Final[int] = 30
AUTOSAVE_SWEEP_INTERVAL: Final[float] = 2.0
AUTOSAVE_SWEEP_BATCH: Final[int] = 50
AUTOSAVE_RATE_LIMIT: Final[str] = "60/minute"

# Sweeper leader election — every uvicorn worker spawns a sweeper task but
# only the holder of this Redis lock runs ``sweep_once`` each tick. TTL is
# the budget for a stalled leader: takeover happens within
# ``AUTOSAVE_SWEEPER_LEADER_TTL + AUTOSAVE_SWEEP_INTERVAL`` seconds.
AUTOSAVE_SWEEPER_LEADER_KEY: Final[str] = "blog:autosave:sweeper:leader"
AUTOSAVE_SWEEPER_LEADER_TTL: Final[int] = 5
# Emit one ``heartbeat`` log line every N leader-ticks so an absence of
# events is an actionable signal that no worker is currently leader.
# 15 ticks x 2s interval = ~30s between heartbeats.
AUTOSAVE_HEARTBEAT_LOG_EVERY: Final[int] = 15

# ---------------------------------------------------------------------------
# Publish readiness
# ---------------------------------------------------------------------------

MIN_PUBLISH_BODY_CHARS: Final[int] = 50
