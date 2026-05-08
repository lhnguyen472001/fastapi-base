"""Unit tests for ``PostTagRepository.replace_post_tags`` round-trip count."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.sql.dml import Delete, Insert
from sqlalchemy.sql.expression import Select

from apps.blog.repositories import PostTagRepository


def _session_with_existing(existing_tag_ids: list[uuid.UUID]) -> AsyncMock:
    """Build an AsyncMock session where the SELECT returns ``existing_tag_ids``."""
    session = AsyncMock()
    select_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = existing_tag_ids
    select_result.scalars.return_value = scalars

    # Each call to session.execute returns a different result depending on
    # the statement type — only the SELECT needs to yield rows; DELETE /
    # INSERT yield empty mocks.
    other_result = MagicMock()

    def execute_side_effect(stmt: Any, *args: Any, **_kwargs: Any) -> MagicMock:
        if isinstance(stmt, Select):
            return select_result
        return other_result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    return session


def _classify(calls: list[Any]) -> tuple[int, int, int]:
    """Return (selects, deletes, inserts) from a list of ``session.execute`` calls."""
    selects = deletes = inserts = 0
    for call in calls:
        stmt = call.args[0]
        if isinstance(stmt, Select):
            selects += 1
        elif isinstance(stmt, Delete):
            deletes += 1
        elif isinstance(stmt, Insert):
            inserts += 1
    return selects, deletes, inserts


async def test_replace_with_full_swap_issues_three_statements() -> None:
    """30 existing tags + 30 different new tags must issue 3 statements.

    Regression: the previous loop emitted one DELETE per dropped tag plus
    one INSERT per added tag (61 statements + 1 SELECT in this scenario).
    """
    repo = PostTagRepository()
    post_id = uuid.uuid4()
    existing = [uuid.uuid4() for _ in range(30)]
    new_tags = [uuid.uuid4() for _ in range(30)]
    session = _session_with_existing(existing)

    await repo.replace_post_tags(session, post_id=post_id, tag_ids=new_tags)

    selects, deletes, inserts = _classify(session.execute.await_args_list)
    assert (selects, deletes, inserts) == (1, 1, 1)


async def test_replace_with_no_changes_issues_only_select() -> None:
    """If the target set equals the existing set, no DELETE or INSERT runs."""
    repo = PostTagRepository()
    post_id = uuid.uuid4()
    same = [uuid.uuid4() for _ in range(5)]
    session = _session_with_existing(same)

    await repo.replace_post_tags(session, post_id=post_id, tag_ids=same)

    selects, deletes, inserts = _classify(session.execute.await_args_list)
    assert (selects, deletes, inserts) == (1, 0, 0)


async def test_replace_with_only_additions_issues_select_and_insert() -> None:
    """No removals → no DELETE statement is emitted."""
    repo = PostTagRepository()
    post_id = uuid.uuid4()
    existing = [uuid.uuid4() for _ in range(2)]
    new_tags = [*existing, uuid.uuid4(), uuid.uuid4()]
    session = _session_with_existing(existing)

    await repo.replace_post_tags(session, post_id=post_id, tag_ids=new_tags)

    selects, deletes, inserts = _classify(session.execute.await_args_list)
    assert (selects, deletes, inserts) == (1, 0, 1)


async def test_replace_with_only_removals_issues_select_and_delete() -> None:
    """No additions → no INSERT statement is emitted."""
    repo = PostTagRepository()
    post_id = uuid.uuid4()
    keep = [uuid.uuid4() for _ in range(2)]
    drop = [uuid.uuid4() for _ in range(3)]
    session = _session_with_existing([*keep, *drop])

    await repo.replace_post_tags(session, post_id=post_id, tag_ids=keep)

    selects, deletes, inserts = _classify(session.execute.await_args_list)
    assert (selects, deletes, inserts) == (1, 1, 0)
