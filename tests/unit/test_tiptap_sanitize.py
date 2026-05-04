"""Unit tests for :mod:`apps.core.tiptap.sanitize`.

Coverage:

* Strip ``<script>``, ``on*`` event handlers, and ``javascript:`` URLs.
* Allow basic formatting in the post allowlist.
* Comment allowlist forbids images and headings.
* External links gain ``rel="noopener noreferrer nofollow"``.
"""

from __future__ import annotations

from apps.core.tiptap.sanitize import (
    COMMENT_HTML_ALLOWED_ATTRIBUTES,
    COMMENT_HTML_ALLOWED_TAGS,
    sanitize_html,
)


def test_strips_script_tag() -> None:
    raw = "<p>hello</p><script>alert(1)</script>"
    cleaned = sanitize_html(raw)
    assert "<script>" not in cleaned
    assert "alert" not in cleaned
    assert "<p>hello</p>" in cleaned


def test_strips_inline_event_handler() -> None:
    raw = '<a href="https://example.com" onclick="alert(1)">link</a>'
    cleaned = sanitize_html(raw)
    assert "onclick" not in cleaned
    assert 'href="https://example.com"' in cleaned


def test_strips_javascript_protocol_links() -> None:
    raw = '<a href="javascript:alert(1)">click</a>'
    cleaned = sanitize_html(raw)
    assert "javascript:" not in cleaned


def test_allows_basic_formatting_in_post_allowlist() -> None:
    raw = "<p><strong>bold</strong> and <em>italic</em></p>"
    cleaned = sanitize_html(raw)
    assert "<strong>bold</strong>" in cleaned
    assert "<em>italic</em>" in cleaned


def test_post_allowlist_permits_images() -> None:
    raw = '<img src="https://example.com/x.png" alt="x">'
    cleaned = sanitize_html(raw)
    assert "<img" in cleaned
    assert 'src="https://example.com/x.png"' in cleaned


def test_comment_allowlist_strips_images() -> None:
    raw = '<p>see <img src="https://example.com/x.png" alt="x"> here</p>'
    cleaned = sanitize_html(
        raw,
        allowed_tags=COMMENT_HTML_ALLOWED_TAGS,
        allowed_attributes=COMMENT_HTML_ALLOWED_ATTRIBUTES,
    )
    assert "<img" not in cleaned
    assert "see" in cleaned and "here" in cleaned


def test_comment_allowlist_strips_headings() -> None:
    raw = "<h1>title</h1><p>body</p>"
    cleaned = sanitize_html(
        raw,
        allowed_tags=COMMENT_HTML_ALLOWED_TAGS,
        allowed_attributes=COMMENT_HTML_ALLOWED_ATTRIBUTES,
    )
    assert "<h1>" not in cleaned
    assert "<p>body</p>" in cleaned
    # The heading text content survives even though the tag is stripped.
    assert "title" in cleaned


def test_external_link_gains_noopener_rel() -> None:
    raw = '<a href="https://example.com">x</a>'
    cleaned = sanitize_html(raw)
    assert "rel=" in cleaned
    assert "noopener" in cleaned and "noreferrer" in cleaned and "nofollow" in cleaned


def test_data_uri_image_is_stripped() -> None:
    raw = '<img src="data:image/png;base64,iVBORw0=" alt="x">'
    cleaned = sanitize_html(raw)
    # data: scheme is not in the allowlist; nh3 drops the src or the tag.
    assert "data:image" not in cleaned


def test_empty_string_passes_through() -> None:
    assert sanitize_html("") == ""
