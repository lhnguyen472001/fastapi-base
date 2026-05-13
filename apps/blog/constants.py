"""Blog-module constants.

Module-level tunables typed with :data:`typing.Final` per the project's
centralized-config rule.
"""

from __future__ import annotations

import re
from typing import Final

from apps.settings import app_settings

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

# ---------------------------------------------------------------------------
# Post version history (post_versions table)
# ---------------------------------------------------------------------------

POST_VERSION_RETENTION_LIMIT: Final[int] = app_settings.blog.post_version_retention_limit
POST_VERSION_COMPRESSION_LEVEL: Final[int] = app_settings.blog.post_version_compression_level
POST_VERSION_SWEEP_INTERVAL: Final[float] = app_settings.blog.post_version_sweep_interval
POST_VERSION_SWEEP_BATCH: Final[int] = 200
POST_VERSION_SWEEPER_LEADER_KEY: Final[str] = "blog:post_version:sweeper:leader"
POST_VERSION_SWEEPER_LEADER_TTL: Final[int] = 1800
POST_VERSION_DIFF_MAX_BYTES: Final[int] = 1_048_576
POST_VERSION_CHANGE_NOTE_MAX_LENGTH: Final[int] = 280
POST_VERSION_INSERT_RETRY_LIMIT: Final[int] = 3

# ---------------------------------------------------------------------------
# Large editor content offload (F-PERF-1)
# ---------------------------------------------------------------------------
# Payloads at or above ``LARGE_CONTENT_BYTES`` run the Tiptap content pipeline
# (render_html + sanitize_html + compress + word/text extraction) on a worker
# thread via ``asyncio.to_thread`` so they do not block the event loop for
# other concurrent requests on the same worker. Below the threshold the
# pipeline runs inline (no thread hand-off cost).
LARGE_CONTENT_BYTES_MIN: Final[int] = 1_024
LARGE_CONTENT_BYTES_MAX: Final[int] = 16 * 1024 * 1024
LARGE_CONTENT_BYTES: Final[int] = app_settings.blog.large_content_bytes

# ---------------------------------------------------------------------------
# Engagement — likes + comments (post_likes + post_comments tables)
# ---------------------------------------------------------------------------

# Comment body limits.
POST_COMMENT_BODY_MAX_LENGTH: Final[int] = 4_000
POST_COMMENT_ANONYMOUS_DISPLAY_NAME_MAX_LENGTH: Final[int] = 80
POST_COMMENT_ANONYMOUS_EMAIL_MAX_LENGTH: Final[int] = 254

# Edit window for authenticated self-edits (seconds since ``created_at``).
POST_COMMENT_EDIT_WINDOW_SECONDS: Final[int] = app_settings.blog.post_comment_edit_window_seconds

# Pending-row TTL: the moderation sweeper purges ``state='pending'`` rows
# older than this many seconds. Default 30 days.
POST_COMMENT_MODERATION_PENDING_TTL_SECONDS: Final[int] = (
    app_settings.blog.post_comment_moderation_pending_ttl_seconds
)
POST_COMMENT_MODERATION_SWEEP_INTERVAL: Final[float] = (
    app_settings.blog.post_comment_moderation_sweep_interval
)
POST_COMMENT_MODERATION_SWEEP_BATCH: Final[int] = 200

# Leader-elect Redis key for the comment-moderation sweeper. Distinct from
# the autosave + post-version sweeper keys so all three can coexist
# without lock contention.
POST_COMMENT_MODERATION_SWEEPER_LEADER_KEY: Final[str] = "blog:comment_moderation:sweeper:leader"
POST_COMMENT_MODERATION_SWEEPER_LEADER_TTL: Final[int] = 1_800

# Rate-limit strings (slowapi-formatted). Authenticated keys throttle per
# ``current_user.id``; the anonymous key throttles per source IP.
POST_LIKE_RATE_LIMIT: Final[str] = app_settings.blog.post_like_rate_limit
POST_COMMENT_AUTH_RATE_LIMIT: Final[str] = app_settings.blog.post_comment_auth_rate_limit
POST_COMMENT_ANONYMOUS_RATE_LIMIT: Final[str] = app_settings.blog.post_comment_anonymous_rate_limit

# List-endpoint pagination defaults.
POST_LIKES_LIST_DEFAULT_LIMIT: Final[int] = 50
POST_COMMENTS_LIST_DEFAULT_LIMIT: Final[int] = 20
