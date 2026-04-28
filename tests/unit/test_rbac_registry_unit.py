"""Unit tests for the @rbac_resource decorator and resource registry."""

from __future__ import annotations

import pytest

import apps.product.models
import apps.user.models  # noqa: F401 — import for decorator side-effect
from apps.rbac.enums import ObjectAction
from apps.rbac.registry import (
    RegisteredResource,
    get_registered_resources,
    get_resource,
    rbac_resource,
)


def test_decorator_registers_class_with_actions() -> None:
    @rbac_resource("widget_test", actions=frozenset({ObjectAction.READ, ObjectAction.WRITE}))
    class _Widget:
        pass

    entry = get_resource("widget_test")

    assert entry is not None
    assert entry.name == "widget_test"
    assert entry.model_type is _Widget
    assert entry.actions == frozenset({ObjectAction.READ, ObjectAction.WRITE})


def test_decorator_stamps_resource_name_on_class() -> None:
    @rbac_resource("gadget_test", actions=frozenset({ObjectAction.READ}))
    class _Gadget:
        pass

    assert _Gadget.__rbac_resource_name__ == "gadget_test"


def test_re_registering_same_class_is_idempotent() -> None:
    @rbac_resource("widget_idempotent", actions=frozenset({ObjectAction.READ}))
    class _W:
        pass

    rbac_resource("widget_idempotent", actions=frozenset({ObjectAction.READ}))(_W)

    entry = get_resource("widget_idempotent")
    assert entry is not None
    assert entry.model_type is _W


def test_re_registering_different_class_under_same_name_raises() -> None:
    @rbac_resource("widget_collision", actions=frozenset({ObjectAction.READ}))
    class _A:
        pass

    with pytest.raises(ValueError, match="already registered"):

        @rbac_resource("widget_collision", actions=frozenset({ObjectAction.READ}))
        class _B:
            pass


def test_get_registered_resources_returns_a_copy() -> None:
    registry = get_registered_resources()
    assert isinstance(registry, dict)

    sentinel_name = "__sentinel_should_not_persist__"
    registry[sentinel_name] = RegisteredResource(name=sentinel_name, model_type=object, actions=frozenset())

    assert get_resource(sentinel_name) is None


def test_user_and_product_models_are_registered_at_import_time() -> None:
    """Importing the apps registers their models via the decorator side-effect."""
    registered = get_registered_resources()

    assert "user" in registered
    assert "product" in registered
    assert "product_category" in registered
    assert "product_image" in registered
