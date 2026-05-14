"""Real-DB / real-ASGI integration test for the like-endpoint rate limit (T020).

Covers FR-024a — the ``POST /api/v1/public/workspaces/.../posts/.../like``
endpoint is decorated with ``@limiter.limit(POST_LIKE_RATE_LIMIT,
key_func=auth_user_key)`` (default ``"60/minute"``). When a single authed
user exceeds that budget within a minute, slowapi short-circuits the
call with HTTP 429 and a ``Retry-After`` header.

**Slowapi ordering quirk:** when a route is decorated with
``@limiter.limit(...)``, ``SlowAPIMiddleware`` deliberately skips that
route (see ``_should_exempt`` in slowapi/middleware.py) and lets the
decorator enforce the limit *from inside* the wrapped function body —
i.e. *after* FastAPI's ``Depends`` resolution. So an unauth or
missing-workspace request never even reaches the limiter; it short-
circuits earlier with 401 / 404. To actually exercise the limiter we
therefore need a fully-valid request chain: real user, real workspace,
real JWT. The post itself can still be a fake UUID because
``post_like_service.like`` raises ``PostNotFoundError`` *inside* the
handler, which is still inside the limiter's wrapper — by then the
budget has already been decremented.

We commit the user + workspace via a fresh session, generate a real
RS256-signed access token, hammer 61 requests, assert the 61st is 429
with ``Retry-After``, then clean everything up. The limiter's in-memory
storage is reset at the top and tail so a budget consumed by a prior
test in the same process does not bleed in.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.auth.security.jwt import generate_access_token
from apps.blog.constants import POST_LIKE_RATE_LIMIT
from apps.core.rate_limit import limiter
from apps.factory import app
from apps.user.models import User
from apps.user.repositories import UserRepository
from apps.user.schemas import CreateUserRequest
from apps.user.services import UserService
from apps.workspace.models import Workspace, WorkspaceMember
from apps.workspace.repositories import WorkspaceMemberRepository, WorkspaceRepository
from apps.workspace.schemas import CreateWorkspaceRequest
from apps.workspace.services import WorkspaceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def _parse_per_minute(spec: str) -> int:
    """Extract the count from a slowapi limit spec like ``"60/minute"``."""
    head = spec.split(";", maxsplit=1)[0].strip()
    count_str, _, _ = head.partition("/")
    return int(count_str.strip())


@pytest.mark.asyncio
async def test_like_rate_limit_returns_429_with_retry_after_once_budget_is_exhausted(
    real_engine: AsyncEngine,
) -> None:
    """61st authed POST /like within a minute → 429 + Retry-After."""
    limiter.reset()
    suffix = uuid.uuid4().hex[:10]
    slug = f"rl-{suffix}"
    workspace_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    factory = async_sessionmaker(real_engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with factory() as setup_session, setup_session.begin():
            user_service = UserService(repository=UserRepository())
            workspace_service = WorkspaceService(
                repository=WorkspaceRepository(),
                member_repository=WorkspaceMemberRepository(),
            )
            owner = await user_service.create(
                setup_session,
                data=CreateUserRequest(
                    email=f"rl-{suffix}@example.com",
                    username=f"rl{suffix}",
                    password="Pwd12345!",
                ),
            )
            owner.is_active = True
            owner_id = owner.id
            workspace = await workspace_service.create(
                setup_session,
                owner_user_id=owner.id,
                data=CreateWorkspaceRequest(
                    slug=slug,
                    name=f"RL {suffix}",
                    description=None,
                ),
            )
            workspace_id = workspace.id

        access_token = generate_access_token(subject=str(owner_id))
        headers = {"Authorization": f"Bearer {access_token}"}

        budget = _parse_per_minute(POST_LIKE_RATE_LIMIT)
        over_budget = budget + 1
        url = f"/api/v1/public/workspaces/{slug}/blog/posts/{uuid.uuid4()}/like"

        transport = httpx.ASGITransport(app=app)
        statuses: list[int] = []
        last_response: httpx.Response | None = None
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(over_budget):
                last_response = await client.post(url, headers=headers)
                statuses.append(last_response.status_code)

        assert last_response is not None
        assert statuses[-1] == 429, statuses
        assert statuses[:-1].count(429) == 0, statuses
        assert "Retry-After" in last_response.headers
        assert int(last_response.headers["Retry-After"]) > 0
        body = last_response.json()
        assert body["status"] == "error"
        assert "Rate limit" in body["message"]
    finally:
        limiter.reset()
        async with factory() as cleanup_session, cleanup_session.begin():
            if workspace_id is not None:
                await cleanup_session.execute(
                    delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id),
                )
                await cleanup_session.execute(
                    delete(Workspace).where(Workspace.id == workspace_id),
                )
            if owner_id is not None:
                await cleanup_session.execute(delete(User).where(User.id == owner_id))
