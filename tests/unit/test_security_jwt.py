"""Unit tests for RS256 JWT helpers and OTP generation."""

from __future__ import annotations

import time

import jwt
import pytest

from apps.auth.enums import TokenType
from apps.auth.security import (
    TokenError,
    TokenExpiredError,
    decode_token,
    generate_access_token,
    generate_challenge_token,
    generate_otp_code,
    generate_refresh_token,
    hash_otp_code,
    hash_token,
)
from apps.settings import app_settings

# ------------------------------- access tokens ------------------------------


def test_access_token_round_trip() -> None:
    token = generate_access_token(subject="user-123")
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    assert payload["sub"] == "user-123"
    assert payload["type"] == TokenType.ACCESS
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_decode_rejects_wrong_type() -> None:
    token = generate_access_token(subject="user-1")
    with pytest.raises(TokenError, match="Wrong token type"):
        decode_token(token, expected_type=TokenType.REFRESH)


def test_decode_rejects_tampered_signature() -> None:
    token = generate_access_token(subject="user-1")
    # Replace the entire signature with something obviously wrong but
    # still base64url-shaped so PyJWT actually attempts verification.
    parts = token.split(".")
    parts[-1] = "A" * len(parts[-1])
    tampered = ".".join(parts)
    with pytest.raises(TokenError):
        decode_token(tampered, expected_type=TokenType.ACCESS)


def test_decode_rejects_garbage() -> None:
    with pytest.raises(TokenError):
        decode_token("not-a-jwt", expected_type=TokenType.ACCESS)


def test_decode_rejects_expired_token(monkeypatch) -> None:
    # Force the access token TTL to 0 so any decode after issuance is expired.
    monkeypatch.setattr(app_settings.auth, "access_token_expire_minutes", 0)
    token = generate_access_token(subject="user-1")
    time.sleep(1)  # ensure exp < now
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type=TokenType.ACCESS)


# ------------------------------ refresh tokens ------------------------------


def test_refresh_token_returns_token_and_expiry() -> None:
    token, expires_at = generate_refresh_token(subject="user-7")
    payload = decode_token(token, expected_type=TokenType.REFRESH)
    assert payload["sub"] == "user-7"
    assert payload["type"] == TokenType.REFRESH
    assert expires_at.tzinfo is not None


def test_hash_token_is_deterministic() -> None:
    token, _ = generate_refresh_token(subject="user-7")
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64


# ------------------------------ challenge tokens ----------------------------


def test_challenge_token_round_trip() -> None:
    token = generate_challenge_token(subject="user-9")
    payload = decode_token(token, expected_type=TokenType.CHALLENGE)
    assert payload["sub"] == "user-9"
    assert payload["type"] == TokenType.CHALLENGE


def test_challenge_token_cannot_be_used_as_access() -> None:
    token = generate_challenge_token(subject="user-9")
    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)


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


# --------------- iss / aud claim and algorithm-pinning regressions ----------


def test_token_payload_includes_iss_and_aud() -> None:
    token = generate_access_token(subject="user-1")
    payload = decode_token(token, expected_type=TokenType.ACCESS)

    assert payload["iss"] == app_settings.auth.jwt_issuer
    assert payload["aud"] == app_settings.auth.jwt_audience


def test_decode_rejects_wrong_audience(monkeypatch) -> None:
    token = generate_access_token(subject="user-1")
    monkeypatch.setattr(app_settings.auth, "jwt_audience", "some-other-audience")

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_decode_rejects_wrong_issuer(monkeypatch) -> None:
    token = generate_access_token(subject="user-1")
    monkeypatch.setattr(app_settings.auth, "jwt_issuer", "some-other-issuer")

    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_decode_rejects_hs256_token() -> None:
    """RS256 -> HS256 confusion regression.

    Our ``decode_token`` hard-pins ``algorithms=["RS256"]`` so any HS*
    token is rejected before signature verification. PyJWT itself also
    refuses to use an asymmetric key as an HMAC secret on the encode
    side; this test exercises our second layer of defense by forging an
    HS256 token with a plain-string secret and asserting the decoder
    rejects it on algorithm grounds.
    """
    forged_payload = {
        "sub": "attacker",
        "type": TokenType.ACCESS.value,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": "forged",
        "iss": app_settings.auth.jwt_issuer,
        "aud": app_settings.auth.jwt_audience,
    }
    forged_token = jwt.encode(forged_payload, "any-hmac-secret", algorithm="HS256")

    with pytest.raises(TokenError):
        decode_token(forged_token, expected_type=TokenType.ACCESS)


def test_encode_hardcodes_rs256_algorithm_regardless_of_settings(monkeypatch) -> None:
    """Even if an operator (or future code path) flips ``jwt_algorithm`` in
    settings, the actual encode call must continue to use RS256.
    """
    monkeypatch.setattr(app_settings.auth, "jwt_algorithm", "HS256")

    token = generate_access_token(subject="user-1")
    header = jwt.get_unverified_header(token)

    assert header["alg"] == "RS256"
