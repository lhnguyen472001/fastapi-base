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
