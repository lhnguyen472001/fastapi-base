---
description: Clean code rules for FastAPI Base — Python 3.13+, type hints, early return, function limits. Apply to ALL coding tasks.
---

# Python Clean Code

**Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x, Pydantic v2

## Type Hints — Always Required

```python
# All parameters and return values MUST have type hints
async def get_user_by_id(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> User | None:
    ...

# Use modern Python 3.10+ union syntax
name: str | None = None       # not Optional[str]
items: list[str] = []         # not List[str]
mapping: dict[str, Any] = {}  # not Dict[str, Any]
```

## Immutability — Prefer Pydantic Models and dataclasses

```python
# Pydantic schemas for request/response (immutable by default with frozen=True)
class CreateUserRequest(BaseObjectSchema):
    username: str
    email: str

# Use @dataclass(frozen=True) for internal value objects
from dataclasses import dataclass

@dataclass(frozen=True)
class PaginationParams:
    limit: int = 20
    offset: int = 0
```

## Dependency Injection — Constructor via `__init__`

```python
# Service receives repository via constructor
class UserService(SQLAlchemyService[User]):
    def __init__(self, repository: UserRepository) -> None:
        super().__init__(repository=repository)

# FastAPI DI via Depends()
@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
) -> APIResponse[UserResponse]:
    ...
```

## Early Return — Reduce Nesting

```python
# Early return pattern
async def find_active_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await repository.get_one_by_id(session, item_id=user_id)
    if user is None:
        raise UserNotFoundException(message=f"User {user_id} not found")
    if not user.is_active:
        raise UserInactiveException(message=f"User {user_id} is inactive")
    return user

# NEVER nest deeply
# if condition:
#     if another:
#         if yet_another:  # <- AVOID
```

## Keyword-Only Arguments for Optional Parameters

```python
# Use * to force keyword-only arguments after positional ones
async def list_users(
    session: AsyncSession,
    *,
    filters: list[StatementFilter] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[User], int]:
    ...
```

## Function & Class Limits

| Constraint | Target | Maximum |
|---|---|---|
| Function length | 15-30 lines | 50 lines |
| Parameters | <= 3 positional | >3 -> use schema/dataclass |
| Nesting depth | <= 2 levels | Extract functions |
| Class length | 150-400 lines | 500 lines |
| Module length | 200-600 lines | 800 lines |

**Refactoring triggers:**

- Function > 50 lines -> extract helper functions
- Function > 3 positional params -> create Pydantic schema or dataclass
- Nesting > 2 levels -> early returns / extract
- Class > 500 lines -> split into mixins or separate classes
- Module > 800 lines -> split into submodules

## Async-First

- Use `async/await` for ALL I/O-bound operations
- NEVER use synchronous DB calls in async context
- NEVER use `time.sleep()` — use `asyncio.sleep()`
- Use `asyncio.gather()` for concurrent independent I/O operations
