"""Unit tests for decoration-time signature validation on RBAC decorators (F-QUAL-4).

Before this change the decorators in :mod:`apps.rbac.decorators` rely on
``_extract(kwargs, name)`` to fail at request time when a route forgot
to declare ``current_user``, ``access_service``, ``session``, or the
``id_param``. That is a latency-bombing footgun — the misconfigured
route deploys, then 500s on the first hit.

After F-QUAL-4 the decorator raises ``TypeError`` at decoration time
(import time, effectively) so misconfigured routes fail fast in CI /
local dev.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.rbac.decorators import require_access, require_ownership

# ---------------------------------------------------------------------------
# require_access — needs ``current_user`` and ``access_service`` parameters.
# ---------------------------------------------------------------------------


def test_require_access_accepts_function_with_required_params() -> None:
    @require_access("posts", "read")
    async def good_route(*, current_user: Any, access_service: Any) -> str:
        return "ok"

    assert good_route is not None  # decoration succeeded


def test_require_access_rejects_function_missing_current_user() -> None:
    with pytest.raises(TypeError, match="current_user"):

        @require_access("posts", "read")
        async def bad_route(*, access_service: Any) -> str:
            return "no"


def test_require_access_rejects_function_missing_access_service() -> None:
    with pytest.raises(TypeError, match="access_service"):

        @require_access("posts", "read")
        async def bad_route(*, current_user: Any) -> str:
            return "no"


# ---------------------------------------------------------------------------
# require_ownership — needs ``current_user``, ``access_service``, ``session``,
# and the configurable ``id_param``.
# ---------------------------------------------------------------------------


async def _noop_loader(_session: Any, _item_id: Any) -> Any:  # pragma: no cover
    return None


def test_require_ownership_accepts_function_with_default_id_param() -> None:
    @require_ownership("posts", "edit", loader=_noop_loader)
    async def good_route(*, current_user: Any, access_service: Any, session: Any, id: Any) -> str:  # noqa: A002
        return "ok"

    assert good_route is not None


def test_require_ownership_rejects_function_missing_id_param() -> None:
    with pytest.raises(TypeError, match="post_id"):

        @require_ownership("posts", "edit", loader=_noop_loader, id_param="post_id")
        async def bad_route(*, current_user: Any, access_service: Any, session: Any) -> str:
            return "no"


def test_require_ownership_rejects_function_missing_session() -> None:
    with pytest.raises(TypeError, match="session"):

        @require_ownership("posts", "edit", loader=_noop_loader)
        async def bad_route(*, current_user: Any, access_service: Any, id: Any) -> str:  # noqa: A002
            return "no"
