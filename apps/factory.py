"""FastAPI application factory.

Builds a fully wired :class:`fastapi.FastAPI` instance: lifespan management
for the RBAC enforcer resource, exception handlers, middleware, and all
domain routers under the ``/api/v1`` prefix.

The module-level :data:`app` is what ``uvicorn`` imports.
"""

from collections.abc import AsyncIterator

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from loguru import logger

from apps.auth.routes import router as auth_router
from apps.core.exceptions.base import BackendError
from apps.core.exceptions.handlers import (
    backend_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from apps.core.middlewares.sqlalchemy import SQLAlchemySessionMiddleware
from apps.health.routes import router as health_router
from apps.product.containers import product_container  # noqa: F401
from apps.product.routes import category_router as product_category_router, router as product_router
from apps.rbac.containers import rbac_container
from apps.rbac.routes import router as rbac_router
from apps.settings import app_settings
from apps.user.routes import router as user_router



API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down async DI resources.

    The Casbin enforcer is an async ``providers.Resource`` and must be
    explicitly initialized before any route can resolve it. We do that here
    so a missing database connection causes the app to fail-fast at startup.
    """
    logger.info("factory - lifespan - Initializing RBAC resources")
    await rbac_container.init_resources()  # type: ignore[func-returns-value]
    logger.info("factory - lifespan - Application started")
    try:
        yield
    finally:
        logger.info("factory - lifespan - Shutting down")
        await rbac_container.shutdown_resources()  # type: ignore[func-returns-value]


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    # Middleware ------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SQLAlchemySessionMiddleware)

    # Exception handlers ----------------------------------------------------
    app.add_exception_handler(BackendError, backend_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    # Routers ---------------------------------------------------------------
    app.include_router(health_router)
    app.include_router(user_router, prefix=API_V1_PREFIX)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(rbac_router, prefix=API_V1_PREFIX)
    app.include_router(product_router, prefix=API_V1_PREFIX)
    app.include_router(product_category_router, prefix=API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    async def _() -> RedirectResponse:
        return RedirectResponse(url="/docs", status_code=307)

    return app


app = create_app()
