"""Jinja2-based email template renderer.

Looks up two paired templates per email — ``<name>.txt`` and ``<name>.html``
— and renders them with the same context dict so the plain-text and HTML
versions stay in lock-step.

The :class:`Environment` enables HTML autoescaping so user-supplied values
(usernames, email addresses) cannot inject markup into the rendered email.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape


class EmailRenderer:
    """Render plain + HTML email bodies from a shared template directory."""

    def __init__(self, template_dir: Path) -> None:
        """Initialize the Jinja environment.

        Args:
            template_dir: Path to the directory containing the ``*.txt`` /
                ``*.html`` template files.

        Raises:
            FileNotFoundError: If ``template_dir`` doesn't exist on disk.
        """
        if not template_dir.exists():
            msg = f"Email template directory not found: {template_dir}"
            raise FileNotFoundError(msg)

        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(self, name: str, **context: Any) -> tuple[str, str]:
        """Render the ``<name>.txt`` and ``<name>.html`` templates.

        Args:
            name: Template stem (without extension).
            **context: Variables passed to both templates.

        Returns:
            ``(plain_text, html)`` — both strings, ready to attach to an
            :class:`apps.core.email.EmailMessage`.

        Raises:
            jinja2.TemplateNotFound: If either ``<name>.txt`` or
                ``<name>.html`` is missing.
        """
        try:
            plain = self._env.get_template(f"{name}.txt").render(**context)
            html = self._env.get_template(f"{name}.html").render(**context)
        except TemplateNotFound as exc:
            msg = (
                f"Email template '{name}' is missing one of '{name}.txt' / "
                f"'{name}.html'. Cause: {exc}"
            )
            raise TemplateNotFound(msg) from exc
        return plain, html
