"""Unit tests for the engagement-route rate-limit key functions (T020 + FR-024a/b).

Behavior tests against actual route limits live in slowapi's own suite;
here we cover the key_func contracts that drive the per-user / per-IP
dispatch on the like + comment endpoints.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import jwt

from apps.blog.routes._engagement_rate_keys import (
    _try_extract_jwt_sub,
    anonymous_ip_key,
    auth_user_key,
)


def _request_with(headers: dict[str, str] | None = None, host: str = "10.0.0.5") -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock(host=host)
    req.scope = {"client": (host, 12345), "headers": []}
    return req


def _make_token(sub: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "exp": datetime.datetime.now(tz=datetime.UTC).timestamp() + 60,
            "iss": "fastapi-base",
            "aud": "fastapi-base",
        },
        key="x" * 32,
        algorithm="HS256",
    )


def test_try_extract_jwt_sub_returns_sub_without_verification() -> None:
    token = _make_token("user-123")
    assert _try_extract_jwt_sub(f"Bearer {token}") == "user-123"


def test_try_extract_jwt_sub_returns_none_for_missing_header() -> None:
    assert _try_extract_jwt_sub(None) is None
    assert _try_extract_jwt_sub("") is None


def test_try_extract_jwt_sub_returns_none_for_non_bearer_scheme() -> None:
    assert _try_extract_jwt_sub("Basic dXNlcjpwYXNz") is None


def test_try_extract_jwt_sub_returns_none_for_malformed_token() -> None:
    assert _try_extract_jwt_sub("Bearer not-a-jwt") is None


def test_auth_user_key_keys_by_jwt_sub_when_present() -> None:
    token = _make_token("user-abc")
    request = _request_with({"authorization": f"Bearer {token}"})

    assert auth_user_key(request) == "user:user-abc"


def test_auth_user_key_falls_back_to_ip_when_unauth() -> None:
    request = _request_with(host="192.168.1.42")
    assert auth_user_key(request).startswith("ip:")


def test_anonymous_ip_key_always_uses_ip() -> None:
    token = _make_token("user-xyz")
    request = _request_with({"authorization": f"Bearer {token}"}, host="172.16.0.1")
    # Even with a valid bearer, the anonymous key is per-IP.
    assert anonymous_ip_key(request).startswith("ip:")
