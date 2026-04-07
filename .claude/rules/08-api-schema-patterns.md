---
description: API and Pydantic schema patterns for FastAPI Base — request/response schemas, pagination, versioning. Apply to ALL API tasks.
---

# API & Schema Patterns

## API Path Conventions

| Context | Path Prefix | Auth Required |
|---|---|---|
| Public | `/api/v1/public/**` | No |
| Authenticated | `/api/v1/**` | Bearer JWT |
| Admin | `/api/v1/admin/**` | Bearer JWT + admin role |

## Schema Layering (Pydantic v2)

```
Request Schema (with validation)          → apps/{module}/schemas.py
     ↓ (validated by FastAPI)
Service Layer (business logic)            → apps/{module}/services.py
     ↓ (SQLAlchemy model)
ORM Model                                 → apps/{module}/models.py
     ↓ (to_dict or from_attributes)
Response Schema (serialization)           → apps/{module}/schemas.py
```

## Request Schemas — With Validation

```python
from pydantic import Field, field_validator
from apps.core.schemas.base import BaseObjectSchema

class CreateUserRequest(BaseObjectSchema):
    """Request schema for creating a user."""

    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    password: str = Field(..., min_length=8)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not v.isalnum():
            raise ValueError("Username must be alphanumeric")
        return v.lower()
```

## Response Schemas — Serialization Only

```python
import uuid
from datetime import datetime
from apps.core.schemas.response import ResponseObjectSchema

class UserResponse(ResponseObjectSchema):
    """Response schema for user data."""

    id: uuid.UUID
    username: str
    email: str
    is_active: bool
    created_at: datetime
    # NEVER include: hashed_password, internal fields
```

## Standard API Response Wrapper

```python
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.database.sql.session import session_factory
from apps.core.schemas.response import APIResponse, JsonResponseStatuses, PaginatedResponse, ResponseCodes
from apps.user.containers import UserContainer
from apps.user.schemas import UserResponse
from apps.user.services import UserService

# Single object response — @inject + Depends(Provide[...])
@router.get("/{user_id}", response_model=APIResponse[UserResponse])
@inject
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    user = await user_service.get_by_id(session, item_id=user_id)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User retrieved successfully.",
    )

# Paginated list response
@router.get("", response_model=APIResponse[PaginatedResponse[UserResponse]])
@inject
async def list_users(
    params: ListUsersRequest = Depends(),
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[PaginatedResponse[UserResponse]]:
    result = await user_service.list_items(session, filters=params)
    return APIResponse[PaginatedResponse[UserResponse]](
        code=ResponseCodes.API000,
        data=result,
        status=JsonResponseStatuses.SUCCESS,
        message="Users retrieved successfully.",
    )
```

## Pagination — Query Parameters

```python
from dependency_injector.wiring import Provide, inject
from apps.core.schemas.request import OffsetPaginationRequestSchema, OrderByRequestSchema

@router.get("")
@inject
async def list_users(
    pagination: OffsetPaginationRequestSchema = Depends(),
    ordering: OrderByRequestSchema = Depends(),
    session: AsyncSession = Depends(session_factory),
    user_service: UserService = Depends(Provide[UserContainer.user_service]),
):
    ...
```

## Schema Rules

- Request schemas: include validation (`Field`, `field_validator`)
- Response schemas: NO validation — serialization only
- NEVER expose internal fields (passwords, internal IDs) in response schemas
- Use `model_validate(obj, from_attributes=True)` to convert ORM models to schemas
- NEVER return ORM models directly from API endpoints
- Use `ConfigDict(from_attributes=True)` on all schemas (inherited from `BaseObjectSchema`)

## Alembic Migrations

- **Location:** `alembic/versions/`
- Run: `uv run alembic revision --autogenerate -m "description"`
- Apply: `uv run alembic upgrade head`
- NEVER edit migration files after they have been applied
- Include both `upgrade()` and `downgrade()` in every migration
