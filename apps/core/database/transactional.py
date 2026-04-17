"""Transactional decorator for async repository / service methods."""

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from .types import SessionType

P = ParamSpec("P")
R = TypeVar("R")


def _extract_session(args: tuple, kwargs: dict) -> SessionType:
    """Locate the AsyncSession the wrapped function intends to use.

    Looks at the ``session`` kwarg first, then scans positional args for the
    first AsyncSession-like object.

    Args:
        args: Positional arguments passed to the wrapped function.
        kwargs: Keyword arguments passed to the wrapped function.

    Returns:
        The async session that the decorator should manage.

    Raises:
        RuntimeError: If no AsyncSession was supplied to the wrapped function.
    """
    candidate = kwargs.get("session")
    if candidate is None:
        for arg in args:
            if isinstance(arg, (AsyncSession, async_scoped_session)):
                candidate = arg
                break
    if candidate is None:
        msg = "@transactional requires an AsyncSession argument; none was provided."
        raise RuntimeError(msg)
    return candidate


def transactional[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run an async function inside a database transaction.

    Args:
        func: The async function to wrap.

    Returns:
        A wrapper preserving the original signature (via ``ParamSpec``).
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        session = _extract_session(args, kwargs)
        if session.in_transaction():
            return await func(*args, **kwargs)
        async with session.begin():
            return await func(*args, **kwargs)

    return wrapper
