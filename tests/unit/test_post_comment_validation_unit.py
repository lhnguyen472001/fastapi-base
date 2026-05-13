"""Pydantic validation tests for the comment request schemas (T029)."""

from __future__ import annotations

import pytest

from apps.blog.schemas import (
    CreateAnonymousCommentRequest,
    CreateAuthenticatedCommentRequest,
)

# ---------------------------------------------------------------------------
# Authenticated body
# ---------------------------------------------------------------------------


def test_auth_body_trims_surrounding_whitespace() -> None:
    r = CreateAuthenticatedCommentRequest(body="  hello world  \n")
    assert r.body == "hello world"


def test_auth_body_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        CreateAuthenticatedCommentRequest(body="   \n\t  ")


def test_auth_body_rejects_excess_length() -> None:
    with pytest.raises(ValueError, match="at most 4000 characters"):
        CreateAuthenticatedCommentRequest(body="x" * 4_001)


def test_auth_body_accepts_max_length() -> None:
    r = CreateAuthenticatedCommentRequest(body="x" * 4_000)
    assert len(r.body) == 4_000


# ---------------------------------------------------------------------------
# Anonymous body
# ---------------------------------------------------------------------------


def test_anon_body_requires_display_name() -> None:
    with pytest.raises(ValueError):
        CreateAnonymousCommentRequest.model_validate({"body": "hi"})


def test_anon_body_rejects_whitespace_only_display_name() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        CreateAnonymousCommentRequest(body="hi", author_display_name="   ")


def test_anon_email_is_optional() -> None:
    r = CreateAnonymousCommentRequest(
        body="hi",
        author_display_name="Reader",
    )
    assert r.author_email is None


def test_anon_email_rejects_obviously_invalid_shape() -> None:
    with pytest.raises(ValueError, match="syntactically valid email"):
        CreateAnonymousCommentRequest(
            body="hi",
            author_display_name="Reader",
            author_email="no-at-sign",
        )


def test_anon_email_accepts_simple_email() -> None:
    r = CreateAnonymousCommentRequest(
        body="hi",
        author_display_name="Reader",
        author_email="reader@example.com",
    )
    assert r.author_email == "reader@example.com"


def test_anon_body_max_length() -> None:
    with pytest.raises(ValueError, match="at most 4000 characters"):
        CreateAnonymousCommentRequest(
            body="x" * 4_001,
            author_display_name="Reader",
        )
