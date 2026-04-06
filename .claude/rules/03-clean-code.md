# Python Clean Code

**Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x, Pydantic v2

## Immutability — Prefer Frozen Schemas

```python
# Pydantic schemas are immutable by default
class CreateUserRequest(RequestObjectSchema):
    email: EmailStr = Field(..., description="User email address")
    username: str = Field(..., min_length=3, max_length=150)

# Use dataclasses for simple data containers
from dataclasses import dataclass

@dataclass(frozen=True)
class PaginationParams:
    limit: int = 20
    offset: int = 0
```

## Injection — Constructor Only

```python
# Constructor injection
class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

# DI Container (dependency-injector)
class UserContainer(DeclarativeContainer):
    user_repository = providers.Singleton(UserRepository)
    user_service = providers.Singleton(UserService, repository=user_repository)

# FastAPI dependency injection via Depends()
@router.get("/{user_id}")
@inject
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]: ...
```

## Early Return — Reduce Nesting

```python
# Early return
async def find_active_user(self, session: AsyncSession, *, user_id: uuid.UUID) -> User:
    user = await self.repository.find_by_id(session, user_id=user_id)
    if user is None:
        raise UserNotFoundError()

    if not user.is_active:
        raise UserInactiveError()

    return user

# NEVER nested if-else chains
```

## Type Hints — Required Everywhere

```python
# All parameters and return values MUST have type hints
async def create_user(
    self, session: AsyncSession, *, data: CreateUserRequest
) -> UserResponse:
    ...

# Use modern union syntax (Python 3.10+)
email: str | None = None          # not Optional[str]
items: list[str] = []             # not List[str]
mapping: dict[str, int] = {}     # not Dict[str, int]
```

## Keyword-Only Arguments

```python
# Use * to force keyword arguments for clarity
async def find_by_id(
    self, session: AsyncSession, *, user_id: uuid.UUID, include_deleted: bool = False
) -> User | None: ...

# Called as: await repo.find_by_id(session, user_id=uid)
# NOT: await repo.find_by_id(session, uid)
```

## Function & Class Limits

| Constraint | Target | Maximum |
|---|---|---|
| Function length | 20–35 lines | 50 lines |
| Parameters | ≤ 3 | >3 → use schema/dataclass |
| Nesting depth | ≤ 2 levels | Extract to helper methods |
| Class length | 200–400 lines | 500 lines |
| Module length | 300–500 lines | 600 lines |

**Refactoring triggers:**
- Function > 50 lines → extract helper methods
- Function > 3 params → create a Pydantic schema or dataclass
- Nesting > 2 levels → early returns / extract to methods
- Class > 500 lines → split into multiple classes/modules
- Module > 600 lines → split into sub-package
