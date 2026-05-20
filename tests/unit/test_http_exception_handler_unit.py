"""Unit tests for the HTTPException → APIResponse-envelope handler (HIGH-1).

Routes that bypass :func:`backend_exception_handler` — unknown paths
(``404``), disallowed methods (``405``), or any ``HTTPException`` raised
directly — must still return the documented ``{code, data, status,
message}`` envelope. The framework default ``{"detail": "..."}`` shape
breaks every client that parses the envelope.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from starlette.exceptions import HTTPException

from apps.core.exceptions.handlers import http_exception_handler
from apps.core.schemas.response import JsonResponseStatuses, ResponseCodes


def _body(response) -> dict:
    return json.loads(bytes(response.body).decode("utf-8"))


def test_404_returns_api006_envelope() -> None:
    request = MagicMock()
    exc = HTTPException(status_code=404, detail="Not Found")

    response = http_exception_handler(request, exc)

    assert response.status_code == 404
    body = _body(response)
    assert body["code"] == ResponseCodes.API006
    assert body["data"] is None
    assert body["status"] == JsonResponseStatuses.FAIL
    assert body["message"] == "Not Found"


def test_405_falls_back_to_api001_for_unmapped_4xx() -> None:
    """405 has no dedicated business code; it must fall back to API001 (generic 4xx)."""
    request = MagicMock()
    exc = HTTPException(status_code=405, detail="Method Not Allowed")

    response = http_exception_handler(request, exc)

    assert response.status_code == 405
    body = _body(response)
    assert body["code"] == ResponseCodes.API001
    assert body["status"] == JsonResponseStatuses.FAIL
    assert body["message"] == "Method Not Allowed"


def test_500_falls_back_to_api003_for_unmapped_5xx() -> None:
    request = MagicMock()
    exc = HTTPException(status_code=503, detail="Service Unavailable")

    response = http_exception_handler(request, exc)

    assert response.status_code == 503
    body = _body(response)
    assert body["code"] == ResponseCodes.API003
    assert body["status"] == JsonResponseStatuses.ERROR


def test_403_maps_to_api005() -> None:
    request = MagicMock()
    exc = HTTPException(status_code=403, detail="forbidden")

    response = http_exception_handler(request, exc)

    body = _body(response)
    assert body["code"] == ResponseCodes.API005
    assert body["status"] == JsonResponseStatuses.FAIL


def test_dict_detail_is_stringified() -> None:
    """``HTTPException`` accepts arbitrary detail payloads; ensure the envelope's
    ``message`` field is always a string so clients can render it directly."""
    request = MagicMock()
    exc = HTTPException(status_code=400, detail={"field": "value"})

    response = http_exception_handler(request, exc)

    body = _body(response)
    assert isinstance(body["message"], str)
    assert "field" in body["message"]


def test_response_propagates_exception_headers() -> None:
    request = MagicMock()
    exc = HTTPException(
        status_code=401,
        detail="auth required",
        headers={"WWW-Authenticate": 'Bearer realm="api"'},
    )

    response = http_exception_handler(request, exc)

    assert response.headers.get("WWW-Authenticate") == 'Bearer realm="api"'
