"""Real-MailHog integration tests for SmtpEmailSender + AuthService.

These tests skip cleanly when MailHog isn't running locally so the rest of
the suite remains green in environments without the compose stack up.
Start MailHog with::

    docker compose up -d mailhog
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from apps.auth.oauth import GoogleOAuthClient
from apps.auth.repository import EmailVerificationRepository, RefreshTokenRepository
from apps.auth.schemas import RegisterRequest
from apps.auth.services import (
    AuthService,
    EmailVerificationService,
    OAuthService,
    TokenService,
    TwoFactorService,
)
from apps.core.email import EmailMessage, EmailRenderer, SmtpEmailSender
from apps.settings import app_settings
from apps.user.repositories import UserRepository
from apps.user.services import UserService
from tests.integration.realdb._mailhog import MailHogClient, is_reachable

# `_decode_part` is a private classmethod we re-use in one assertion below.
_decode_part = MailHogClient._decode_part

pytestmark = pytest.mark.skipif(not is_reachable(), reason="MailHog not reachable on localhost:8025")


@pytest_asyncio.fixture
async def mailhog() -> MailHogClient:
    client = MailHogClient()
    await client.clear_inbox()
    return client


@pytest.fixture
def smtp_sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        host=app_settings.email.smtp_host,
        port=app_settings.email.smtp_port,
        sender_name=app_settings.email.sender_name,
        sender_address=app_settings.email.sender_address,
        use_tls=False,
        timeout=5,
    )


@pytest.fixture
def email_renderer() -> EmailRenderer:
    return EmailRenderer(app_settings.email.template_dir)


@pytest.fixture
def auth_service_real_smtp(smtp_sender: SmtpEmailSender, email_renderer: EmailRenderer) -> AuthService:
    user_service = UserService(repository=UserRepository())
    refresh_token_repository = RefreshTokenRepository()
    email_verification_repository = EmailVerificationRepository()
    google_oauth_client = GoogleOAuthClient(client_id="test", client_secret="test", redirect_uri="http://test")

    token_service = TokenService(
        user_service=user_service,
        refresh_token_repository=refresh_token_repository,
    )
    email_verification_service = EmailVerificationService(
        user_service=user_service,
        email_verification_repository=email_verification_repository,
        email_sender=smtp_sender,
        email_renderer=email_renderer,
    )
    two_factor_service = TwoFactorService()
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


# ----------------------------- direct sender -------------------------------


async def test_smtp_sender_delivers_to_mailhog(smtp_sender, mailhog) -> None:
    recipient = f"direct_{uuid.uuid4().hex[:8]}@example.com"
    await smtp_sender.send(
        EmailMessage(
            to=recipient,
            subject="Hello from SmtpEmailSender",
            body="This is the plain-text body.",
        )
    )

    delivered = await mailhog.latest_for(recipient)
    assert delivered is not None
    assert "Hello from SmtpEmailSender" in delivered["Content"]["Headers"]["Subject"][0]
    assert "plain-text body" in delivered["Content"]["Body"]


async def test_smtp_sender_delivers_html_alternative(smtp_sender, mailhog) -> None:
    recipient = f"html_{uuid.uuid4().hex[:8]}@example.com"
    await smtp_sender.send(
        EmailMessage(
            to=recipient,
            subject="HTML test",
            body="Plain version",
            html_body="<h1>HTML version</h1>",
        )
    )

    html = await mailhog.latest_html_for(recipient)
    assert html is not None
    assert "HTML version" in html
    assert "<h1>" in html


async def test_smtp_sender_handles_unicode(smtp_sender, mailhog) -> None:
    recipient = f"unicode_{uuid.uuid4().hex[:8]}@example.com"
    body = "Unicode body — café · 日本語 · 🔑"
    await smtp_sender.send(EmailMessage(to=recipient, subject="Unicode test", body=body))

    delivered = await mailhog.latest_for(recipient)
    assert delivered is not None

    # Decode the Content-Transfer-Encoding (likely base64 for unicode bodies)
    # and verify the original characters round-tripped intact.
    decoded = MailHogClient._decode_part(delivered.get("Content", {}))
    assert "café" in decoded
    assert "日本語" in decoded
    assert "🔑" in decoded


# ------------------------------ register flow ------------------------------


async def test_register_flow_delivers_otp_via_mailhog(real_session, auth_service_real_smtp, mailhog) -> None:
    """Full register → MailHog → verify_email round-trip with real SMTP."""
    suffix = uuid.uuid4().hex[:8]
    payload = RegisterRequest(
        email=f"flow_{suffix}@example.com",
        username=f"flow_{suffix}",
        password="Sup3rSecret!",
    )

    user = await auth_service_real_smtp.register(real_session, data=payload)
    await real_session.flush()
    assert user.is_active is False

    code = await mailhog.find_otp_for(payload.email)
    assert code is not None, "OTP code not found in MailHog inbox"

    activated = await auth_service_real_smtp.verify_email(real_session, email=payload.email, code=code)
    await real_session.flush()
    assert activated.is_active is True
    assert activated.email_verified_at is not None

    # The HTML alternative must also reach MailHog with the same code.
    html_body = await mailhog.latest_html_for(payload.email)
    assert html_body is not None
    assert code in html_body
    assert "<html" in html_body.lower()


async def test_register_swallows_smtp_failure(real_session, auth_service_real_smtp, monkeypatch) -> None:
    """A downed SMTP server must not abort registration."""

    async def boom(_message):
        raise RuntimeError("SMTP is down")

    monkeypatch.setattr(auth_service_real_smtp.email_verification_service.email_sender, "send", boom)

    suffix = uuid.uuid4().hex[:8]
    payload = RegisterRequest(
        email=f"swallow_{suffix}@example.com",
        username=f"swallow_{suffix}",
        password="Sup3rSecret!",
    )

    user = await auth_service_real_smtp.register(real_session, data=payload)
    await real_session.flush()

    # User row was still created even though delivery failed.
    assert user.id is not None
    assert user.is_active is False
