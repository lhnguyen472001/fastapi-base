"""XSS round-trip tests for the comment-body sanitizer (T030 / SC-008)."""

from __future__ import annotations

import pytest

from apps.blog.services._comments import _sanitize_comment_body

_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">click</a>',
    "<svg onload=alert(1)>",
    "<iframe src=javascript:alert(1)></iframe>",
    "<style>body{color:red}</style>",
    "<object data=javascript:alert(1)></object>",
    '<input type=text value="x" onfocus="alert(1)" autofocus>',
    "<body onload=alert(1)>",
    "<base href=javascript:alert(1)>",
]


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_sanitizer_strips_dangerous_markup(payload: str) -> None:
    out = _sanitize_comment_body(payload)
    # No tag-opening characters from the payload should survive (nh3 strips
    # the whole tag including its angle brackets when no tags are allowed).
    assert "<" not in out, f"sanitized output retained markup: {out!r}"
    assert ">" not in out, f"sanitized output retained markup: {out!r}"
    assert "alert(" not in out, f"script body survived: {out!r}"


def test_sanitizer_preserves_text_content() -> None:
    assert _sanitize_comment_body("Hello world") == "Hello world"


def test_sanitizer_preserves_newlines() -> None:
    # Multi-line plain text is preserved (so frontend can render with
    # ``white-space: pre-wrap``).
    out = _sanitize_comment_body("line one\nline two\nline three")
    assert "line one" in out
    assert "line two" in out
    assert "line three" in out


def test_sanitizer_handles_entity_escaped_input() -> None:
    out = _sanitize_comment_body("4 &lt; 5 and 5 &gt; 4")
    assert out  # the sanitizer may unescape; we just assert non-empty round-trip
    assert "<" not in out
    assert ">" not in out
