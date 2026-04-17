"""Unit tests for RS256 JWT helpers and OTP generation."""

from __future__ import annotations

import time

import pytest

from apps.core.security import (
    ACCESS_TOKEN_TYPE,
    CHALLENGE_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenError,
    TokenExpiredError,
    create_access_token,
    create_challenge_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp_code,
    hash_token,
)

# ------------------------------- access tokens ------------------------------


def test_access_token_round_trip() -> None:
    token = create_access_token(subject="user-123")
    payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    assert payload["sub"] == "user-123"
    assert payload["type"] == ACCESS_TOKEN_TYPE
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_decode_rejects_wrong_type() -> None:
    token = create_access_token(subject="user-1")
    with pytest.raises(TokenError, match="Wrong token type"):
        decode_token(token, expected_type=REFRESH_TOKEN_TYPE)


def test_decode_rejects_tampered_signature() -> None:
    token = create_access_token(subject="user-1")
    # Replace the entire signature with something obviously wrong but
    # still base64url-shaped so PyJWT actually attempts verification.
    parts = token.split(".")
    parts[-1] = "A" * len(parts[-1])
    tampered = ".".join(parts)
    with pytest.raises(TokenError):
        decode_token(tampered, expected_type=ACCESS_TOKEN_TYPE)


def test_decode_rejects_garbage() -> None:
    with pytest.raises(TokenError):
        decode_token("not-a-jwt", expected_type=ACCESS_TOKEN_TYPE)


def test_decode_rejects_expired_token(monkeypatch) -> None:
    # Force the access token TTL to 0 so any decode after issuance is expired.
    from apps.settings import app_settings

    monkeypatch.setattr(app_settings.auth, "access_token_expire_minutes", 0)
    token = create_access_token(subject="user-1")
    time.sleep(1)  # ensure exp < now
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type=ACCESS_TOKEN_TYPE)


# ------------------------------ refresh tokens ------------------------------


def test_refresh_token_returns_token_and_expiry() -> None:
    token, expires_at = create_refresh_token(subject="user-7")
    payload = decode_token(token, expected_type=REFRESH_TOKEN_TYPE)
    assert payload["sub"] == "user-7"
    assert payload["type"] == REFRESH_TOKEN_TYPE
    assert expires_at.tzinfo is not None


def test_hash_token_is_deterministic() -> None:
    token, _ = create_refresh_token(subject="user-7")
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64


# ------------------------------ challenge tokens ----------------------------


def test_challenge_token_round_trip() -> None:
    token = create_challenge_token(subject="user-9")
    payload = decode_token(token, expected_type=CHALLENGE_TOKEN_TYPE)
    assert payload["sub"] == "user-9"
    assert payload["type"] == CHALLENGE_TOKEN_TYPE


def test_challenge_token_cannot_be_used_as_access() -> None:
    token = create_challenge_token(subject="user-9")
    with pytest.raises(TokenError):
        decode_token(token, expected_type=ACCESS_TOKEN_TYPE)


# --------------------------------- OTP --------------------------------------


def test_generate_otp_default_length_is_six_digits() -> None:
    code = generate_otp_code()
    assert len(code) == 6
    assert code.isdigit()


def test_generate_otp_respects_length_argument() -> None:
    code = generate_otp_code(length=8)
    assert len(code) == 8


def test_otp_codes_are_random() -> None:
    samples = {generate_otp_code() for _ in range(50)}
    # Extremely unlikely to collide all 50 with a 6-digit space (10^6)
    assert len(samples) > 40


def test_hash_otp_code_is_deterministic_and_64_hex() -> None:
    h = hash_otp_code("123456")
    assert h == hash_otp_code("123456")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
