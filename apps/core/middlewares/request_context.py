"""Per-request context middleware.

Generates (or echoes) a stable ``X-Request-ID`` for every HTTP request and
binds it onto the loguru logger so every log line emitted within the
request task carries ``request_id`` alongside the OpenTelemetry
``trace_id`` / ``span_id`` already injected by
:func:`apps.core.logging.record_formatter`.

The middleware is a raw ASGI callable (not :class:`starlette.middleware.base.BaseHTTPMiddleware`)
so it never buffers the request body — important for direct-to-S3 uploads
that stream the body through.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from loguru import logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.core.middlewares.constants import REQUEST_ID_FALLBACK, REQUEST_ID_HEADER

request_id_ctx: ContextVar[str] = ContextVar("request_id", default=REQUEST_ID_FALLBACK)


def get_request_id() -> str:
    """Return the request_id bound to the current asyncio task, or ``"-"``."""
    return request_id_ctx.get()


def _generate_request_id() -> str:
    """Generate a fresh request_id (32-char hex, no dashes)."""
    return uuid.uuid4().hex


def _extract_request_id(scope: Scope) -> str:
    """Pull ``X-Request-ID`` from request headers, or generate one.

    Header lookup is case-insensitive (Starlette stores headers as
    lowercased ``bytes``). A blank value is treated as missing so a
    misbehaving upstream cannot disable the request_id.
    """
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode("latin-1"):
            decoded = value.decode("latin-1").strip()
            if decoded:
                return decoded
            break
    return _generate_request_id()


class RequestContextMiddleware:
    """ASGI middleware that binds ``request_id`` per request.

    Responsibilities:
        * Resolve the inbound ``X-Request-ID`` (or generate a UUID4 hex).
        * Store it in :data:`request_id_ctx` so downstream code (services,
          repositories, background tasks spawned within the request)
          can recover it via :func:`get_request_id`.
        * Bind it onto loguru via :meth:`loguru.Logger.contextualize` so
          every log line in the request scope carries it.
        * Echo it back on the response via the ``X-Request-ID`` header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope)
        token = request_id_ctx.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                header_pair = (
                    REQUEST_ID_HEADER.encode("latin-1"),
                    request_id.encode("latin-1"),
                )
                headers = [(name, value) for name, value in headers if name != REQUEST_ID_HEADER.encode("latin-1")]
                headers.append(header_pair)
                message["headers"] = headers
            await send(message)

        try:
            with logger.contextualize(request_id=request_id):
                await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_ctx.reset(token)
