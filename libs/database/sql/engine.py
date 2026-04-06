import enum
import functools
from typing import Final

from settings import app_settings
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class SQLAlchemyEngineTypes(enum.StrEnum):
    """SQLAlchemy engine types."""

    READER = "reader"
    WRITER = "writer"


engines: Final[dict[SQLAlchemyEngineTypes, AsyncEngine]] = {
    SQLAlchemyEngineTypes.READER: create_async_engine(
        app_settings.db.database_uri,
        pool_pre_ping=app_settings.db.pool_pre_ping,
        pool_recycle=app_settings.db.pool_recycle,
        pool_size=app_settings.db.pool_size,
        max_overflow=app_settings.db.max_overflow,
        pool_timeout=app_settings.db.pool_timeout,
    ),
    SQLAlchemyEngineTypes.WRITER: create_async_engine(
        app_settings.db.database_uri,
        pool_pre_ping=app_settings.db.pool_pre_ping,
        pool_recycle=app_settings.db.pool_recycle,
        pool_size=app_settings.db.pool_size,
        max_overflow=app_settings.db.max_overflow,
        pool_timeout=app_settings.db.pool_timeout,
    ),
}


@functools.lru_cache
def engine_factory(engine_type: SQLAlchemyEngineTypes = SQLAlchemyEngineTypes.READER) -> AsyncEngine:
    """Factory for creating SQLAlchemy engines."""
    return engines[engine_type]
