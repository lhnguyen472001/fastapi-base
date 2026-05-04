"""Unit tests for :mod:`apps.core.tiptap.extract_text`."""

from __future__ import annotations

from apps.core.tiptap.extract_text import extract_text


def test_extract_returns_empty_for_falsy_input() -> None:
    assert extract_text(None) == ""
    assert extract_text({}) == ""


def test_extract_simple_paragraph() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
        ],
    }
    assert extract_text(doc) == "Hello"


def test_extract_concatenates_multiple_paragraphs_with_whitespace() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "second"}]},
        ],
    }
    assert extract_text(doc) == "first second"


def test_extract_walks_nested_lists() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [{"type": "text", "text": "b1"}],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    assert extract_text(doc) == "a b b1"


def test_extract_handles_code_blocks() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "print('hi')"}],
            },
        ],
    }
    assert extract_text(doc) == "print('hi')"


def test_extract_handles_hard_break() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "line1"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "line2"},
                ],
            },
        ],
    }
    assert extract_text(doc) == "line1 line2"


def test_extract_collapses_whitespace() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "  hello   world  "}]},
        ],
    }
    assert extract_text(doc) == "hello world"


def test_extract_ignores_unknown_text_node_payload() -> None:
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text"}]}],
    }
    assert extract_text(doc) == ""
