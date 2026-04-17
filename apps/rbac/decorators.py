"""Route decorators for RBAC and ABAC enforcement.

Both decorators expect the wrapped FastAPI route to declare:

* ``current_user: User = Depends(get_current_user)``
* ``access_service: AccessService = Depends(Provide[RBACContainer.access_service])``

They preserve the route signature so FastAPI's dependency injection and
``@inject`` wiring continue to work.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from apps.rbac.exceptions import AccessDeniedError

if TYPE_CHECKING:
    from apps.rbac.services import AccessService

ObjectLoader = Callable[..., Awaitable[Any]]


def _extract(kwargs: dict[str, Any], name: str) -> Any:
    if name not in kwargs:
        raise RuntimeError(f"require_access/require_ownership: route must declare a parameter named '{name}'.")
    return kwargs[name]


def require_access(
    resource: str,
    action: str,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """RBAC gate: ensure ``current_user`` may perform ``action`` on ``resource``.

    Raises:
        AccessDeniedError: When the enforcer denies the request.
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user = _extract(kwargs, "current_user")
            access_service: AccessService = _extract(kwargs, "access_service")

            allowed = await access_service.check(user_id=current_user.id, resource=resource, action=action)
            if not allowed:
                raise AccessDeniedError(message=f"User lacks '{action}' on '{resource}'.")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_ownership(
    resource: str,
    action: str,
    *,
    loader: ObjectLoader,
    id_param: str = "id",
    id_attr: str = "id",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """ABAC gate: load the target object via ``loader`` and allow the request
    when the user owns it; otherwise consult RBAC as an override.

    The loader is an async callable ``(session, item_id) -> object | None``.
    The loaded object is stashed back into ``kwargs[f"_loaded_{id_param}"]`` so
    the route body can reuse it.

    Raises:
        AccessDeniedError: When neither ABAC nor RBAC allow the request.
    """

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user = _extract(kwargs, "current_user")
            access_service: AccessService = _extract(kwargs, "access_service")
            session = _extract(kwargs, "session")
            item_id = _extract(kwargs, id_param)

            obj = await loader(session, item_id)
            if obj is None:
                raise AccessDeniedError(message=f"{resource} {item_id} not found.")

            kwargs[f"_loaded_{id_param}"] = obj

            allowed = await access_service.check_object(
                user_id=current_user.id,
                obj=obj,
                action=action,
                resource=resource,
                id_attr=id_attr,
            )
            if not allowed:
                raise AccessDeniedError(message=f"User lacks '{action}' on '{resource}' {item_id}.")
            return await func(*args, **kwargs)

        return wrapper

    return decorator
