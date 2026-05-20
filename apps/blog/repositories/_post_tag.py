"""Data access for the post↔tag join."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, insert, select

from apps.blog.models import PostTag
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostTagRepository(BaseSQLAlchemyRepository[PostTag]):
    """Data access for the post↔tag join."""

    model_type = PostTag

    async def replace_post_tags(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
        tag_ids: Iterable[uuid.UUID],
    ) -> None:
        """Hard-replace the tag set on a post.

        Issues at most three statements regardless of tag count: a SELECT
        of existing tag ids, one bulk DELETE for tags being dropped, and
        one executemany INSERT for tags being added. The previous loop
        produced one DELETE per dropped tag plus one INSERT per added tag,
        which under bulk re-tagging compounded into N+1 round-trips.
        """
        target = set(tag_ids)

        existing_rows = (
            (await session.execute(select(PostTag.tag_id).where(PostTag.post_id == post_id))).scalars().all()
        )
        existing = set(existing_rows)

        to_remove = existing - target
        if to_remove:
            await session.execute(
                delete(PostTag).where(PostTag.post_id == post_id, PostTag.tag_id.in_(to_remove)),
            )

        to_add = target - existing
        if to_add:
            await session.execute(
                insert(PostTag),
                [{"post_id": post_id, "tag_id": tag_id} for tag_id in to_add],
            )
