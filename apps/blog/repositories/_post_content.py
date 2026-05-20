"""Data access for the 1:1 :class:`PostContent` body."""

from __future__ import annotations

import uuid

from apps.blog.models import PostContent
from apps.core.database.repository import BaseSQLAlchemyRepository
from apps.core.database.types import SessionType


class PostContentRepository(BaseSQLAlchemyRepository[PostContent]):
    """Data access for the 1:1 :class:`PostContent` body."""

    model_type = PostContent

    async def find_by_post_id(
        self,
        session: SessionType,
        *,
        post_id: uuid.UUID,
    ) -> PostContent | None:
        return await self.get_one(session, PostContent.post_id == post_id)
