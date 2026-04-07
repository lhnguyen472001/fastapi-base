---
description: System design and concurrency rules for FastAPI Base — async patterns, caching, background tasks. Apply to ALL system design tasks.
---

# System Design & Concurrency

## Async-First Architecture

- ALL I/O-bound operations MUST be `async`
- Use `asyncio.gather()` for concurrent independent I/O calls
- Use `asyncio.TaskGroup` (Python 3.11+) for structured concurrency
- NEVER use blocking calls (`requests`, `time.sleep`) in async context

```python
# Concurrent independent I/O operations
async def get_dashboard_data(session: AsyncSession, user_id: uuid.UUID):
    user, orders, notifications = await asyncio.gather(
        user_service.get_by_id(session, item_id=user_id),
        order_service.list_by_user(session, user_id=user_id),
        notification_service.get_unread(session, user_id=user_id),
    )
    return DashboardResponse(user=user, orders=orders, notifications=notifications)
```

## Messaging (Redis Streams / Celery / Background Tasks)

- Design **Idempotent Consumers** — prevent duplicate processing
- Use unique `message_id` for deduplication
- Configure **Dead Letter Queue (DLQ)** for failed messages
- For simple async tasks, use FastAPI `BackgroundTasks`

```python
from fastapi import BackgroundTasks

@router.post("/users")
async def create_user(
    request: CreateUserRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(session_factory),
):
    user = await user_service.create(session, data=request)
    background_tasks.add_task(send_welcome_email, user.email)
    return APIResponse(code="API000", data=user, message="User created")
```

## Redis / Caching

- **Cache-Aside Pattern:** check cache -> miss -> load DB -> put cache
- **All keys MUST have TTL** — no infinite cache
- Configurable TTL per entity type via environment variables
- Use `orjson` for fast serialization/deserialization of cached data

## Background Jobs

- Use distributed lock (Redis-based) for multi-instance scheduled jobs
- Prevent duplicate job execution across cluster
- Log job start/end with elapsed time

## Concurrency Checklist

- [ ] Race conditions checked in "find-or-create" flows
- [ ] Idempotency: repeated requests produce no duplicate side effects
- [ ] Long-running ops: batch writes, not per-item
- [ ] External input: validate and handle bad input (no unhandled exceptions)
- [ ] List endpoints: paginated or explicitly bounded
- [ ] Connection pools properly sized for expected load
- [ ] Graceful shutdown: pending requests complete before exit

## Error Handling Strategy

```python
# Module-specific exceptions inherit from BackendError
class UserNotFoundException(BackendError):
    code = UserErrorCodes.USER001
    status_code = 404

# Raised in service layer, caught by global exception handler
async def get_user(session, user_id):
    user = await repository.get_one_by_id(session, item_id=user_id)
    if user is None:
        raise UserNotFoundException(message=f"User {user_id} not found")
    return user
```

## Observability

- Use OpenTelemetry for distributed tracing (already configured)
- Instrument FastAPI, SQLAlchemy, and Redis
- Structured logging via `loguru`
- Trace propagation across service boundaries
