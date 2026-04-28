"""Rate-limiting integration (slowapi) wired to the project's response shape.

Exposes a single module-level :data:`limiter` that route handlers decorate
with ``@limiter.limit("N/period", key_func=...)``. Storage backend is
configured via :data:`apps.settings.app_settings.rate_limit.storage_uri` —
``memory://`` for single-worker dev, ``redis://host:port/db`` for shared
multi-worker windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import ORJSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from apps.core.schemas.response import APIResponse, JsonResponseStatuses, ResponseCodes
from apps.settings import app_settings

if TYPE_CHECKING:
    from fastapi import Request

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=app_settings.rate_limit.storage_uri,
    enabled=app_settings.rate_limit.enabled,
    default_limits=[],
    headers_enabled=True,
    strategy="fixed-window",
)


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> ORJSONResponse:  # noqa: ARG001 — FastAPI handler signature
    """Convert ``RateLimitExceeded`` into the project's standard envelope.

    Preserves the ``Retry-After`` header that ``slowapi`` would normally set
    via its own handler so well-behaved clients can back off automatically.
    """
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover — type guard
        raise exc
    body = APIResponse[None](
        code=ResponseCodes.API008,
        data=None,
        status=JsonResponseStatuses.ERROR,
        message=f"Rate limit exceeded: {exc.detail}",
    )
    response = ORJSONResponse(
        content=body.model_dump(),
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response.headers["Retry-After"] = str(getattr(exc, "retry_after", 60))
    return response
