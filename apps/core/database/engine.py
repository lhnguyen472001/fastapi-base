"""Lazy SQLAlchemy async engine factory.

Engines are NOT instantiated at import time — `engine_factory()` builds them
on first call and caches via `lru_cache`. This makes the module safe to import
in test environments that swap out settings or run without a database.

Read/write split: when ``DB_READER_HOST`` is set in the environment, the
:class:`DatabaseSettings` validator populates ``reader_uri`` and the reader
engine connects to that replica. Otherwise the reader engine reuses the
writer URI (single-DB deployment); ``RoutingSession`` still caches reader
and writer as distinct engine instances so the routing logic itself works
the same in both topologies.
"""

import enum
import functools

from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.settings import app_settings


class SQLAlchemyEngineTypes(enum.StrEnum):
    """SQLAlchemy engine types."""

    READER = "reader"
    WRITER = "writer"


def _build_engine(database_uri: URL) -> AsyncEngine:
    """Construct an AsyncEngine for ``database_uri`` using the configured pool sizing."""
    db = app_settings.db
    return create_async_engine(
        database_uri,
        pool_pre_ping=db.pool_pre_ping,
        pool_recycle=db.pool_recycle,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
    )


@functools.cache
def engine_factory(
    engine_type: SQLAlchemyEngineTypes = SQLAlchemyEngineTypes.READER,
) -> AsyncEngine:
    """Return the cached AsyncEngine for the given engine type, building it lazily.

    Reader and writer are cached separately so callers (e.g. RoutingSession)
    receive distinct engine instances. The reader uses
    ``app_settings.db.reader_uri`` when configured, else falls back to the
    writer URI.
    """
    db = app_settings.db
    if engine_type == SQLAlchemyEngineTypes.READER:
        return _build_engine(db.reader_uri or db.database_uri)
    return _build_engine(db.database_uri)
