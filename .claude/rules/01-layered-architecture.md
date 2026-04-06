# Layered Architecture

## Layer Structure

```
Router (routes.py) → Service → Repository → Model
```

Dependencies **ONLY flow downward**. NEVER import from layers above.

## Router Layer (`apps/{module}/routes.py`)

- Route functions inject **Services** via `dependency-injector` (`Provide[Container.service]`)
- Return **Pydantic response schemas** wrapped in `APIResponse` — NEVER ORM models
- Use `Depends(session_factory)` for database sessions
- Validation happens via Pydantic request schemas automatically

```python
@router.post("", response_model=APIResponse[UserResponse], status_code=201)
@inject
async def create_user(
    data: CreateUserRequest,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    user = await service.create_user(session, data=data)
    return APIResponse[UserResponse](
        code=ResponseCodes.API000,
        data=user,
        status=JsonResponseStatuses.SUCCESS,
        message="User created successfully.",
    )
```

## Service Layer (`apps/{module}/services.py`)

- Business logic lives here
- Receives `AsyncSession` from router, passes to repository
- Converts between request schemas and ORM models
- Returns **Pydantic response schemas** — NEVER ORM models
- NEVER import from routes or direct SQLAlchemy queries

```python
class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    async def create_user(
        self, session: AsyncSession, *, data: CreateUserRequest
    ) -> UserResponse:
        existing = await self.repository.find_by_email_or_username(
            session, email=data.email, username=data.username
        )
        if existing is not None:
            raise UserAlreadyExistsError(message="...")

        user = User(email=data.email, username=data.username, ...)
        user = await self.repository.create(session, user=user)
        return UserResponse.model_validate(user)
```

## Repository Layer (`apps/{module}/repositories.py`)

- Extends `BaseSQLAlchemyRepository[ModelT]`
- Define a `Protocol` class for the interface
- All database queries happen here — NEVER in services
- Returns ORM model instances

```python
class UserRepositoryProtocol(Protocol):
    async def find_by_id(self, session: AsyncSession, *, user_id: uuid.UUID) -> User | None: ...
    async def create(self, session: AsyncSession, *, user: User) -> User: ...

class UserRepository(BaseSQLAlchemyRepository[User]):
    model_type = User

    async def find_by_id(self, session: AsyncSession, *, user_id: uuid.UUID) -> User | None:
        stmt = self.filter_select_by_kwargs(self.statement, {"id": user_id})
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
```

## Model Layer (`apps/{module}/models.py`)

- SQLAlchemy 2.x declarative models with `Mapped` type annotations
- Inherit from base classes: `UUIDAuditBase`, `BigIntAuditBase`
- Use mixins: `HasSoftDeletedMixin`, `HasSlugMixin`, etc.
- Business methods allowed on models (e.g., `user.delete()`)

```python
class User(UUIDAuditBase, HasSoftDeletedMixin):
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
```

## Data Flow

```
HTTP Request → Route(Pydantic schema) → Service(schema→model) → Repository(ORM query)
→ DB → Repository(ORM model) → Service(model→response schema) → Route(APIResponse) → HTTP Response
```

## Shared Code Location

- Shared infrastructure lives in `libs/` — NOT in `apps/`
- Module-specific code lives in `apps/{module}/`
- Cross-module imports between `apps/` modules should go through services, NEVER direct model imports
