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
│   ├── database/sql/
│   │   ├── engine.py                      # Async engine factory (reader/writer split)
│   │   ├── session.py                     # RoutingSession + async_scoped_session + session_factory
│   │   ├── registry.py                    # ORM registry + MetadataRegistry
│   │   ├── types.py                       # Type aliases (SQLAlchemyModelT, etc.)
│   │   ├── utils.py                       # get_instrumented_attr, model_from_dict, slugify
│   │   ├── filters.py                     # StatementFilter ABC + concrete filters
│   │   ├── pagination.py                  # Offset + cursor pagination helpers
│   │   ├── transactional.py               # @Transactional decorator (auto begin/commit/rollback)
│   │   ├── model/
│   │   │   ├── base.py                    # Declarative bases: UUIDBase, UUIDAuditBase, BigIntBase, etc.
│   │   │   └── mixins/                    # UUID PK, BigInt PK, timestamps, soft delete, slug, sentinel
│   │   └── repository/
│   │       ├── protocol.py                # RepositoryProtocol (561 lines, full generic interface)
│   │       └── base.py                    # BaseSQLAlchemyRepository (1053 lines, generic CRUD)
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
- **Imports:** Use `apps.*` prefix for all local imports (e.g., `from apps.core.database.sql.engine import ...`)
- **Sessions:** Use `Depends(session_factory)` in routes — auto read/write split via `RoutingSession`
- **DI:** Use `@inject` + `Depends(Provide[Container.service])` — never manually instantiate services in routes
- **Transactions:** Use `@Transactional()` decorator in services for multi-statement writes
- **Filters:** Use `StatementFilter` subclasses for composable query filtering
- **Exceptions:** Subclass `BackendError` with module-specific `StrEnum` error codes
- **Schemas:** Never return ORM models directly from API endpoints — use Pydantic schemas
- **Responses:** Wrap all API responses in `APIResponse[T]` with `ResponseCodes` and `JsonResponseStatuses`
- **Constants:** Module-level literal constants (URLs, TTLs, timeouts, cookie names, key prefixes, bcrypt cost factors, etc.) MUST live in a per-module `constants.py` (e.g. `apps/auth/constants.py`, `apps/rbac/constants.py`) and be typed with `typing.Final[T]`. NEVER define constants inline in service / route / repository / model / DI-container files — even if only used within that module. Importers should `from apps.<module>.constants import NAME`. This keeps all tunables in one greppable place per module and makes test overrides trivial.
- All rules in `.claude/rules/` apply to every coding task
