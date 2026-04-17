"""Refresh-token issuance, rotation, and revocation."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from apps.auth.exceptions import (
    EmailNotVerifiedError,
    InvalidTokenError,
    RefreshTokenRevokedError,
    TokenExpiredError,
)
from apps.auth.models import RefreshToken
from apps.auth.schemas import TokenPair
from apps.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenError,
    TokenExpiredError as CoreTokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)
from apps.settings import app_settings
from apps.user.exceptions import UserNotFoundError

if TYPE_CHECKING:
    from apps.auth.repository import RefreshTokenRepository
    from apps.core.database.types import SessionType
    from apps.user.models import User
    from apps.user.services import UserService


class TokenService:
    """Mint, rotate, revoke, and resolve refresh/access tokens.

    This service owns the refresh-token lifecycle so higher-level flows
    (login, 2FA, OAuth) can delegate rather than duplicate the minting and
    rotation logic.
    """

    def __init__(
        self,
        *,
        user_service: UserService,
        refresh_token_repository: RefreshTokenRepository,
    ) -> None:
        self.user_service = user_service
        self.refresh_token_repository = refresh_token_repository

    async def issue_pair(
        self,
        session: SessionType,
        *,
        user: User,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[TokenPair, RefreshToken]:
        """Mint an access token + persist a hashed refresh token row.

        Returns:
            A tuple of (TokenPair, RefreshToken) so callers that need the
            persisted row (e.g. token rotation) avoid a redundant query.
        """
        access_token = create_access_token(subject=str(user.id))
        refresh_raw, refresh_expires_at = create_refresh_token(subject=str(user.id))

        refresh_row = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        session.add(refresh_row)
        await session.flush()

        pair = TokenPair(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=app_settings.auth.access_token_expire_minutes * 60,
        )
        return pair, refresh_row

    async def refresh(
        self,
        session: SessionType,
        *,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """Rotate a refresh token: revoke the old, issue a new pair."""
        try:
            payload = decode_token(raw_refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is None:
            raise RefreshTokenRevokedError()

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        user = await self.user_service.get_by_id(session, user_id=user_id)

        new_pair, new_refresh_row = await self.issue_pair(
            session, user=user, user_agent=user_agent, ip_address=ip_address
        )

        existing.revoked_at = datetime.datetime.now(datetime.UTC)
        existing.replaced_by_id = new_refresh_row.id
        await session.flush()

        return new_pair

    async def logout(self, session: SessionType, *, raw_refresh_token: str) -> None:
        """Revoke a refresh token. Idempotent — never raises on missing token."""
        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is not None:
            existing.revoked_at = datetime.datetime.now(datetime.UTC)
            await session.flush()

    async def user_from_access_token(self, session: SessionType, *, token: str) -> User:
        """Decode an access token and return the corresponding active user."""
        try:
            payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        try:
            user = await self.user_service.get_by_id(session, user_id=user_id)
        except UserNotFoundError as e:
            raise InvalidTokenError() from e

        if not user.is_active:
            raise EmailNotVerifiedError()
        return user
