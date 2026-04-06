# Decorators & Middleware (Cross-Cutting Concerns)

Use Python decorators and FastAPI middleware to separate cross-cutting concerns:
Logging, Performance, Audit, Request Context.

## Decorator Pattern (Python equivalent of Java AOP)

```python
import functools
import time
import logging

logger = logging.getLogger(__name__)

def track_action(action: str = ""):
    """Decorator for automatic logging and performance tracking."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            method_name = func.__qualname__
            logger.info("%s - %s - START - args: %s", method_name, action, kwargs)

            start = time.perf_counter()
            result = await func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000

            logger.info("%s - %s - END - elapsed: %.2fms", method_name, action, elapsed)
            return result
        return wrapper
    return decorator

# Usage — clean service, no manual logging
class OrderService:
    @track_action("Create Order")
    async def create_order(self, session: AsyncSession, *, data: CreateOrderRequest) -> OrderResponse:
        # Pure business logic — logging handled by decorator
        ...
```

## FastAPI Middleware

```python
# Session context middleware (already implemented)
class SQLAlchemySessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = id(asyncio.current_task())
        set_session_ctx(session_id)
        try:
            response = await call_next(request)
        finally:
            await scoped_session.remove()
            reset_session_ctx()
        return response
```

## FastAPI Dependencies as Cross-Cutting Concerns

```python
# Auth dependency
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(session_factory),
) -> User:
    payload = decode_jwt(token)
    user = await user_repo.find_by_id(session, user_id=payload["sub"])
    if user is None:
        raise HTTPException(status_code=401)
    return user

# Use as dependency in routes
@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    ...
```

## Exception Handlers (Global)

```python
# Registered in app startup
@app.exception_handler(BackendError)
async def backend_error_handler(request: Request, exc: BackendError):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )
```

## When to Use Decorators

- Performance tracking / method timing
- Audit logging (who did what, when)
- Input/output logging for debugging
- Retry logic for external service calls
- Cache results (`functools.lru_cache` for sync, custom for async)
- NEVER for core business logic
