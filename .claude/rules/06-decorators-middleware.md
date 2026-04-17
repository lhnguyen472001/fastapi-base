---
description: Decorator and middleware patterns for FastAPI Base — Python equivalents of AOP for cross-cutting concerns. Apply to ALL tasks involving decorators or middleware.
---

# Decorators & Middleware (Cross-Cutting Concerns)

Use decorators and middleware to separate cross-cutting concerns: Logging, Transactions, Performance, Auth.

## @Transactional Decorator Pattern

```python
from apps.core.database.transactional import Transactional


class OrderService(SQLAlchemyService[Order]):
    @Transactional()
    async def create_order(self, session, *, data):
        # Transaction handled by decorator — auto-commit on success, rollback on error
        order = await self.repository.add(session, data=data)
        await self.inventory_service.reserve(session, order_id=order.id)
        return order
```

## Performance Tracking Decorator

```python
import functools
import time
from loguru import logger

def track_action(action_name: str = ""):
    """Decorator that logs method entry/exit with timing."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            method = f"{func.__qualname__}"
            logger.info(f"TrackAction - {method} - START - {action_name}")
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.info(f"TrackAction - {method} - END - elapsed: {elapsed:.2f}ms")
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(f"TrackAction - {method} - ERROR after {elapsed:.2f}ms: {e}")
                raise
        return wrapper
    return decorator

# Usage
class OrderService:
    @track_action("Create Order")
    @Transactional()
    async def create_order(self, session, *, data):
        # Pure business logic — logging handled by decorator
        ...
```

## FastAPI Middleware

```python
from starlette.middleware.base import BaseHTTPMiddleware

# SQLAlchemy session middleware (already implemented)
# Sets session context per request, auto-cleanup on response
class SQLAlchemySessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        set_session_ctx(session_id=id(asyncio.current_task()))
        try:
            return await call_next(request)
        finally:
            await scoped_session.remove()
            reset_session_ctx()
```

## FastAPI Dependencies as Middleware

```python
from dependency_injector.wiring import Provide, inject
from fastapi import Depends, Security

# Use Depends() for request-scoped cross-cutting concerns
async def get_current_user(
    token: str = Security(oauth2_scheme),
    session: AsyncSession = Depends(session_factory),
) -> User:
    payload = decode_jwt(token)
    user = await user_service.get_by_id(session, item_id=payload["sub"])
    if user is None:
        raise AuthenticationError(message="Invalid token")
    return user

# Apply to routes — always use @inject with DI container
@router.get("/me")
@inject
async def get_profile(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
):
    ...
```

## When to Use Each Pattern

| Pattern | Use For | Example |
|---|---|---|
| `@inject` + `Provide[]` | DI container resolution in routes | `Depends(Provide[UserContainer.user_service])` |
| Decorator | Method-level concerns (logging, timing, caching) | `@track_action`, `@Transactional` |
| Middleware | Request-level concerns (session, CORS, auth) | `SQLAlchemySessionMiddleware` |
| `Depends()` | Route-level DI (auth, pagination, filters) | `get_current_user`, `session_factory` |
| Exception Handler | Global error handling | `backend_exception_handler` |

## Rules

- ALWAYS use `@inject` on route functions that use `Depends(Provide[...])`
- `@inject` goes AFTER `@router.get/post/...` (decorator order matters)
- Decorators for method-level cross-cutting (timing, audit, retry)
- Middleware for request/response lifecycle (sessions, logging, CORS)
- `Depends()` for route-specific DI and validation
- NEVER put business logic in decorators or middleware
- Stack decorators from outermost to innermost (top = outermost)
