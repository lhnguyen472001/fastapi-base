"""Shared helpers for the RBAC ORM models."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC datetime.

    Centralized so every model's ``is_expired`` check uses the same clock
    source, which keeps tests that freeze time (``freezegun``) consistent.
    """
    return datetime.now(UTC)
