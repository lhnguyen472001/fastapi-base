---
description: Layered architecture rules for FastAPI Base — Router → Service → Repository → Model. Apply to ALL coding tasks.
---

# Layered Architecture (4-Layer)

## Layer Structure

```
Router (Presentation) → Service (Application) → Repository (Data Access) → Model (Domain)
```

Dependencies **ONLY flow downward**. NEVER import from layers above.

## Router Layer (`apps/{module}/routes.py`)

- Routers inject **Services** via DI container using `@inject` + `Depends(Provide[...])`, never Repositories directly
- Return **Pydantic response schemas** — NEVER ORM models
- MUST use `@inject` decorator from `dependency_injector.wiring` on every route function
- Service dependencies resolved via `Depends(Provide[{Module}Container.{service}])`
- Session via `Depends(session_factory)`
- Use Pydantic schemas with validation for request bodies

```python
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.session import session_factory
from apps.core.schemas.response import APIResponse, JsonResponseStatuses, ResponseCodes
from apps.user.containers import UserContainer
from apps.user.schemas import UserResponse, CreateUserRequest
from apps.user.services import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=APIResponse[UserResponse], status_code=201)
@inject
async def create_user(
        data: CreateUserRequest,
        session: AsyncSession = Depends(session_factory),
        user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    user = await user_service.create(session, data=data)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User created successfully.",
    )
```

## Service Layer (`apps/{module}/services.py`)

- Services use Repository interfaces for data access
- NEVER import Router layer or directly use SQLAlchemy sessions for queries
- Business logic and orchestration lives here
- Use `@Transactional` decorator for write operations

```python
from apps.core.services.base import SQLAlchemyService
from apps.user.models import User

class UserService(SQLAlchemyService[User]):
    """User business logic."""

    async def create(self, session, *, data):
        return await self.repository.add(session, data=data.model_dump())
```

## Repository Layer (`apps/{module}/repositories.py`)

- Extends `BaseSQLAlchemyRepository` with model-specific queries
- NEVER contain business logic — only data access
- Use `StatementFilter` subclasses for composable query filtering

```python
from apps.core.database.repository.base import BaseSQLAlchemyRepository
from apps.user.models import User


class UserRepository(BaseSQLAlchemyRepository[User]):
    """User data access."""
    model_type = User
```

## Model Layer (`apps/{module}/models.py`)

- SQLAlchemy 2.x declarative models with `Mapped` type annotations
- Inherit from project bases: `UUIDBase`, `UUIDAuditBase`, `BigIntBase`, `BigIntAuditBase`
- Models define table structure and relationships only
- NEVER contain business logic beyond simple computed properties

```python
from sqlalchemy.orm import Mapped, mapped_column
from apps.core.database.model.base import UUIDAuditBase


class User(UUIDAuditBase):
    """User model."""
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
```

## Data Flow

```
HTTP Request → Router(validate via Pydantic) → Service(business logic)
→ Repository(SQLAlchemy query) → DB → reverse path → Pydantic Response
```

## DI Container (`apps/{module}/containers.py`)

Each module declares a `DeclarativeContainer` that wires Repository -> Service:

```python
from dependency_injector import containers, providers

from apps.user.repositories import UserRepository
from apps.user.services import UserService

class UserContainer(containers.DeclarativeContainer):
    """Dependency injection container for the User module."""

    user_repository = providers.Factory(UserRepository)
    user_service = providers.Factory(UserService, repository=user_repository)
```

**Rules:**

- `providers.Factory` for stateless services/repositories (new instance per request)
- `providers.Singleton` for shared infrastructure (engines, session factories)
- Container wires Repository into Service constructor automatically
- Routes resolve services via `Depends(Provide[Container.service])`

## Module Structure

Each domain module follows this structure:

```
apps/{module}/
├── __init__.py
├── models.py          # SQLAlchemy ORM models
├── repositories.py    # Repository classes
├── services.py        # Business logic services
├── routes.py          # FastAPI router endpoints (@inject + Depends(Provide[...]))
├── schemas.py         # Pydantic request/response schemas
├── exceptions.py      # Module-specific exceptions
└── containers.py      # DI container (dependency-injector)
```
