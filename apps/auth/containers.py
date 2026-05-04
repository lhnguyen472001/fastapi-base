"""Dependency injection container for the Auth module."""

from __future__ import annotations

from dependency_injector import containers, providers

from apps.auth.oauth import GoogleOAuthClient
from apps.auth.repository import EmailVerificationRepository, RefreshTokenRepository
from apps.auth.services import (
    AuthService,
    EmailVerificationService,
    OAuthService,
    TokenService,
    TwoFactorService,
)
from apps.core.email import EmailRenderer, SmtpEmailSender
from apps.core.redis import CacheManager, get_redis_client
from apps.settings import app_settings
from apps.user.repositories import UserRepository
from apps.user.services import UserService


class AuthContainer(containers.DeclarativeContainer):
    """Wires the auth service graph and activates @inject in routes/dependencies."""

    wiring_config = containers.WiringConfiguration(modules=["apps.auth.routes", "apps.auth.dependencies"])

    # Repositories
    user_repository = providers.Factory(UserRepository)
    refresh_token_repository = providers.Factory(RefreshTokenRepository)
    email_verification_repository = providers.Factory(EmailVerificationRepository)

    # Adjacent services
    user_service = providers.Factory(UserService, repository=user_repository)

    # Infrastructure
    email_sender = providers.Singleton(
        SmtpEmailSender,
        host=app_settings.email.smtp_host,
        port=app_settings.email.smtp_port,
        sender_name=app_settings.email.sender_name,
        sender_address=app_settings.email.sender_address,
        use_tls=app_settings.email.smtp_use_tls,
        username=app_settings.email.smtp_username.get_secret_value(),
        password=app_settings.email.smtp_password.get_secret_value(),
        timeout=app_settings.email.smtp_timeout_seconds,
    )
    email_renderer = providers.Singleton(
        EmailRenderer,
        template_dir=app_settings.email.template_dir,
    )
    google_oauth_client = providers.Singleton(
        GoogleOAuthClient,
        client_id=app_settings.auth.google_client_id,
        client_secret=app_settings.auth.google_client_secret.get_secret_value(),
        redirect_uri=app_settings.auth.google_redirect_uri,
    )
    cache_manager = providers.Singleton(CacheManager, redis_client=providers.Callable(get_redis_client))

    # Auth sub-services (per 3.2 split).
    token_service = providers.Factory(
        TokenService,
        user_service=user_service,
        refresh_token_repository=refresh_token_repository,
        cache=cache_manager,
    )
    email_verification_service = providers.Factory(
        EmailVerificationService,
        user_service=user_service,
        user_repository=user_repository,
        email_verification_repository=email_verification_repository,
        email_sender=email_sender,
        email_renderer=email_renderer,
    )
    two_factor_service = providers.Factory(TwoFactorService, user_repository=user_repository)
    oauth_service = providers.Factory(
        OAuthService,
        user_service=user_service,
        google_oauth_client=google_oauth_client,
    )

    # Facade consumed by routes / dependencies.
    auth_service = providers.Factory(
        AuthService,
        user_service=user_service,
        token_service=token_service,
        email_verification_service=email_verification_service,
        two_factor_service=two_factor_service,
        oauth_service=oauth_service,
    )
