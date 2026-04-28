"""Auth request and response schemas (Pydantic v2)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import EmailStr, Field

from apps.core.schemas.request import RequestObjectSchema
from apps.core.schemas.response import ResponseObjectSchema
from apps.user.schemas import CreateUserRequest


class RegisterRequest(CreateUserRequest):
    """Self-service registration body."""


class VerifyEmailRequest(RequestObjectSchema):
    """Confirm email ownership via OTP code."""

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)


class ResendVerificationRequest(RequestObjectSchema):
    email: EmailStr


class LoginRequest(RequestObjectSchema):
    """Step 1 of login — credentials."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class Login2FARequest(RequestObjectSchema):
    """Step 2 of login — answer the 2FA challenge."""

    challenge_token: str
    totp_code: str = Field(..., min_length=6, max_length=8)


class RefreshRequest(RequestObjectSchema):
    refresh_token: str


class LogoutRequest(RequestObjectSchema):
    refresh_token: str


class Enable2FARequest(RequestObjectSchema):
    """Confirm setup by submitting a TOTP code generated from the new secret."""

    totp_code: str = Field(..., min_length=6, max_length=8)


class Disable2FARequest(RequestObjectSchema):
    """Disabling 2FA requires both a current TOTP and the user's password."""

    password: str
    totp_code: str = Field(..., min_length=6, max_length=8)


class TokenPair(ResponseObjectSchema):
    """Access + refresh token bundle returned after successful auth."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — bearer token delimiter, not a password
    expires_in: int = Field(..., description="Access token TTL in seconds")


class TwoFactorChallenge(ResponseObjectSchema):
    """Returned by login step 1 when the user has 2FA enabled."""

    requires_2fa: Literal[True] = True
    challenge_token: str = Field(..., description="Short-lived JWT to submit with the TOTP code")


class Setup2FAResponse(ResponseObjectSchema):
    """Returned by /auth/2fa/setup so the client can render a QR code."""

    secret: str = Field(..., description="Base32-encoded TOTP secret")
    otpauth_url: str = Field(..., description="otpauth:// URI consumed by authenticator apps")


class GoogleAuthorizeResponse(ResponseObjectSchema):
    authorize_url: str
    state: str


class RegisterResponse(ResponseObjectSchema):
    """What the registration endpoint returns (no tokens — must verify first)."""

    user_id: uuid.UUID
    message: str = "Verification email sent. Please check your inbox."
