"""Unit tests for BLOCKER-1: service delegates to the new repository method.

``PostCommentModerationService._find_post_by_id_any_workspace`` previously
constructed and executed a raw ``select(Post)`` in the service layer,
violating CLAUDE.md's "no raw SQL in services" rule. The fix moves the
SELECT into ``PostRepository.find_by_id_any_workspace`` and turns the
service helper into a thin delegation.

These tests pin the boundary so future edits don't reintroduce the
in-service ``select()`` import.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.blog.repositories import PostRepository
from apps.blog.services._comment_moderation import PostCommentModerationService


def test_repository_exposes_find_by_id_any_workspace() -> None:
    assert hasattr(PostRepository, "find_by_id_any_workspace")
    assert inspect.iscoroutinefunction(PostRepository.find_by_id_any_workspace)


def test_repository_signature_is_keyword_only_post_id() -> None:
    """The contract is ``(session, *, post_id)``. A positional-only post_id would
    quietly break the moderation service after a refactor."""
    sig = inspect.signature(PostRepository.find_by_id_any_workspace)
    assert "post_id" in sig.parameters
    assert sig.parameters["post_id"].kind == inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_service_helper_delegates_to_repository() -> None:
    post_id = uuid.uuid4()
    sentinel = MagicMock(name="Post")

    repository = MagicMock(name="PostCommentModerationRepository")
    post_repository = MagicMock(name="PostRepository")
    post_repository.find_by_id_any_workspace = AsyncMock(return_value=sentinel)
    access_service = MagicMock(name="AccessService")
    session = MagicMock(name="Session")

    service = PostCommentModerationService(
        repository=repository,
        post_repository=post_repository,
        access_service=access_service,
    )

    found = await service._find_post_by_id_any_workspace(session, post_id=post_id)

    assert found is sentinel
    post_repository.find_by_id_any_workspace.assert_awaited_once_with(session, post_id=post_id)


def test_service_helper_does_not_import_sqlalchemy_select() -> None:
    """Regression guard against the BLOCKER-1 anti-pattern of importing
    ``sqlalchemy.select`` inside a service method."""
    src = inspect.getsource(PostCommentModerationService._find_post_by_id_any_workspace)
    assert "from sqlalchemy import select" not in src
    assert "session.execute" not in src
