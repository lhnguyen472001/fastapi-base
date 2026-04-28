"""Unit tests for TokenService refresh-token reuse detection.

End-to-end auth tests against a real DB live in
``tests/integration/realdb/test_auth_service_realdb.py``. These tests
focus on the reuse-detection branch added in Phase 1 #9: when a presented
refresh token's hash exists in the database but is no longer active
(rotated or expired), the service must call ``revoke_all_for_user`` on
the entire family before raising ``RefreshTokenRevokedError``.
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.auth.exceptions import RefreshTokenRevokedError
from apps.auth.services._tokens import TokenService
from apps.core.security import create_refresh_token


def _make_service() -> tuple[TokenService, AsyncMock]:
    repo = AsyncMock()
    user_service = AsyncMock()
    service = TokenService(user_service=user_service, refresh_token_repository=repo)
    return service, repo


@pytest.mark.asyncio
async def test_refresh_revokes_family_when_token_was_previously_rotated() -> None:
    """An attacker presenting a previously-rotated token revokes the family."""
    service, repo = _make_service()
    session = AsyncMock()
    raw_token, _ = create_refresh_token(subject=str(uuid.uuid4()))
    repo.find_active_by_hash.return_value = None  # not active

    user_id = uuid.uuid4()
    revoked_row = MagicMock()
    revoked_row.user_id = user_id
    revoked_row.revoked_at = datetime.datetime.now(datetime.UTC)
    repo.find_by_hash.return_value = revoked_row

    with pytest.raises(RefreshTokenRevokedError):
        await service.refresh(session, raw_refresh_token=raw_token)

    repo.revoke_all_for_user.assert_awaited_once_with(session, user_id=user_id)


@pytest.mark.asyncio
async def test_refresh_does_not_revoke_when_token_unknown() -> None:
    """A forged token (signature valid but never issued) must NOT cascade-revoke."""
    service, repo = _make_service()
    session = AsyncMock()
    raw_token, _ = create_refresh_token(subject=str(uuid.uuid4()))
    repo.find_active_by_hash.return_value = None
    repo.find_by_hash.return_value = None  # token never existed

    with pytest.raises(RefreshTokenRevokedError):
        await service.refresh(session, raw_refresh_token=raw_token)

    repo.revoke_all_for_user.assert_not_awaited()
