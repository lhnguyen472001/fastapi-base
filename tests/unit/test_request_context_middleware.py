"""Unit tests for ``apps.core.middlewares.request_context.RequestContextMiddleware``.

Drives the middleware directly via ``httpx.AsyncClient`` + ``ASGITransport``
so we exercise the real ASGI receive/send protocol without spinning up
the full FastAPI app graph.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest
from loguru import logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from apps.core.middlewares.constants import REQUEST_ID_FALLBACK, REQUEST_ID_HEADER
from apps.core.middlewares.request_context import (
    RequestContextMiddleware,
    get_request_id,
    request_id_ctx,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _build_app(handler) -> RequestContextMiddleware:
    """Return a tiny Starlette app wrapped in the middleware under test."""
    app = Starlette(routes=[Route("/", handler)])
    return RequestContextMiddleware(app)


@pytest.fixture
async def client_with_echo() -> AsyncIterator[httpx.AsyncClient]:
    """Client whose only route echoes the bound request_id."""

    async def echo(_request: Request) -> Response:
        return JSONResponse({"request_id": get_request_id()})

    app = _build_app(echo)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.unit
async def test_generates_request_id_when_header_missing(client_with_echo: httpx.AsyncClient) -> None:
    response = await client_with_echo.get("/")

    assert response.status_code == 200
    request_id = response.headers[REQUEST_ID_HEADER]

    assert request_id != REQUEST_ID_FALLBACK
    assert len(request_id) == 32
    assert response.json()["request_id"] == request_id


@pytest.mark.unit
async def test_echoes_client_supplied_request_id(client_with_echo: httpx.AsyncClient) -> None:
    response = await client_with_echo.get("/", headers={REQUEST_ID_HEADER: "client-supplied-id"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client-supplied-id"
    assert response.json()["request_id"] == "client-supplied-id"


@pytest.mark.unit
async def test_blank_request_id_header_is_treated_as_missing(client_with_echo: httpx.AsyncClient) -> None:
    """A misbehaving upstream sending an empty header must not disable the id."""
    response = await client_with_echo.get("/", headers={REQUEST_ID_HEADER: "   "})

    assert response.status_code == 200
    generated = response.headers[REQUEST_ID_HEADER]
    assert generated != ""
    assert generated != REQUEST_ID_FALLBACK
    assert len(generated) == 32


@pytest.mark.unit
async def test_concurrent_requests_do_not_leak_request_id(client_with_echo: httpx.AsyncClient) -> None:
    """Each task must observe its own request_id even when interleaved."""
    inbound_ids = [f"req-{i:03d}" for i in range(50)]

    async def fire(req_id: str) -> str:
        response = await client_with_echo.get("/", headers={REQUEST_ID_HEADER: req_id})
        assert response.status_code == 200
        return response.json()["request_id"]

    observed = await asyncio.gather(*(fire(rid) for rid in inbound_ids))

    assert observed == inbound_ids


@pytest.mark.unit
async def test_loguru_records_inside_route_carry_bound_request_id() -> None:
    """A log line emitted from inside the route handler must see the bound id."""
    captured: list[dict] = []

    async def emit_log(_request: Request) -> Response:
        logger.info("inside route")
        return JSONResponse({"request_id": get_request_id()})

    sink_id = logger.add(lambda msg: captured.append(dict(msg.record["extra"])), level="DEBUG")
    try:
        app = _build_app(emit_log)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", headers={REQUEST_ID_HEADER: "log-corr-1"})
    finally:
        logger.remove(sink_id)

    assert response.status_code == 200
    in_route = [extra for extra in captured if extra.get("request_id") == "log-corr-1"]
    assert in_route, f"expected a captured record bound to log-corr-1, got: {captured}"


@pytest.mark.unit
async def test_non_http_scope_passes_through_without_binding() -> None:
    """Lifespan / websocket scopes must not bind a request_id."""
    seen: list[str] = []

    async def downstream(scope, receive, send) -> None:
        seen.append(get_request_id())
        if scope["type"] == "lifespan":
            message = await receive()
            assert message["type"] == "lifespan.startup"
            await send({"type": "lifespan.startup.complete"})

    middleware = RequestContextMiddleware(downstream)

    async def fake_receive() -> dict:
        return {"type": "lifespan.startup"}

    sent: list[dict] = []

    async def fake_send(message: dict) -> None:
        sent.append(message)

    await middleware({"type": "lifespan"}, fake_receive, fake_send)

    assert seen == [REQUEST_ID_FALLBACK]
    assert sent == [{"type": "lifespan.startup.complete"}]


@pytest.mark.unit
async def test_request_id_context_var_is_reset_after_request(client_with_echo: httpx.AsyncClient) -> None:
    """Outside the request the ContextVar must fall back to the default sentinel."""
    await client_with_echo.get("/", headers={REQUEST_ID_HEADER: "scope-a"})
    assert request_id_ctx.get() == REQUEST_ID_FALLBACK
