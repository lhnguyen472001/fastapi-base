# FastAPI Base Project

## Commands

```bash
uv run uvicorn main:app --reload       # Start dev server (port 8000)
uv run pytest                          # Run tests
uv run ruff check .                    # Lint
uv run ruff format .                   # Format
uv run alembic upgrade head            # Run migrations
```

## Architecture

- **Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, pydantic-settings
- **DB Driver:** asyncpg (PostgreSQL)
- **Layered Architecture:** Router → Service → Repository → Model
- **ORM:** SQLAlchemy 2.x declarative with async sessions, read/write split via `RoutingSession`
- **DI:** `dependency-injector` — `@inject` + `Depends(Provide[Container.service])` in routes
- **Auth:** bcrypt + PyJWT (declared, not yet wired)
- **Logging:** loguru with OpenTelemetry trace/span ID injection
- **Observability:** OpenTelemetry (FastAPI, SQLAlchemy, Redis instrumentation)

## Project Structure

```
apps/
├── settings.py                            # ApplicationSettings + DatabaseSettings (pydantic-settings)
├── containers.py                          # CoreContainer (engine, session singletons)
├── core/
│   ├── logging.py                         # loguru + OTel trace formatter, InterceptHandler
│   ├── database/
│   │   ├── engine.py                      # Async engine factory (reader/writer split)
│   │   ├── session.py                     # RoutingSession + async_scoped_session + session_factory
│   │   ├── registry.py                    # ORM registry + MetadataRegistry
│   │   ├── types.py                       # Type aliases (SQLAlchemyModelT, etc.)
│   │   ├── utils.py                       # get_instrumented_attr, model_from_dict, slugify
│   │   ├── filters.py                     # StatementFilter ABC + concrete filters
│   │   ├── transactional.py               # @transactional decorator (auto begin/commit/rollback)
│   │   ├── model/
│   │   │   ├── base.py                    # Declarative bases: UUIDBase, UUIDAuditBase, BigIntBase, etc.
│   │   │   └── mixins/                    # UUID PK, BigInt PK, timestamps, soft delete, slug, sentinel
│   │   └── repository/
│   │       ├── protocol.py                # ReaderProtocol / WriterProtocol / UpsertableProtocol / SQLAlchemyRepositoryProtocol
│   │       ├── base.py                    # BaseSQLAlchemyRepository — generic CRUD entrypoint
│   │       ├── _query_builder.py          # QueryBuilder — apply filters / order / kwargs to a Select
│   │       ├── _statements.py             # Pure statement-shape helpers (soft-delete filter, count projection, dialect)
│   │       └── _result_processor.py       # execute_statement, collect_rows, collect_rows_with_window_count
│   ├── schemas/
│   │   ├── base.py                        # BaseObjectSchema (Pydantic v2, from_attributes=True)
│   │   ├── request.py                     # RequestObjectSchema, OffsetPaginationRequestSchema, OrderByRequestSchema
│   │   └── response.py                    # APIResponse[T], PaginatedResponse[T], ResponseCodes, JsonResponseStatuses
│   ├── services/
│   │   ├── protocol.py                    # BaseServiceProtocol
│   │   ├── base.py                        # SQLAlchemyReadService, SQLAlchemyWriteService, SQLAlchemyService
│   │   └── utils.py                       # ResultConverter (ORM → schema)
│   ├── exceptions/
│   │   ├── base.py                        # BackendError (code + status_code + message)
│   │   ├── errors.py                      # NotFoundError, ConflictError, etc.
│   │   └── handlers.py                    # backend_exception_handler, validation_exception_handler
│   └── middlewares/
│       └── sqlalchemy.py                  # SQLAlchemySessionMiddleware (session-per-request)
├── user/                                  # Example domain module
│   ├── models.py                          # User(UUIDAuditBase) — ORM model
│   ├── repositories.py                    # UserRepository(BaseSQLAlchemyRepository) + Protocol
│   ├── services.py                        # UserService(SQLAlchemyService)
│   ├── routes.py                          # APIRouter + @inject + Depends(Provide[UserContainer...])
│   ├── schemas.py                         # CreateUserRequest, UpdateUserRequest, UserResponse
│   ├── exceptions.py                      # UserErrorCodes(StrEnum), UserNotFoundError, etc.
│   └── containers.py                      # UserContainer(DeclarativeContainer) — wires repo→service
└── auth/
    └── models.py                          # RefreshToken(UUIDAuditBase) — FK to users
```

## DI Pattern (dependency-injector)

Every route MUST use `@inject` decorator with `Depends(Provide[Container.service])`:

```python
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

@router.get("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    ...
```

Each module defines a `containers.py`:

```python
from dependency_injector import containers, providers

class UserContainer(containers.DeclarativeContainer):
    user_repository = providers.Factory(UserRepository)
    user_service = providers.Factory(UserService, repository=user_repository)
```

