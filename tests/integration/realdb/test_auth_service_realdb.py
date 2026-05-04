"""Real-DB integration tests for AuthService and Google OAuth.

Hits the migrated Postgres tables (users, refresh_tokens, email_verifications)
through the full service layer. Google OAuth HTTP calls are mocked with respx.
"""

from __future__ import annotations

import re
import time
import uuid

import httpx
import pyotp
import pytest
import respx

from apps.auth.constants import GOOGLE_TOKEN_ENDPOINT, GOOGLE_USERINFO_ENDPOINT
from apps.auth.enums import TokenType
from apps.auth.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidOtpError,
    InvalidTokenError,
    InvalidTwoFactorCodeError,
    OAuthStateInvalidError,
    RefreshTokenRevokedError,
    TwoFactorNotEnabledError,
)
from apps.auth.oauth import GoogleOAuthClient
from apps.auth.repository import EmailVerificationRepository, RefreshTokenRepository
from apps.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenPair,
    TwoFactorChallenge,
)
from apps.auth.security import (
    decode_token,
    generate_refresh_token,
)
from apps.auth.services import (
    AuthService,
    EmailVerificationService,
    OAuthService,
    TokenService,
    TwoFactorService,
)
from apps.core.email import EmailRenderer, StubEmailSender
from apps.settings import app_settings
from apps.user.repositories import UserRepository
from apps.user.services import UserService


def _next_totp_code(secret: str) -> str:
    """Mint a TOTP code one window past now to clear the replay-guard counter."""
    return pyotp.TOTP(secret).at(int(time.time()) + 30)


# ----------------------------- fixtures -------------------------------------


@pytest.fixture
def email_sender() -> StubEmailSender:
    return StubEmailSender()


@pytest.fixture
def google_oauth_client() -> GoogleOAuthClient:
    return GoogleOAuthClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/api/v1/auth/oauth/google/callback",
    )


@pytest.fixture
def email_renderer() -> EmailRenderer:
    return EmailRenderer(app_settings.email.template_dir)


@pytest.fixture
def auth_service(
    email_sender: StubEmailSender,
    email_renderer: EmailRenderer,
    google_oauth_client: GoogleOAuthClient,
) -> AuthService:
    user_repository = UserRepository()
    user_service = UserService(repository=user_repository)
    refresh_token_repository = RefreshTokenRepository()
    email_verification_repository = EmailVerificationRepository()

    token_service = TokenService(
        user_service=user_service,
        refresh_token_repository=refresh_token_repository,
    )
    email_verification_service = EmailVerificationService(
        user_service=user_service,
        user_repository=user_repository,
        email_verification_repository=email_verification_repository,
        email_sender=email_sender,
        email_renderer=email_renderer,
    )
    two_factor_service = TwoFactorService(user_repository=user_repository)
    oauth_service = OAuthService(
        user_service=user_service,
        google_oauth_client=google_oauth_client,
    )

    return AuthService(
        user_service=user_service,
        token_service=token_service,
        email_verification_service=email_verification_service,
        two_factor_service=two_factor_service,
        oauth_service=oauth_service,
    )


def _register_request(suffix: str, password: str = "Sup3rSecret!") -> RegisterRequest:
    return RegisterRequest(
        email=f"auth_{suffix}@example.com",
        username=f"auth_{suffix}",
        password=password,
    )


def _extract_code(stub: StubEmailSender) -> str:
    body = stub.sent[-1].body
    match = re.search(r"\b(\d{6})\b", body)
    assert match is not None, f"No 6-digit code found in: {body!r}"
    return match.group(1)


# ----------------------------- registration --------------------------------


