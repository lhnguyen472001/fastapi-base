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
from fastapi.responses import ORJSONResponse, RedirectResponse
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from apps.auth.containers import AuthContainer
from apps.auth.routes import auth_router
from apps.core.database.session import async_session_factory
from apps.core.exceptions.base import BackendError
from apps.core.exceptions.handlers import (
    backend_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from apps.core.middlewares.sqlalchemy import SQLAlchemySessionMiddleware
from apps.core.rate_limit import limiter, rate_limit_exceeded_handler
from apps.core.redis import close_redis_client
from apps.health.routes import health_router
from apps.product.routes import product_category_router, product_router
from apps.rbac.enforcer import enforcer_factory
from apps.rbac.routes import rbac_router
from apps.rbac.seeders import sync_registered_resources
from apps.settings import app_settings
from apps.user.routes import user_router

from .containers import AppContainer

API_V1_PREFIX = "/api/v1"


def verify_rbac_multi_worker_safety() -> None:
    """Refuse to boot when multi-worker is configured without a Casbin watcher."""
    if app_settings.workers > 1 and not app_settings.rbac.watcher_redis_url:
        msg = (
            f"WORKERS={app_settings.workers} requires RBAC_WATCHER_REDIS_URL "
            "to keep the Casbin enforcer consistent across processes. "
            "Either set RBAC_WATCHER_REDIS_URL=redis://<host>:<port>/<db> "
            "or run with WORKERS=1."
        )
        raise RuntimeError(msg)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down async DI resources.

    The Casbin enforcer is an async ``providers.Resource`` and must be
    explicitly initialized before any route can resolve it. We do that here
    so a missing database connection causes the app to fail-fast at startup.
    """
    verify_rbac_multi_worker_safety()
    logger.info("factory - lifespan - Initializing RBAC resources")

    if app_settings.rbac.auto_seed_resources_from_registry:
        enforcer = await enforcer_factory()
        async with async_session_factory() as seed_session, seed_session.begin():
            await sync_registered_resources(
                seed_session,
                enforcer,
                admin_role_name=app_settings.rbac.system_admin_role_name,
            )

    logger.info("factory - lifespan - Application started")
    try:
        yield
    finally:
        logger.info("factory - lifespan - Shutting down")
        await AuthContainer.google_oauth_client().aclose()
        await close_redis_client()


def application_factory() -> FastAPI:
    """Build and return a configured FastAPI application."""
    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    container = AppContainer()
    container.init_resources()
    container.wire(modules=[__name__])

    # Rate limiting ---------------------------------------------------------
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

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
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
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


app = application_factory()
