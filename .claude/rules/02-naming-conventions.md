---
description: Naming conventions for FastAPI Base — PEP 8, component naming, anti-patterns. Apply to ALL coding tasks.
---

# Naming Conventions

## Component Naming

| Component | Pattern | Example |
|---|---|---|
| Router module | `routes.py` | `apps/user/routes.py` |
| Router variable | `router` | `router = APIRouter(...)` |
| Service class | `{Entity}Service` | `UserService` |
| Repository class | `{Entity}Repository` | `UserRepository` |
| ORM Model | `{Entity}` (singular) | `User` |
| Table name | `{entity}s` (plural, auto) | `users` (via `CommonTableAttributes`) |
| Request schema | `{Action}{Entity}Request` | `CreateUserRequest` |
| Response schema | `{Entity}Response` | `UserResponse` |
| Exception class | `{Entity}{Error}Exception` | `UserNotFoundException` |
| Error codes enum | `{Entity}ErrorCodes` | `UserErrorCodes` |
| DI Container | `{Entity}Container` | `UserContainer` |
| Filter class | `{Description}Filter` | `SearchFilter`, `LimitOffsetFilter` |
| Mixin class | `{Feature}Mixin` | `HasTimestampMixin` |

## Python Naming Rules (PEP 8)

| Element | Convention | Good | Bad |
|---|---|---|---|
| Class | PascalCase | `OrderService` | `order_service` |
| Function/Method | snake_case | `calculate_price()` | `calculatePrice()` |
| Variable | snake_case | `user_count` | `userCount` |
| Constant | UPPER_SNAKE_CASE | `MAX_RETRY_LIMIT` | `maxRetry` |
| Module | snake_case | `user_service.py` | `UserService.py` |
| Package | lowercase | `apps/user/` | `apps/User/` |
| Private | `_` prefix | `_internal_method()` | `internalMethod()` |
| Boolean | `is_`, `has_`, `can_`, `should_` | `is_active` | `active` |
| Async function | `async def` prefix implicit | `async def get_user()` | `def get_user_async()` |
| Type alias | PascalCase with `T` suffix | `SQLAlchemyModelT` | `sql_model_type` |
| Protocol | PascalCase | `RepositoryProtocol` | `IRepository` |

## Import Conventions

```python
# 1. stdlib
import uuid
from typing import Any, Sequence

# 2. third-party
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Mapped, mapped_column

# 3. local (always use apps.* prefix)
from apps.core.database.model.base import UUIDAuditBase
from apps.core.schemas.response import APIResponse
from apps.user.models import User
```

## Anti-Patterns

- **No Redundancy:** `User.user_email` -> use `User.email`
- **No Abbreviations:** `usr_svc` -> use `user_service`
- **No Hungarian Notation:** `str_name` -> use `name`
- **No `I` prefix for Protocols:** `IRepository` -> use `RepositoryProtocol`
- ALL code, comments, variables MUST be in English
