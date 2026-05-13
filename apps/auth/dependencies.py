"""FastAPI dependencies for the auth module."""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.containers import AuthContainer
from apps.auth.exceptions import InvalidTokenError
from apps.auth.services import AuthService
from apps.core.database.session import session_factory
from apps.user.models import User

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer JWT access token")


@inject
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> User:
    """Resolve the current user from a Bearer access token.

    Raises:
        InvalidTokenError: If the Authorization header is missing or the token
            is invalid / expired / refers to a deleted user.
    """
    if credentials is None or credentials.scheme != "Bearer":
        raise InvalidTokenError(message="Missing or malformed Authorization header.")

    return await auth_service.get_user_from_access_token(session, token=credentials.credentials)


@inject
async def get_current_user_or_anonymous(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(session_factory),
    auth_service: AuthService = Depends(Provide[AuthContainer.auth_service]),
) -> User | None:
    """Resolve the current user iff a valid Bearer token is present; else None.

    Used by public read endpoints that want to personalize the response for
    a logged-in caller (e.g. ``PostDetailResponse.liked_by_me``) without
    rejecting anonymous traffic. A missing or malformed Authorization
    header returns ``None``; an *invalid* / expired / revoked token still
    raises so a stale-token caller can't silently degrade to anonymous.
    """
    if credentials is None or credentials.scheme != "Bearer":
        return None
    return await auth_service.get_user_from_access_token(session, token=credentials.credentials)
