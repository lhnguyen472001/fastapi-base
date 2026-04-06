# Naming Conventions

## Component Naming

| Component | Pattern | Example |
|---|---|---|
| Router module | `routes.py` | `apps/user/routes.py` |
| Service class | `{Entity}Service` | `UserService` |
| Repository Protocol | `{Entity}RepositoryProtocol` | `UserRepositoryProtocol` |
| Repository class | `{Entity}Repository` | `UserRepository` |
| ORM Model | `{Entity}` (singular) | `User` |
| Request Schema | `{Action}{Entity}Request` | `CreateUserRequest` |
| Response Schema | `{Entity}Response` | `UserResponse` |
| List Request Schema | `List{Entity}sRequest` | `ListUsersRequest` |
| DI Container | `{Entity}Container` | `UserContainer` |
| Exception | `{Entity}{Error}Error` | `UserNotFoundError` |
| Error Codes Enum | `{Entity}ErrorCodes` | `UserErrorCodes` |
| Router instance | `router` | `router = APIRouter(...)` |

## Python Naming Rules (PEP 8)

| Element | Convention | Good | Bad |
|---|---|---|---|
| Class | PascalCase, noun | `OrderService` | `doOrder` |
| Function/Method | snake_case, verb | `calculate_price()` | `price()` |
| Variable | snake_case | `user_count` | `userCount` |
| Constant | UPPER_SNAKE_CASE | `MAX_RETRY_LIMIT` | `maxRetry` |
| Module | snake_case | `user_service.py` | `UserService.py` |
| Package | snake_case, no hyphens | `background_tasks` | `background-tasks` |
| Boolean | `is_`, `has_`, `can_`, `should_` | `is_expired` | `expired` |
| Private | Leading underscore | `_hash_password()` | `hashPassword()` |
| Type alias | PascalCase | `SQLAlchemyModelT` | `sqlalchemy_model_t` |
| Enum | PascalCase class, UPPER values | `OrderStatus.PENDING` | `OrderStatuses` |

## Anti-Patterns

- **No redundancy:** `User.user_email` → use `User.email`
- **No abbreviations:** `usr_svc` → use `user_service`
- **No camelCase** in Python code — always `snake_case` for functions/variables
- **No `I` prefix** on protocols: `UserRepositoryProtocol` not `IUserRepository`
- **ALL code, comments, variables MUST be in English**
