"""Unit tests for apps/rbac/services/_access.py — AccessService.

Regression coverage for the async-correctness contract: callers in
``apps/rbac/dependencies.py`` and ``apps/rbac/decorators.py`` ``await`` these
methods, so they MUST be coroutine functions. Sync ``def`` returning ``bool``
would make ``await`` raise ``TypeError`` at runtime, which the global handler
turns into HTTP 500 on every gated route.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.rbac.services import AccessService


def test_check_is_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(AccessService.check)


def test_check_object_is_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(AccessService.check_object)


def _make_service(*, enforce_return: bool = False) -> AccessService:
    enforcer = MagicMock()
    enforcer.enforce = MagicMock(return_value=enforce_return)
    return AccessService(enforcer=enforcer)


@pytest.mark.asyncio
async def test_check_returns_enforcer_result_as_bool() -> None:
    service = _make_service(enforce_return=True)

    allowed = await service.check(user_id=uuid.uuid4(), resource="post", action="read")

    assert allowed is True


@pytest.mark.asyncio
async def test_check_object_owner_short_circuits_without_enforcer() -> None:
    service = _make_service(enforce_return=False)
    user_id = uuid.uuid4()
    obj: Any = type("Obj", (), {"owner_id": user_id})()

    allowed = await service.check_object(user_id=user_id, obj=obj, action="edit")

    assert allowed is True
    service.enforcer.enforce.assert_not_called()


@pytest.mark.asyncio
async def test_check_object_falls_back_to_rbac_when_no_instance_grant() -> None:
    service = _make_service(enforce_return=True)
    obj: Any = type("Obj", (), {"owner_id": uuid.uuid4(), "id": uuid.uuid4()})()

    allowed = await service.check_object(
        user_id=uuid.uuid4(),
        obj=obj,
        action="edit",
        resource="post",
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_check_object_returns_false_when_resource_missing_and_not_owner() -> None:
    service = _make_service(enforce_return=False)
    obj: Any = type("Obj", (), {"owner_id": uuid.uuid4()})()

    allowed = await service.check_object(user_id=uuid.uuid4(), obj=obj, action="edit")

    assert allowed is False
