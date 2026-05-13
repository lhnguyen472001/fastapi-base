"""User-module constants.

Module-level identifiers typed with :data:`typing.Final` per the project's
centralized-config rule.
"""

from __future__ import annotations

import uuid
from typing import Final

# Stable sentinel ``users.id`` used by the post-engagement feature to
# tombstone the author reference of comments authored by accounts that
# have since been deleted (FR-030 / data-model §6 of
# specs/003-post-likes-comments).
#
# The Alembic migration that adds the post-engagement tables seeds the
# matching row; the value here and the value seeded by the migration MUST
# stay in sync. Do not change this constant without authoring a follow-up
# migration that backfills any rows pointing at the old id.
DELETED_USER_SENTINEL_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-0000-0000-0000feedbeef")
