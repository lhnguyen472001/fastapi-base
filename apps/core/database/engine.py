"""Lazy SQLAlchemy async engine factory.

Engines are NOT instantiated at import time — `engine_factory()` builds them
on first call and caches via `lru_cache`. This makes the module safe to import
in test environments that swap out settings or run without a database.
"""

import enum
import functools

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from apps.settings import app_settings


class SQLAlchemyEngineTypes(enum.StrEnum):
    """SQLAlchemy engine types."""

    READER = "reader"
    WRITER = "writer"


def _build_engine() -> AsyncEngine:
    """Construct an AsyncEngine from current application settings."""
    db = app_settings.db
    return create_async_engine(
        db.database_uri,
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
    receive distinct engine instances even if their connection URLs are
    identical today; this leaves room for true read/write splitting later.
    """
    _ = engine_type  # cache key only — used by lru_cache to distinguish reader vs writer
    return _build_engine()