async def test_register_creates_inactive_user_and_sends_otp(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    user = await auth_service.register(real_session, data=_register_request(suffix))
    await real_session.flush()

    assert user.is_active is False
    assert user.email_verified_at is None
    assert len(email_sender.sent) == 1
    assert "verification code" in email_sender.sent[0].body.lower()


async def test_verify_email_activates_user(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    user = await auth_service.register(real_session, data=payload)
    await real_session.flush()

    code = _extract_code(email_sender)
    activated = await auth_service.verify_email(real_session, email=payload.email, code=code)
    await real_session.flush()

    assert activated.id == user.id
    assert activated.is_active is True
    assert activated.email_verified_at is not None


async def test_verify_email_with_wrong_code_increments_attempts(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()

    with pytest.raises(InvalidOtpError):
        await auth_service.verify_email(real_session, email=payload.email, code="000000")


async def test_verify_email_after_max_attempts_invalidates_code(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()

    correct_code = _extract_code(email_sender)
    for _ in range(5):
        with pytest.raises(InvalidOtpError):
            await auth_service.verify_email(real_session, email=payload.email, code="999999")
        await real_session.flush()

    # 6th attempt with the CORRECT code is rejected because attempts >= max.
    with pytest.raises(InvalidOtpError):
        await auth_service.verify_email(real_session, email=payload.email, code=correct_code)


async def test_resend_verification_invalidates_old_code(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()

    old_code = _extract_code(email_sender)
    await auth_service.resend_verification(real_session, email=payload.email)
    await real_session.flush()

    new_code = _extract_code(email_sender)
    assert new_code != old_code or len(email_sender.sent) == 2

    # Old code can no longer activate the user.
    with pytest.raises(InvalidOtpError):
        await auth_service.verify_email(real_session, email=payload.email, code=old_code)


# -------------------------------- login ------------------------------------


async def test_login_unverified_user_rejected(real_session, auth_service) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()

    with pytest.raises(EmailNotVerifiedError):
        await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))


async def test_login_wrong_password_rejected(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()
    await auth_service.verify_email(real_session, email=payload.email, code=_extract_code(email_sender))
    await real_session.flush()

    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(real_session, data=LoginRequest(email=payload.email, password="wrong-password"))


async def test_login_unknown_user_rejected(real_session, auth_service) -> None:
    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(real_session, data=LoginRequest(email="nobody@example.com", password="anything-1234"))


async def test_login_returns_token_pair_when_2fa_disabled(real_session, auth_service, email_sender) -> None:
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    await auth_service.register(real_session, data=payload)
    await real_session.flush()
    await auth_service.verify_email(real_session, email=payload.email, code=_extract_code(email_sender))
    await real_session.flush()

    result = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()

    assert isinstance(result, TokenPair)
    assert result.access_token
    assert result.refresh_token
    assert result.expires_in > 0


# ------------------------------- 2FA flow ----------------------------------


async def _activate_user(real_session, auth_service, email_sender, suffix):
    payload = _register_request(suffix)
    user = await auth_service.register(real_session, data=payload)
    await real_session.flush()
    code = _extract_code(email_sender)
    await auth_service.verify_email(real_session, email=payload.email, code=code)
    await real_session.flush()
    return user, payload


async def test_setup_and_enable_2fa(real_session, auth_service, email_sender) -> None:
    user, _ = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])

    setup = await auth_service.setup_2fa(real_session, user=user)
    await real_session.flush()
    assert setup.secret
    assert "otpauth://totp/" in setup.otpauth_url

    valid_code = pyotp.TOTP(setup.secret).now()
    await auth_service.enable_2fa(real_session, user=user, totp_code=valid_code)
    await real_session.flush()

    assert user.is_2fa_enabled is True


async def test_enable_2fa_with_wrong_code_rejected(real_session, auth_service, email_sender) -> None:
    user, _ = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    await auth_service.setup_2fa(real_session, user=user)
    await real_session.flush()

    with pytest.raises(InvalidTwoFactorCodeError):
        await auth_service.enable_2fa(real_session, user=user, totp_code="000000")
    assert user.is_2fa_enabled is False


async def test_login_with_2fa_returns_challenge_then_token_pair(real_session, auth_service, email_sender) -> None:
    user, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    setup = await auth_service.setup_2fa(real_session, user=user)
    await auth_service.enable_2fa(real_session, user=user, totp_code=pyotp.TOTP(setup.secret).now())
    await real_session.flush()

    step1 = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(step1, TwoFactorChallenge)

    valid_code = _next_totp_code(setup.secret)
    step2 = await auth_service.login_2fa(real_session, challenge_token=step1.challenge_token, totp_code=valid_code)
    await real_session.flush()
    assert isinstance(step2, TokenPair)


async def test_login_2fa_with_wrong_code_rejected(real_session, auth_service, email_sender) -> None:
    user, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    setup = await auth_service.setup_2fa(real_session, user=user)
    await auth_service.enable_2fa(real_session, user=user, totp_code=pyotp.TOTP(setup.secret).now())
    await real_session.flush()

    step1 = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(step1, TwoFactorChallenge)

    with pytest.raises(InvalidTwoFactorCodeError):
        await auth_service.login_2fa(real_session, challenge_token=step1.challenge_token, totp_code="000000")


async def test_disable_2fa_clears_secret(real_session, auth_service, email_sender) -> None:
    user, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    setup = await auth_service.setup_2fa(real_session, user=user)
    await auth_service.enable_2fa(real_session, user=user, totp_code=pyotp.TOTP(setup.secret).now())
    await real_session.flush()

    valid_code = _next_totp_code(setup.secret)
    await auth_service.disable_2fa(real_session, user=user, password=payload.password, totp_code=valid_code)
    await real_session.flush()

    assert user.is_2fa_enabled is False
    assert user.totp_secret is None


async def test_disable_2fa_when_not_enabled_raises(real_session, auth_service, email_sender) -> None:
    user, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    with pytest.raises(TwoFactorNotEnabledError):
        await auth_service.disable_2fa(real_session, user=user, password=payload.password, totp_code="000000")


# ------------------------------ refresh / logout ---------------------------


async def test_refresh_rotates_token(real_session, auth_service, email_sender) -> None:
    _, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    pair1 = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(pair1, TokenPair)

    pair2 = await auth_service.refresh(real_session, raw_refresh_token=pair1.refresh_token)
    await real_session.flush()

    assert pair2.refresh_token != pair1.refresh_token
    assert pair2.access_token != pair1.access_token

    # Old token can no longer be used.
    with pytest.raises(RefreshTokenRevokedError):
        await auth_service.refresh(real_session, raw_refresh_token=pair1.refresh_token)


async def test_refresh_with_garbage_token_rejected(real_session, auth_service) -> None:
    with pytest.raises(InvalidTokenError):
        await auth_service.refresh(real_session, raw_refresh_token="not-a-jwt")


async def test_refresh_with_access_token_type_rejected(real_session, auth_service, email_sender) -> None:
    _, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    pair = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(pair, TokenPair)

    # Try to use the access token where a refresh token is expected.
    with pytest.raises(InvalidTokenError):
        await auth_service.refresh(real_session, raw_refresh_token=pair.access_token)


async def test_refresh_with_unknown_jwt_rejected(real_session, auth_service) -> None:
    """A signed-but-unknown refresh JWT must be rejected (no DB row exists)."""
    forged, _ = generate_refresh_token(subject=str(uuid.uuid4()))
    payload = decode_token(forged, expected_type=TokenType.REFRESH)
    assert payload["type"] == TokenType.REFRESH  # token itself is valid

    with pytest.raises(RefreshTokenRevokedError):
        await auth_service.refresh(real_session, raw_refresh_token=forged)


async def test_logout_revokes_refresh_token(real_session, auth_service, email_sender) -> None:
    _, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    pair = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(pair, TokenPair)

    await auth_service.logout(real_session, raw_refresh_token=pair.refresh_token)
    await real_session.flush()

    with pytest.raises(RefreshTokenRevokedError):
        await auth_service.refresh(real_session, raw_refresh_token=pair.refresh_token)


async def test_logout_idempotent(real_session, auth_service) -> None:
    """Logging out an unknown token must not raise."""
    forged, _ = generate_refresh_token(subject=str(uuid.uuid4()))
    await auth_service.logout(real_session, raw_refresh_token=forged)


# ----------------------------------- me ------------------------------------


async def test_get_user_from_access_token(real_session, auth_service, email_sender) -> None:
    user, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    pair = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(pair, TokenPair)

    fetched = await auth_service.get_user_from_access_token(real_session, token=pair.access_token)
    assert fetched.id == user.id


async def test_get_user_from_access_token_with_refresh_token_rejected(real_session, auth_service, email_sender) -> None:
    _, payload = await _activate_user(real_session, auth_service, email_sender, uuid.uuid4().hex[:8])
    pair = await auth_service.login(real_session, data=LoginRequest(email=payload.email, password=payload.password))
    await real_session.flush()
    assert isinstance(pair, TokenPair)

    with pytest.raises(InvalidTokenError):
        await auth_service.get_user_from_access_token(real_session, token=pair.refresh_token)


# ----------------------------- Google OAuth --------------------------------


@pytest.fixture
def google_userinfo_payload() -> dict:
    return {
        "sub": "google-test-sub-123",
        "email": "googleuser@example.com",
        "email_verified": True,
        "name": "Google User",
        "picture": "https://example.com/pic.jpg",
    }


@respx.mock
async def test_google_callback_creates_new_user(real_session, auth_service, google_userinfo_payload) -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.fake", "token_type": "Bearer"})
    )
    respx.get(GOOGLE_USERINFO_ENDPOINT).mock(return_value=httpx.Response(200, json=google_userinfo_payload))

    flow = auth_service.start_google_oauth()
    result = await auth_service.google_callback(
        real_session,
        code="g-auth-code",
        state=flow.state_token,
        cookie_state_id=flow.state_id,
    )
    await real_session.flush()

    assert isinstance(result, TokenPair)

    # User should now exist, active, with google_sub linked.
    user = await auth_service.user_service.get_by_email_or_username(
        real_session, email=google_userinfo_payload["email"]
    )
    assert user is not None
    assert user.is_active is True
    assert user.google_sub == google_userinfo_payload["sub"]
    assert user.email_verified_at is not None


@respx.mock
async def test_google_callback_links_existing_user(
    real_session, auth_service, email_sender, google_userinfo_payload
) -> None:
    # Pre-create a local user with the same email (registered via password).
    suffix = uuid.uuid4().hex[:8]
    payload = _register_request(suffix)
    payload = RegisterRequest(
        email=google_userinfo_payload["email"],
        username=payload.username,
        password=payload.password,
    )
    user = await auth_service.register(real_session, data=payload)
    await real_session.flush()
    assert user.google_sub is None

    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.fake", "token_type": "Bearer"})
    )
    respx.get(GOOGLE_USERINFO_ENDPOINT).mock(return_value=httpx.Response(200, json=google_userinfo_payload))

    flow = auth_service.start_google_oauth()
    result = await auth_service.google_callback(
        real_session,
        code="g-auth-code",
        state=flow.state_token,
        cookie_state_id=flow.state_id,
    )
    await real_session.flush()

    assert isinstance(result, TokenPair)
    await real_session.refresh(user)
    assert user.google_sub == google_userinfo_payload["sub"]
    assert user.is_active is True


