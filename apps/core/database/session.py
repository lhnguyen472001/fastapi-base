import asyncio
from collections.abc import AsyncGenerator
from contextvars import ContextVar, Token
from typing import Any

from loguru import logger
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.expression import Select

from .engine import SQLAlchemyEngineTypes, engine_factory

__all__ = ("session_factory",)


session_ctx: ContextVar[int] = ContextVar("session_ctx", default=0)
session_ctx_token: ContextVar[Token[int] | None] = ContextVar("session_ctx_token", default=None)


def get_session_ctx() -> int:
    """Get the session context."""
    return session_ctx.get()


def set_session_ctx(session_id: int) -> None:
    """Set the session context."""
    token = session_ctx.set(session_id)
    session_ctx_token.set(token)


def reset_session_ctx() -> None:
    """Reset the session context."""
    token = session_ctx_token.get()
    if token is not None:
        session_ctx.reset(token)
        session_ctx_token.set(None)


class RoutingSession(Session):
    """Session that routes statements between the reader and writer engines.

    Routing rules, in order of precedence:

    1. ``Update`` / ``Delete`` / ``Insert`` clauses always go to the writer.
    2. ``SELECT ... FOR UPDATE`` goes to the writer (the replica cannot
       hold a row lock that a later write would honour).
    3. Once any of the above has fired in this session lifetime, every
       subsequent statement also routes to the writer (sticky read-after-
       write). The flag is reset by ``scoped_session.remove()`` between
       requests because that destroys the session entirely.
    4. Otherwise (pre-write SELECTs), route to the reader.

    The previous implementation used ``self.in_transaction()`` plus the
    private ``self._flushing`` attribute to decide writer vs reader. SA
    autobegins a transaction on the first ``execute``, so under that
    heuristic every SELECT after the first one routed to the writer —
    silently wasting the read replica.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Set lazily on the first writer-bound statement; sticky for the
        # remaining lifetime of this session so reads-after-write see the
        # data they just committed instead of stale replica state.
        self._wrote: bool = False

    def get_bind(
        self,
        _mapper: dict[str, Any] | None = None,
        *,
        clause: ClauseElement | None = None,
        **_kwargs: Any,
    ) -> Engine | Connection:
        """Pick the engine for ``clause`` per the routing rules above."""
        is_dml = isinstance(clause, (Update, Delete, Insert))
        is_locking_select = isinstance(clause, Select) and clause._for_update_arg is not None
        if is_dml or is_locking_select or self._wrote:
            self._wrote = True
            return engine_factory(SQLAlchemyEngineTypes.WRITER).sync_engine

        return engine_factory(SQLAlchemyEngineTypes.READER).sync_engine


async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    class_=AsyncSession,
    sync_session_class=RoutingSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


scoped_session = async_scoped_session(session_factory=async_session_factory, scopefunc=get_session_ctx)


def get_current_session() -> async_scoped_session[AsyncSession]:
    """Get the current session."""
    return scoped_session()


async def session_factory() -> AsyncGenerator[async_scoped_session[AsyncSession]]:
    """Yield a request-scoped session and manage its full lifecycle."""
    set_session_ctx(session_id=id(asyncio.current_task()))
    session = scoped_session()
    try:
        try:
            yield session
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        else:
            if session.in_transaction():
                await session.commit()
    finally:
        try:
            await scoped_session.remove()
        except SQLAlchemyError:
            logger.exception("session_factory - scoped_session.remove() failed")
        finally:
            reset_session_ctx()
