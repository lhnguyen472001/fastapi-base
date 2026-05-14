"""Real-DB / real-ASGI test for anon comment-create rate-limit (T033).

Covers FR-024b — ``POST /api/v1/public/workspaces/.../posts/.../comments``
on the anonymous path is decorated with
``@limiter.limit(POST_COMMENT_ANONYMOUS_RATE_LIMIT,
key_func=anonymous_ip_key)`` (default ``"3/minute;30/day"``). The 4th
unauth submission from the same source IP within one minute therefore
returns 429 with a ``Retry-After`` header.

As with the like-endpoint rate-limit test, the slowapi decorator
enforces the budget *inside* the handler body — after FastAPI's
``Depends`` resolution. So the route's workspace lookup, the
``get_current_user_or_anonymous`` resolver, and the request-body
validator must all succeed for the limiter to even see the request. We
therefore need a real workspace whose ``allow_anonymous_comments`` flag
is True; the post itself can still be a fake UUID because the failure
inside the service (``PostNotFoundError``) is still inside the
limiter's wrapper and the budget has already been decremented.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.blog.constants import POST_COMMENT_ANONYMOUS_RATE_LIMIT
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
    """Extract the per-minute count from a slowapi spec like ``"3/minute;30/day"``."""
    head = spec.split(";", maxsplit=1)[0].strip()
    count_str, _, _ = head.partition("/")
    return int(count_str.strip())


@pytest.mark.asyncio
async def test_anonymous_comment_rate_limit_returns_429_after_4th_request(
    real_engine: AsyncEngine,
) -> None:
    """4th anonymous POST /comments within a minute → 429 + Retry-After."""
    limiter.reset()
    suffix = uuid.uuid4().hex[:10]
    slug = f"crl-{suffix}"
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
                    email=f"crl-{suffix}@example.com",
                    username=f"crl{suffix}",
                    password="Pwd12345!",
                ),
            )
            owner_id = owner.id
            workspace = await workspace_service.create(
                setup_session,
                owner_user_id=owner.id,
                data=CreateWorkspaceRequest(
                    slug=slug,
                    name=f"CRL {suffix}",
                    description=None,
                ),
            )
            workspace.allow_anonymous_comments = True
            workspace_id = workspace.id

        budget = _parse_per_minute(POST_COMMENT_ANONYMOUS_RATE_LIMIT)
        over_budget = budget + 1
        url = f"/api/v1/public/workspaces/{slug}/blog/posts/{uuid.uuid4()}/comments"
        body = {"body": "anon probe", "author_display_name": "probe", "author_email": None}

        transport = httpx.ASGITransport(app=app)
        statuses: list[int] = []
        last_response: httpx.Response | None = None
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(over_budget):
                last_response = await client.post(url, json=body)
                statuses.append(last_response.status_code)

        assert last_response is not None
        assert statuses[-1] == 429, statuses
        assert statuses[:-1].count(429) == 0, statuses
        assert "Retry-After" in last_response.headers
        assert int(last_response.headers["Retry-After"]) > 0
        envelope = last_response.json()
        assert envelope["status"] == "error"
        assert "Rate limit" in envelope["message"]
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
