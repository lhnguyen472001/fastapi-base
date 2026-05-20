"""Shared schemas used by multiple blog modules (hero_quote, etc.)."""

from __future__ import annotations

from pydantic import Field, HttpUrl, field_validator

from apps.blog.constants import (
    HERO_QUOTE_AUTHOR_MAX_LENGTH,
    HERO_QUOTE_SOURCE_URL_MAX_LENGTH,
    HERO_QUOTE_TEXT_MAX_LENGTH,
)
from apps.core.schemas.base import BaseObjectSchema


class HeroQuote(BaseObjectSchema):
    """Pull-quote attached to a post (optional).

    Round-trips cleanly through the JSONB column on
    :class:`apps.blog.models.Post`.
    """

    text: str = Field(..., min_length=1, max_length=HERO_QUOTE_TEXT_MAX_LENGTH)
    author: str | None = Field(default=None, max_length=HERO_QUOTE_AUTHOR_MAX_LENGTH)
    source_url: HttpUrl | None = Field(default=None)

    @field_validator("source_url")
    @classmethod
    def _check_source_url_length(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and len(str(value)) > HERO_QUOTE_SOURCE_URL_MAX_LENGTH:
            msg = f"source_url length must not exceed {HERO_QUOTE_SOURCE_URL_MAX_LENGTH} characters."
            raise ValueError(msg)
        return value
