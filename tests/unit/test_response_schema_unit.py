"""Unit tests for ``apps.core.schemas.response.APIResponse`` helpers."""

from __future__ import annotations

from apps.core.schemas.response import APIResponse, JsonResponseStatuses, ResponseCodes


def test_success_classmethod_builds_envelope_with_default_code() -> None:
    response = APIResponse[dict].success(data={"name": "x"}, message="ok")

    assert response.code == ResponseCodes.API000
    assert response.status == JsonResponseStatuses.SUCCESS
    assert response.message == "ok"
    assert response.data == {"name": "x"}


def test_success_classmethod_accepts_none_data() -> None:
    response = APIResponse[dict].success(message="empty")

    assert response.data is None
    assert response.status == JsonResponseStatuses.SUCCESS


def test_success_classmethod_accepts_custom_code() -> None:
    response = APIResponse[dict].success(data={"k": 1}, message="custom", code=ResponseCodes.API007)

    assert response.code == ResponseCodes.API007
    assert response.status == JsonResponseStatuses.SUCCESS