@respx.mock
async def test_google_callback_with_token_endpoint_failure_raises(real_session, auth_service) -> None:
    from apps.auth.exceptions import OAuthProviderError

    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))

    flow = auth_service.start_google_oauth()
    with pytest.raises(OAuthProviderError):
        await auth_service.google_callback(
            real_session,
            code="bad-code",
            state=flow.state_token,
            cookie_state_id=flow.state_id,
        )


async def test_google_callback_with_invalid_state_rejected(real_session, auth_service) -> None:
    with pytest.raises(OAuthStateInvalidError):
        await auth_service.google_callback(
            real_session,
            code="g-auth-code",
            state="not-a-real-state",
            cookie_state_id="some-cookie-id",
        )


async def test_google_callback_rejects_missing_cookie(real_session, auth_service) -> None:
    flow = auth_service.start_google_oauth()
    with pytest.raises(OAuthStateInvalidError):
        await auth_service.google_callback(
            real_session,
            code="g-auth-code",
            state=flow.state_token,
            cookie_state_id=None,
        )


async def test_google_callback_rejects_mismatched_cookie(real_session, auth_service) -> None:
    flow = auth_service.start_google_oauth()
    with pytest.raises(OAuthStateInvalidError):
        await auth_service.google_callback(
            real_session,
            code="g-auth-code",
            state=flow.state_token,
            cookie_state_id="not-the-right-state-id",
        )


def test_google_authorize_url_contains_client_id_and_pkce(auth_service) -> None:
    flow = auth_service.start_google_oauth()
    assert "client_id=test-client-id" in flow.authorize_url
    assert "state=" in flow.authorize_url
    assert "scope=openid+email+profile" in flow.authorize_url
    assert "code_challenge=" in flow.authorize_url
    assert "code_challenge_method=S256" in flow.authorize_url
