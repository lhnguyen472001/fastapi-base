"""Unit tests for the Jinja-based EmailRenderer."""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import TemplateNotFound

from apps.core.email import EmailRenderer

TEMPLATE_DIR = Path("apps/core/email/templates")


def test_renderer_renders_plain_and_html() -> None:
    renderer = EmailRenderer(TEMPLATE_DIR)
    plain, html = renderer.render(
        "verification_email",
        subject="Verify your email",
        app_name="FastAPI Base",
        username="alice",
        code="123456",
        ttl_minutes=10,
    )

    # Both versions must contain the OTP and username.
    assert "123456" in plain
    assert "123456" in html
    assert "alice" in plain
    assert "alice" in html

    # HTML version should be actual HTML.
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


def test_renderer_autoescapes_html_in_user_input() -> None:
    """Username containing HTML must be escaped in the HTML body, not the plain body."""
    renderer = EmailRenderer(TEMPLATE_DIR)
    plain, html = renderer.render(
        "verification_email",
        subject="Verify",
        app_name="FastAPI Base",
        username="<script>alert(1)</script>",
        code="000000",
        ttl_minutes=10,
    )

    # Plain text passes through verbatim — no auto-escape.
    assert "<script>alert(1)</script>" in plain
    # HTML version must escape the angle brackets.
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_renderer_raises_for_missing_template_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        EmailRenderer(missing)


def test_renderer_raises_for_missing_template_pair(tmp_path: Path) -> None:
    # Provide an HTML template but no .txt counterpart — render() must fail.
    (tmp_path / "lonely.html").write_text("<p>{{ x }}</p>", encoding="utf-8")
    renderer = EmailRenderer(tmp_path)
    with pytest.raises(TemplateNotFound):
        renderer.render("lonely", x=1)
