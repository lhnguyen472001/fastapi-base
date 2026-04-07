from contextvars import ContextVar, Token
from typing import Any, AsyncGenerator, Dict

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session, async_sessionmaker
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
    """Session that routes to the appropriate engine based on the type of query."""

    def get_bind(
        self,
        mapper: Dict[str, Any] | None = None,
        *,
        clause: ClauseElement | None = None,
        **kw: Any,
    ) -> Engine | Connection:
        """Route writes, locking selects, and in-flight transactions to the writer.

        SELECT ... FOR UPDATE statements MUST hit the writer because the read
        replica cannot hold a row lock that the subsequent write would honour.
        """
        if (
            self._flushing
            or self.in_transaction()
            or isinstance(clause, (Update, Delete, Insert))
            or (isinstance(clause, Select) and clause._for_update_arg is not None)
        ):
            return engine_factory(SQLAlchemyEngineTypes.WRITER).sync_engine

        return engine_factory(SQLAlchemyEngineTypes.READER).sync_engine


_async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    class_=AsyncSession,
    sync_session_class=RoutingSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


scoped_session = async_scoped_session(session_factory=_async_session_factory, scopefunc=get_session_ctx)


def get_current_session() -> async_scoped_session[AsyncSession]:
    """Get the current session."""
    return scoped_session()


async def session_factory() -> AsyncGenerator[AsyncSession, None]:
    """Factory for creating async sessions."""
    session = scoped_session()

    try:
        yield session

    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