## Conventions

- All code, comments, and variables MUST be in English
- Use Google-style docstrings for all public functions
- Type hints required for all parameters and return values
- Import order: stdlib → third-party → local (`apps.*`)
- Settings from environment via pydantic-settings, never hardcoded
- Use `loguru`, never `print` for application output
- Async-first: use `async/await` for all I/O-bound operations
- Repository pattern for all database access
- Early return pattern — avoid deep nesting

## Important

- **RBAC / Casbin & multi-worker:** the Casbin enforcer is per-worker in-memory. Running with `uvicorn --workers >1` will cause stale-cache reads after policy mutations until each worker reloads. Stay on `--workers 1` until a Casbin watcher (e.g. Redis pub/sub) is wired in. See `apps/rbac/enforcer.py` warning.
- **Post-version retention sweeper:** the FastAPI lifespan starts a background `post_version_sweeper` task alongside the autosave sweeper. Both use leader-elected Redis locks (distinct keys), so any worker count is safe; with Redis off the sweeper exits cleanly and retention is not enforced. Tunables live in `apps/blog/constants.py` (`POST_VERSION_RETENTION_LIMIT`, `POST_VERSION_SWEEP_INTERVAL`, etc.). See `apps/blog/sweeper.py:post_version_sweeper`.
- **Comment-moderation retention sweeper:** the FastAPI lifespan starts a background `comment_moderation_sweeper` task that hard-deletes anonymous `pending` comments older than `POST_COMMENT_MODERATION_PENDING_TTL_SECONDS` (FR-010e). Leader-elected via its own distinct Redis key (`blog:comment_moderation:sweeper:leader`), so any worker count is safe; with Redis off the sweeper exits cleanly and queue retention is best-effort. Counter-neutral by design — `pending` rows never contributed to `posts.comment_count`. Tunables live in `apps/blog/constants.py` (`POST_COMMENT_MODERATION_PENDING_TTL_SECONDS`, `POST_COMMENT_MODERATION_SWEEP_INTERVAL`, etc.). See `apps/blog/sweeper.py:comment_moderation_sweeper`.
- **Imports:** Use `apps.*` prefix for all local imports (e.g., `from apps.core.database.engine import ...`)
- **Sessions:** Use `Depends(session_factory)` in routes — auto read/write split via `RoutingSession`
- **No session ops in services:** Services MUST NOT call `session.add` / `session.flush` / `session.refresh` / `session.delete` / `session.execute` / `session.merge` (or any other `session.*` method) directly. The only thing a service may do with the session is pass it as the first argument to a repository method. Persistence patterns map as follows:
  - Insert new row: `await repo.add(session, instance, expunge=False)` (returns the persisted instance)
  - Mutate-then-persist: build a `dict` of changed fields and call `await repo.update(session, item_id=instance.id, data={...})` — never `setattr(instance, ...) + session.flush()`
  - Delete a loaded instance: `await repo.delete(session, item_id=instance.id)` — never `await session.delete(instance)`
  - Bulk delete by predicate: `await repo.delete_where(session, Model.col == value)`
  - Bulk insert: `await repo.add_many(session, [{...}, {...}])`
  - Eager-load relationships after a write: re-fetch via `repo.find_by_id(...)` (or any read method on the repo); never call `session.refresh(instance, attribute_names=[...])` from a service
  - If a service mutates fields on a loaded model from another aggregate, inject that aggregate's repository (e.g. `user_repository: UserRepository`) and call its `update(item_id, data=dict)`. Do not reach for the session as a shortcut.

  Raw SQL / `session.execute(select(...))` and similar query construction belongs inside repository methods only — never in services.
- **DI:** Use `@inject` + `Depends(Provide[Container.service])` — never manually instantiate services in routes
- **Transactions:** Use `@Transactional()` decorator in services for multi-statement writes
- **Filters:** Use `StatementFilter` subclasses for composable query filtering
- **Exceptions:** Subclass `BackendError` with module-specific `StrEnum` error codes
- **Schemas:** Never return ORM models directly from API endpoints — use Pydantic schemas
- **Responses:** Wrap all API responses in `APIResponse[T]` with `ResponseCodes` and `JsonResponseStatuses`
- **Constants:** Module-level literal constants (URLs, TTLs, timeouts, cookie names, key prefixes, bcrypt cost factors, etc.) MUST live in a per-module `constants.py` (e.g. `apps/auth/constants.py`, `apps/rbac/constants.py`) and be typed with `typing.Final[T]`. NEVER define constants inline in service / route / repository / model / DI-container files — even if only used within that module. Importers should `from apps.<module>.constants import NAME`. This keeps all tunables in one greppable place per module and makes test overrides trivial.
- All rules in `.claude/rules/` apply to every coding task

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan: [specs/003-post-likes-comments/plan.md](specs/003-post-likes-comments/plan.md)
<!-- SPECKIT END -->
