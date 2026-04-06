# System Design & Concurrency

## Async-First Architecture

- ALL I/O-bound operations MUST use `async/await`
- Use `asyncpg` driver for PostgreSQL (configured in engine)
- Use `httpx.AsyncClient` for external HTTP calls — NEVER `requests`
- Use `aiofiles` for file I/O if needed

```python
# Async HTTP client
async with httpx.AsyncClient() as client:
    response = await client.get("https://api.example.com/data")

# NEVER use sync libraries in async context
import requests  # FORBIDDEN in async code
```

## Messaging (Redis Streams / SQS / RabbitMQ)

- Design **Idempotent Consumers** — prevent duplicate processing
- Always configure **Dead Letter Queue (DLQ)** for failed messages
- Use unique `message_id` for deduplication
- Handle poison messages gracefully with retry limits

## Redis / Caching

- **Cache-Aside Pattern:** check cache → miss → load DB → put cache
- **All keys MUST have TTL** — no infinite cache
- Configurable TTL per entity type via environment variables
- Use structured key patterns: `{module}:{entity}:{id}` (e.g., `user:profile:123`)

## Background Tasks

- Use FastAPI `BackgroundTasks` for simple fire-and-forget operations
- Use **Celery** or **ARQ** for distributed/scheduled tasks
- Use distributed locks (Redis-based) for multi-instance scheduled jobs
- Prevent duplicate job execution across cluster

```python
# Simple background task
from fastapi import BackgroundTasks

@router.post("/users")
async def create_user(data: CreateUserRequest, background_tasks: BackgroundTasks):
    user = await service.create_user(session, data=data)
    background_tasks.add_task(send_welcome_email, user.email)
    return APIResponse(...)

# For heavier jobs, use Celery/ARQ workers
```

## Concurrency Patterns

```python
# Parallel async operations with asyncio.gather
results = await asyncio.gather(
    fetch_user_profile(user_id),
    fetch_user_orders(user_id),
    fetch_user_notifications(user_id),
)

# Use asyncio.TaskGroup (Python 3.11+) for structured concurrency
async with asyncio.TaskGroup() as tg:
    task1 = tg.create_task(fetch_data_a())
    task2 = tg.create_task(fetch_data_b())

# NEVER use threading for I/O-bound work — use async
# Use ProcessPoolExecutor only for CPU-bound tasks
```

## Concurrency Checklist

- [ ] Race conditions checked in "find-or-create" flows (use `get_or_upsert` with `with_for_update`)
- [ ] Idempotency: repeated requests = no duplicate side effects
- [ ] Long-running ops: batch writes, not per-item
- [ ] External input: validate/sanitize (Pydantic handles this)
- [ ] List endpoints: paginated via `LimitOffsetPaginationFilter` or cursor pagination
- [ ] Timeouts configured for external service calls
