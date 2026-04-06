# FastAPI Base Project

## Commands

```bash
uv run uvicorn main:app --reload # Start dev server (port 8000)
uv run pytest                    # Run tests
uv run ruff check .              # Lint
uv run ruff format .             # Format
uv run alembic upgrade head      # Run migrations
```

## Architecture

- **Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, pydantic-settings
- **DB Driver:** asyncpg (PostgreSQL)
- **Layered Architecture:** Router → Service → Repository → Model
- **ORM:** SQLAlchemy 2.x declarative with async sessions, read/write split routing
- **DI:** dependency-injector (`DeclarativeContainer` + `Provide[]`)
- **Auth:** bcrypt + PyJWT (declared, not yet wired)

## Project Structure

```
apps/
├── settings.py                   # ApplicationSettings + DatabaseSettings (pydantic-settings)
├── containers.py                 # CoreContainer (engine, session DI singletons)
├── auth/
│   └── models.py                 # Auth models
├── user/                         # Example module
│   ├── containers.py             # UserContainer (DI wiring)
│   ├── exceptions.py             # UserNotFoundError, UserAlreadyExistsError
│   ├── models.py                 # User ORM model
│   ├── repositories.py           # UserRepository + Protocol
│   ├── routes.py                 # FastAPI router (/users)
│   ├── schemas.py                # Pydantic request/response schemas
│   └── services.py               # UserService (business logic)
libs/
├── logging.py                    # Logging configuration
├── database/sql/
│   ├── engine.py                 # Async engine (reader/writer split)
│   ├── session.py                # RoutingSession + async_scoped_session
│   ├── registry.py               # ORM registry + MetadataRegistry
│   ├── types.py                  # Type aliases (SQLAlchemyModelT, etc.)
│   ├── utils.py                  # get_instrumented_attr, model_from_dict, slugify
│   ├── filters.py                # StatementFilter ABC + concrete filters
│   ├── pagination.py             # Offset + cursor pagination helpers
│   ├── model/
│   │   ├── base.py               # Declarative bases: UUIDBase, BigIntBase, etc.
│   │   └── mixins/               # UUID PK, BigInt PK, timestamps, soft delete, slug
│   └── repository/
│       ├── base.py               # BaseSQLAlchemyRepository (generic CRUD)
│       └── protocol.py           # Repository protocol
├── schemas/
│   ├── base.py                   # BaseObjectSchema (Pydantic v2)
│   ├── request.py                # OffsetPaginationRequestSchema, OrderByRequestSchema
│   └── response.py               # APIResponse, PaginatedResponse, ResponseObjectSchema
├── exceptions/
│   ├── base.py                   # BackendError base class
│   ├── errors.py                 # Common error definitions
│   └── handlers.py               # FastAPI exception handlers
├── middlewares/
│   └── sqlalchemy.py             # SQLAlchemy session context middleware
└── services/
    ├── protocol.py               # Service protocol
    └── utils.py                  # Service helpers
```

## Coding Rules

All rules in `.claude/rules/` apply to every coding task:

| File | Scope |
|---|---|
| `01-layered-architecture.md` | Router → Service → Repository → Model, dependency direction |
| `02-naming-conventions.md` | Component naming, PEP 8 naming, anti-patterns |
| `03-clean-code.md` | Pydantic schemas, DI, early return, type hints, size limits |
| `04-database-persistence.md` | N+1, locking, transactions, SQLAlchemy 2.x patterns |
| `05-system-design.md` | Async patterns, caching, background tasks, concurrency |
| `06-decorators-middleware.md` | Decorators for cross-cutting, FastAPI middleware/dependencies |
| `07-code-quality.md` | Logging, error handling, config, comments, language |
| `08-api-schema-patterns.md` | FastAPI routing, Pydantic schema tiers, Alembic migrations |
| `vibe-coding.md` | Master workflow: plan → confirm → implement |
| `review-code.md` | Code review checklist against all rules |
| `build-prompt.md` | Structured prompt building workflow |

## Conventions

- All code, comments, and variables MUST be in English
- Use Google-style docstrings for all public functions
- Type hints required for all parameters and return values
- Import order: stdlib → third-party → local (`apps.*`, `libs.*`)
- Settings from environment via pydantic-settings, never hardcoded
- Use `logging` module, never `print` for application output
- Async-first: use `async/await` for all I/O-bound operations
- Repository pattern for all database access

## Important

- **Imports:** Use `apps.*` for app modules, `libs.*` for shared code
- **Sessions:** Use `session_factory()` async generator as FastAPI dependency
- **Filters:** Use `StatementFilter` subclasses for composable query filtering
- **Models:** Never return ORM models directly from API endpoints — use Pydantic schemas
- **Workflow:** Follow plan → confirm → implement (see `.claude/rules/vibe-coding.md`)
