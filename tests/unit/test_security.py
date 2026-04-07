"""Unit tests for apps/core/security.py bcrypt helpers."""

from __future__ import annotations

from apps.core.security import hash_password, verify_password


def test_hash_password_returns_str() -> None:
    hashed = hash_password("secret123")
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")  # bcrypt prefix


def test_hash_password_uses_random_salt() -> None:
    """Two hashes of the same plaintext must differ — proves a fresh salt."""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_verify_password_accepts_correct_password() -> None:
    plain = "correct horse battery staple"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("right-password")
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_handles_unicode() -> None:
    plain = "пароль-密码-🔑"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True
    assert verify_password("different", hashed) is False
