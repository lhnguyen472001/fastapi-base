"""Protocol types for the RBAC module.

Decouples service constructors from concrete Casbin classes so tests can
substitute stub implementations and so the service layer satisfies FR-021
(protocol-typed dependencies).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EnforcerProtocol(Protocol):
    """Subset of ``casbin.AsyncEnforcer`` consumed by ``AccessService``.

    ``enforce`` is intentionally synchronous in Casbin; callers wrap it in
    ``asyncio.to_thread`` for non-blocking dispatch. The Protocol matches
    that shape exactly so a concrete enforcer instance satisfies it
    without an adapter.
    """

    def enforce(self, *rvals: Any) -> bool: ...

    async def load_policy(self) -> None: ...

    async def add_policy(self, *params: str) -> bool: ...

    async def remove_policy(self, *params: str) -> bool: ...

    async def add_grouping_policy(self, *params: str) -> bool: ...

    async def remove_grouping_policy(self, *params: str) -> bool: ...

    def get_policy(self) -> list[list[str]]: ...

    def get_grouping_policy(self) -> list[list[str]]: ...
