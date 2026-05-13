"""Pydantic round-trip tests for the engagement response schemas (T017)."""

from __future__ import annotations

import uuid

import pytest

from apps.blog.schemas import LikeState


def test_like_state_round_trip_serializes_three_fields() -> None:
    pid = uuid.uuid4()
    state = LikeState(post_id=pid, like_count=7, liked_by_me=True)

    dumped = state.model_dump()

    assert dumped == {"post_id": pid, "like_count": 7, "liked_by_me": True}


def test_like_state_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        LikeState(post_id=uuid.uuid4(), like_count=-1, liked_by_me=False)


def test_like_state_emits_uuid_string_in_json() -> None:
    pid = uuid.uuid4()
    state = LikeState(post_id=pid, like_count=0, liked_by_me=False)

    payload = state.model_dump_json()

    assert str(pid) in payload
    assert '"like_count":0' in payload
    assert '"liked_by_me":false' in payload
