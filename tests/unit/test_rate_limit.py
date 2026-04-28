"""Unit tests for the slowapi-backed rate-limit handler and Limiter wiring.

Behavior tests against actual route limits live in the integration suite —
those need the full FastAPI app with auth_service stubs. Here we cover:
- the custom 429 handler shape
- limiter is enabled by settings flag
- the limiter instance is constructed at import time
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from slowapi.errors import RateLimitExceeded

from apps.core.rate_limit import limiter, rate_limit_exceeded_handler
from apps.settings import app_settings


def test_limiter_is_constructed_with_settings() -> None:
    assert limiter is not None
    assert limiter.enabled == app_settings.rate_limit.enabled


def test_rate_limit_exceeded_handler_returns_429_with_envelope() -> None:
    request = MagicMock()
    limit = MagicMock()
    limit.error_message = "5 per 1 minute"
    exc = RateLimitExceeded(limit=limit)

    response = asyncio.run(rate_limit_exceeded_handler(request, exc))

    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_rate_limit_exceeded_handler_re_raises_unexpected_exception() -> None:
    request = MagicMock()
    other = ValueError("not a rate-limit exception")

    try:
        asyncio.run(rate_limit_exceeded_handler(request, other))
    except ValueError as e:
        assert str(e) == "not a rate-limit exception"
    else:  # pragma: no cover
        msg = "handler should re-raise non-RateLimitExceeded exceptions"
        raise AssertionError(msg)


def test_limiter_can_be_temporarily_disabled(monkeypatch) -> None:
    """``Limiter.enabled`` is mutable so tests can opt out."""
    monkeypatch.setattr(limiter, "enabled", False)

    assert limiter.enabled is False
