"""Unit tests for OAuth state binding + PKCE.

These tests exercise apps/auth/services/_oauth.py without requiring a real
DB or a live Google endpoint. The verifier/challenge derivation and the
state-binding logic are pure functions of inputs.
"""

from __future__ import annotations

import base64
import hashlib
import string
from unittest.mock import MagicMock

import pytest

from apps.auth.constants import OAUTH_STATE_COOKIE_NAME
from apps.auth.enums import TokenType
from apps.auth.exceptions import OAuthStateInvalidError
from apps.auth.security import (
    TokenError,
    compute_pkce_challenge,
    decode_token,
    generate_challenge_token,
    generate_oauth_state_token,
    generate_pkce_verifier,
)
from apps.auth.services._oauth import (
    OAuthFlowStart,
    OAuthService,
)

# ------------------------------ PKCE helpers --------------------------------


def test_pkce_verifier_meets_rfc_7636_format() -> None:
    """RFC 7636 §4.1: 43-128 unreserved characters."""
    verifier = generate_pkce_verifier()
    unreserved = set(string.ascii_letters + string.digits + "-._~")

    assert 43 <= len(verifier) <= 128
    assert set(verifier).issubset(unreserved)


def test_pkce_challenge_is_s256_of_verifier() -> None:
    """Challenge = BASE64URL-NOPAD(SHA256(verifier))."""
    verifier = "the_quick_brown_fox_jumps_over_the_lazy_dog_0123456789"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    assert compute_pkce_challenge(verifier) == expected


def test_pkce_challenge_is_url_safe_and_unpadded() -> None:
    challenge = compute_pkce_challenge(generate_pkce_verifier())

    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


def test_pkce_two_verifiers_are_distinct() -> None:
    samples = {generate_pkce_verifier() for _ in range(50)}

    assert len(samples) == 50


# --------------------------- state token claims ----------------------------


def test_oauth_state_token_carries_sid_and_cv() -> None:
    state_id = "abc123"
    verifier = generate_pkce_verifier()

    token = generate_oauth_state_token(state_id=state_id, code_verifier=verifier)
    payload = decode_token(token, expected_type=TokenType.OAUTH_STATE)

    assert payload["sub"] == "oauth_state"
    assert payload["sid"] == state_id
    assert payload["cv"] == verifier


def test_oauth_state_token_type_is_distinct_from_challenge() -> None:
    """A 2FA challenge token must NOT satisfy the OAuth state decoder.

    Before this fix the two flows shared TokenType.CHALLENGE; an attacker
    who scraped a valid 2FA challenge could replay it as OAuth state.
    """
    challenge = generate_challenge_token(subject="user-1")

    with pytest.raises(TokenError):
        decode_token(challenge, expected_type=TokenType.OAUTH_STATE)


# ---------------------- OAuthService.verify_state_token ---------------------


def _make_service() -> OAuthService:
    return OAuthService(
        user_service=MagicMock(),
        google_oauth_client=MagicMock(),
    )


def test_verify_state_accepts_matching_cookie() -> None:
    service = _make_service()
    flow = service.start_authorize_flow()

    payload = service.verify_state_token(flow.state_token, cookie_state_id=flow.state_id)

    assert payload["sid"] == flow.state_id
    assert payload["cv"]


def test_verify_state_rejects_missing_cookie() -> None:
    service = _make_service()
    flow = service.start_authorize_flow()

    with pytest.raises(OAuthStateInvalidError):
        service.verify_state_token(flow.state_token, cookie_state_id=None)


def test_verify_state_rejects_mismatched_cookie() -> None:
    service = _make_service()
    flow = service.start_authorize_flow()

    with pytest.raises(OAuthStateInvalidError):
        service.verify_state_token(flow.state_token, cookie_state_id="some-other-state-id")


def test_verify_state_rejects_2fa_challenge_token() -> None:
    """Token-type collision regression."""
    service = _make_service()
    challenge = generate_challenge_token(subject="user-1")

    with pytest.raises(OAuthStateInvalidError):
        service.verify_state_token(challenge, cookie_state_id="anything")


# --------------------------- start_authorize_flow ---------------------------


def test_start_authorize_flow_returns_bundle_with_pkce_challenge_in_url() -> None:
    service = _make_service()
    service.google_oauth_client.build_authorize_url.return_value = "https://accounts.google.com/...?code_challenge=X"

    flow = service.start_authorize_flow()

    assert isinstance(flow, OAuthFlowStart)
    assert flow.state_id and flow.state_token and flow.authorize_url
    call = service.google_oauth_client.build_authorize_url.call_args
    assert call.kwargs["state"] == flow.state_token
    assert call.kwargs.get("code_challenge")


def test_oauth_state_cookie_name_is_stable() -> None:
    """Routes and the service must agree on the cookie name."""
    assert OAUTH_STATE_COOKIE_NAME == "oauth_state"
