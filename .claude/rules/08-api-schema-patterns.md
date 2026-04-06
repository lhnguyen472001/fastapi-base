# API, Schema Patterns & Migrations

## API Path Conventions

| Context | Path Prefix | Auth Required |
|---|---|---|
| Public | `/api/v1/public/**` | No |
| Authenticated | `/api/v1/**` | Yes (JWT Bearer) |
| Admin | `/api/v1/admin/**` | Yes (admin role) |

## Router Patterns

```python
# Module router
router = APIRouter(prefix="/users", tags=["users"])

# All endpoints return APIResponse wrapper
@router.post("", response_model=APIResponse[UserResponse], status_code=201)
@inject
async def create_user(
    data: CreateUserRequest,
    session: AsyncSession = Depends(session_factory),
    service: UserService = Depends(Provide[UserContainer.user_service]),
) -> APIResponse[UserResponse]:
    ...

# Include in main app
app.include_router(router, prefix="/api/v1")
```

## Schema Patterns (Pydantic v2)

### Request Schemas — WITH validation

```python
class CreateUserRequest(RequestObjectSchema):
    email: EmailStr = Field(..., description="User email address")
    username: str = Field(..., min_length=3, max_length=150, description="Username")
    password: str = Field(..., min_length=8, max_length=128, description="Password")

class UpdateUserRequest(RequestObjectSchema):
    email: EmailStr | None = Field(default=None)
    username: str | None = Field(default=None, min_length=3, max_length=150)
    # Use exclude_unset=True when converting: data.model_dump(exclude_unset=True)
```

### Response Schemas — FROM ORM via model_validate

```python
class UserResponse(ResponseObjectSchema):
    id: uuid.UUID
    email: str
    username: str
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

# Convert ORM → response (from_attributes=True in ResponseObjectSchema)
UserResponse.model_validate(user_orm_instance)
```

### Pagination

```python
# Request: extend OffsetPaginationRequestSchema
class ListUsersRequest(OffsetPaginationRequestSchema):
    is_active: bool | None = Field(default=None, description="Filter by active status")

# Response: use PaginatedResponse[T]
PaginatedResponse[UserResponse](items=[...], total=100, limit=20, offset=0)
```

### API Response Wrapper

```python
# ALL endpoints return this structure
APIResponse[UserResponse](
    code=ResponseCodes.API000,       # Business code
    data=user_response,              # Typed payload
    status=JsonResponseStatuses.SUCCESS,
    message="User created successfully.",
)
```

## Schema Rules

- Request schemas: `{Action}{Entity}Request` — WITH Field validation
- Response schemas: `{Entity}Response` — with `from_attributes=True`
- NEVER expose `hashed_password` or sensitive fields in response schemas
- Use `model_dump(exclude_unset=True)` for partial updates
- NEVER return ORM model instances from routes — always Pydantic schemas

## Alembic Migrations

- **Location:** `alembic/versions/`
- **Naming:** Auto-generated with descriptive message
- **Commands:**
  ```bash
  uv run alembic revision --autogenerate -m "add_user_table"
  uv run alembic upgrade head
  uv run alembic downgrade -1
  ```
- NEVER modify a migration that has been applied to shared environments
- ALWAYS include both upgrade and downgrade functions
- Review auto-generated migrations before applying — verify column types, indexes, constraints
