"""Unit tests for :mod:`apps.core.tiptap.render`."""

from __future__ import annotations

from apps.core.tiptap.render import render_html


def test_render_empty_or_falsy() -> None:
    assert render_html(None) == ""
    assert render_html({}) == ""


def test_render_paragraph_with_text() -> None:
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}],
    }
    assert render_html(doc) == "<p>hello</p>"


def test_render_escapes_html_text() -> None:
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<script>x</script>"}]}],
    }
    rendered = render_html(doc)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_render_heading_levels() -> None:
    for level in range(1, 7):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": level},
                    "content": [{"type": "text", "text": f"h{level}"}],
                },
            ],
        }
        assert render_html(doc) == f"<h{level}>h{level}</h{level}>"


def test_render_heading_clamps_invalid_level_to_h1() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 99},
                "content": [{"type": "text", "text": "title"}],
            },
        ],
    }
    assert render_html(doc) == "<h1>title</h1>"


def test_render_marks_bold_italic_link() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "click",
                        "marks": [
                            {"type": "bold"},
                            {"type": "italic"},
                            {"type": "link", "attrs": {"href": "https://example.com"}},
                        ],
                    },
                ],
            },
        ],
    }
    rendered = render_html(doc)
    assert rendered.startswith("<p>")
    assert rendered.endswith("</p>")
    assert "<strong>" in rendered
    assert "<em>" in rendered
    assert '<a href="https://example.com">' in rendered
    assert rendered.count("<strong>") == rendered.count("</strong>")
    assert rendered.count("<em>") == rendered.count("</em>")
    assert rendered.count("<a ") == rendered.count("</a>")


def test_render_code_block() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "x = 1"}],
            },
        ],
    }
    assert render_html(doc) == "<pre><code>x = 1</code></pre>"


def test_render_blockquote_and_list() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "quote"}]},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                        ],
                    },
                ],
            },
        ],
    }
    rendered = render_html(doc)
    assert "<blockquote><p>quote</p></blockquote>" in rendered
    assert "<ul><li><p>a</p></li></ul>" in rendered


def test_render_image_with_attrs() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {
                    "src": "https://example.com/x.png",
                    "alt": "alt-text",
                    "width": 320,
                    "height": 200,
                },
            },
        ],
    }
    rendered = render_html(doc)
    assert 'src="https://example.com/x.png"' in rendered
    assert 'alt="alt-text"' in rendered
    assert 'width="320"' in rendered
    assert 'height="200"' in rendered


def test_render_horizontal_rule_and_hard_break() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "horizontalRule"},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "b"},
                ],
            },
        ],
    }
    rendered = render_html(doc)
    assert "<hr>" in rendered
    assert "<br>" in rendered
