"""Refresh-token issuance, rotation, and revocation."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from apps.auth.constants import USER_CACHE_KEY_PREFIX, USER_CACHE_TTL_SECONDS
from apps.auth.enums import TokenType
from apps.auth.exceptions import (
    EmailNotVerifiedError,
    InvalidTokenError,
    RefreshTokenRevokedError,
    TokenExpiredError,
)
from apps.auth.models import RefreshToken
from apps.auth.schemas import TokenPair
from apps.auth.security import (
    TokenError,
    TokenExpiredError as CoreTokenExpiredError,
    decode_token,
    generate_access_token,
    generate_refresh_token,
    hash_token,
)
from apps.core.redis import CacheManager
from apps.settings import app_settings
from apps.user.exceptions import UserNotFoundError
from apps.user.models import User

if TYPE_CHECKING:
    from apps.auth.repository import RefreshTokenRepository
    from apps.core.database.types import SessionType
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
        cache: CacheManager | None = None,
    ) -> None:
        self.user_service = user_service
        self.refresh_token_repository = refresh_token_repository
        self.cache = cache if cache is not None else CacheManager(None)

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
        access_token = generate_access_token(subject=str(user.id))
        refresh_raw, refresh_expires_at = generate_refresh_token(subject=str(user.id))

        refresh_row = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        refresh_row = await self.refresh_token_repository.add(session, refresh_row, expunge=False)

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
            payload = decode_token(raw_refresh_token, expected_type=TokenType.REFRESH)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is None:
            # Reuse-detection: the token was previously issued (signature is
            # valid, but the active-by-hash lookup missed it) — meaning it
            # was already rotated or expired. Treat as a likely theft of a
            # rotated token and revoke every active descendant in the
            # family so the attacker's freshly-rotated token also dies.
            previous = await self.refresh_token_repository.find_by_hash(session, token_hash=token_hash_value)
            if previous is not None:
                await self.refresh_token_repository.revoke_all_for_user(session, user_id=previous.user_id)
            raise RefreshTokenRevokedError()

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        user = await self.user_service.find_or_raise(session, user_id=user_id)

        new_pair, new_refresh_row = await self.issue_pair(
            session, user=user, user_agent=user_agent, ip_address=ip_address
        )

        await self.refresh_token_repository.update(
            session,
            item_id=existing.id,
            data={
                "revoked_at": datetime.datetime.now(datetime.UTC),
                "replaced_by_id": new_refresh_row.id,
            },
        )

        return new_pair

    async def logout(self, session: SessionType, *, raw_refresh_token: str) -> None:
        """Revoke a refresh token. Idempotent — never raises on missing token."""
        token_hash_value = hash_token(raw_refresh_token)
        existing = await self.refresh_token_repository.find_active_by_hash(session, token_hash=token_hash_value)
        if existing is not None:
            await self.refresh_token_repository.update(
                session,
                item_id=existing.id,
                data={"revoked_at": datetime.datetime.now(datetime.UTC)},
            )

    async def user_from_access_token(self, session: SessionType, *, token: str) -> User:
        """Decode an access token and return the corresponding active user.

        Cache-aside: a hit returns a transient ``User`` rebuilt from the
        cached field dict (no SQLAlchemy session attachment). Routes that
        only read scalar columns (id, email, is_active, ...) are unaffected;
        callers that need lazy-loaded relationships must use
        :meth:`UserService.find_or_raise` directly.
        """
        try:
            payload = decode_token(token, expected_type=TokenType.ACCESS)
        except CoreTokenExpiredError as e:
            raise TokenExpiredError() from e
        except TokenError as e:
            raise InvalidTokenError() from e

        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as e:
            raise InvalidTokenError() from e

        cache_key = f"{USER_CACHE_KEY_PREFIX}:{user_id}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            user = self._user_from_cache_dict(cached)
            if not user.is_active:
                raise EmailNotVerifiedError()
            return user

        try:
            user = await self.user_service.find_or_raise(session, user_id=user_id)
        except UserNotFoundError as e:
            raise InvalidTokenError() from e

        if not user.is_active:
            raise EmailNotVerifiedError()

        await self.cache.set(cache_key, self._user_to_cache_dict(user), ttl=USER_CACHE_TTL_SECONDS)
        return user

    async def invalidate_user_cache(self, user_id: uuid.UUID) -> None:
        """Drop the cached User entry for ``user_id``.

        Call this after any mutation that affects auth-relevant fields
        (deactivation, email change, 2FA toggle, password reset). Safe to
        call when caching is disabled — no-ops cleanly.
        """
        await self.cache.delete(f"{USER_CACHE_KEY_PREFIX}:{user_id}")

    @staticmethod
    def _user_to_cache_dict(user: User) -> dict[str, Any]:
        """Project a ``User`` ORM instance to a JSON-safe dict for caching."""
        return {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "hashed_password": user.hashed_password,
            "is_active": user.is_active,
            "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
            "google_sub": user.google_sub,
            "totp_secret": user.totp_secret,
            "is_2fa_enabled": user.is_2fa_enabled,
            "last_totp_counter": user.last_totp_counter,
            "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }

    @staticmethod
    def _user_from_cache_dict(data: dict[str, Any]) -> User:
        """Rehydrate a transient ``User`` from a cached field dict.

        The returned instance is **not** session-attached. Callers must
        not pass it to ``session.merge`` / ``session.add`` without first
        re-fetching from the DB, since SQLAlchemy will treat it as a new
        row insert otherwise.
        """
        user = User(
            email=data["email"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            is_active=data["is_active"],
            google_sub=data["google_sub"],
            totp_secret=data["totp_secret"],
            is_2fa_enabled=data["is_2fa_enabled"],
            last_totp_counter=data["last_totp_counter"],
        )
        user.id = uuid.UUID(data["id"])
        user.email_verified_at = (
            datetime.datetime.fromisoformat(data["email_verified_at"]) if data["email_verified_at"] else None
        )
        user.deleted_at = datetime.datetime.fromisoformat(data["deleted_at"]) if data["deleted_at"] else None
        if data["created_at"]:
            user.created_at = datetime.datetime.fromisoformat(data["created_at"])
        if data["updated_at"]:
            user.updated_at = datetime.datetime.fromisoformat(data["updated_at"])
        return user
