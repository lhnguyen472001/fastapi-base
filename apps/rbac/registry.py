"""Resource registry: pair ORM models with their RBAC resource name + actions.

Domain models opt in to RBAC by decorating themselves::

    @rbac_resource("product", actions=frozenset({ObjectAction.READ, ObjectAction.WRITE}))
    class Product(UUIDAuditBase): ...

The registry is in-memory and populated at import time. It serves two
purposes:

1. **Discoverability** — admin tooling can enumerate every resource the
   app gates and the verbs it accepts (e.g. for a "Permissions" UI that
   lists possible ``(resource, action)`` pairs).
2. **Validation hook** — a future check can refuse ``access_required``
   calls naming an unregistered resource or an action the resource has
   not declared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from apps.rbac.enums import ObjectAction


T = TypeVar("T", bound=type)


@dataclass(frozen=True, slots=True)
class RegisteredResource:
    """Metadata for one ORM model registered as an RBAC resource.

    ``name`` is the wire-format string used in Casbin policies and in
    ``access_required(resource, action)`` calls. ``model_type`` is the
    decorated class. ``actions`` is the closed set of verbs callers may
    legitimately ask the enforcer to check on this resource.
    """

    name: str
    model_type: type
    actions: frozenset[ObjectAction]


_RESOURCE_REGISTRY: dict[str, RegisteredResource] = {}


def rbac_resource(
    name: str,
    *,
    actions: frozenset[ObjectAction],
) -> Callable[[T], T]:
    """Class decorator that registers ``cls`` as an RBAC resource.

    Stamps ``cls.__rbac_resource_name__`` so callers that have only the
    class (e.g. ``Product``) can discover its resource name without
    re-consulting the registry. Re-registering a name with a different
    class raises ``ValueError`` to catch accidental typos.
    """

    def decorator(cls: T) -> T:
        existing = _RESOURCE_REGISTRY.get(name)
        if existing is not None and existing.model_type is not cls:
            msg = (
                f"RBAC resource '{name}' is already registered to "
                f"{existing.model_type.__qualname__}; cannot re-register to "
                f"{cls.__qualname__}."
            )
            raise ValueError(msg)
        _RESOURCE_REGISTRY[name] = RegisteredResource(
            name=name,
            model_type=cls,
            actions=actions,
        )
        cls.__rbac_resource_name__ = name  # type: ignore[attr-defined]
        return cls

    return decorator


def get_registered_resources() -> dict[str, RegisteredResource]:
    """Return a shallow copy of the resource registry.

    Returning a copy keeps callers from mutating the live registry; the
    underlying ``RegisteredResource`` objects are frozen dataclasses so
    sharing them is safe.
    """
    return dict(_RESOURCE_REGISTRY)


def get_resource(name: str) -> RegisteredResource | None:
    """Look up a single registered resource by its wire-format name."""
    return _RESOURCE_REGISTRY.get(name)
