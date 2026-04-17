import asyncio
from typing import ClassVar

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from apps.core.database.session import (
    reset_session_ctx,
    scoped_session,
    set_session_ctx,
)


class SQLAlchemySessionMiddleware(BaseHTTPMiddleware):
    """Middleware for SQLAlchemy sessions."""

    _exclude_paths: ClassVar[list[str]] = [
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        "/robots.txt",
        "/sitemap.xml",
        "/humans.txt",
        "/ads.txt",
        "/apple-touch-icon.png",
    ]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Dispatch the middleware."""
        if request.url.path in self._exclude_paths:
            return await call_next(request)

        set_session_ctx(session_id=id(asyncio.current_task()))

        try:
            return await call_next(request)
        except Exception as e:
            logger.error(f"Error in database session middleware: {e}")
            raise
        finally:
            try:
                await scoped_session.remove()
            except Exception as e:
                logger.error(f"Error removing scoped session: {e}")
            finally:
                reset_session_ctx()
