# Naming Conventions (Senior Level)

## Component Naming

| Component | Pattern | Example |
|---|---|---|
| Controller | `{Entity}Controller` | `UserController` |
| Service Interface | `{Entity}Service` | `UserService` |
| Service Impl | `{Entity}ServiceImpl` | `UserServiceImpl` |
| Presentation Adapter | `{Entity}Adapter` | `UserAdapter` |
| DTO Adapter | `{Entity}DtoAdapter` | `UserDtoAdapter` |
| Application Mapper | `{Entity}ApplicationMapper` | `UserApplicationMapper` |
| Domain Model | `{Entity}` | `User` |
| Domain Repository | `{Entity}Repository` | `UserRepository` |
| Repository Adapter | `{Entity}RepositoryAdapter` | `UserRepositoryAdapter` |
| JPA Repository | `{Entity}JpaRepository` | `UserJpaRepository` |
| JPA Entity | `{Entity}Entity` | `UserEntity` |
| Request DTO | `{Action}{Entity}Request` | `CreateUserRequest` |
| Response DTO | `{Entity}Response` | `UserResponse` |
| Command | `{Feature}Command` | `WorkflowApprovalCommand` |
| Query | `{Feature}Query` | `MeetingRoomBookingQuery` |
| Context | `{Feature}Context` | `WorkflowApprovalContext` |

## Java Naming Rules

| Element | Convention | Good ✅ | Bad ❌ |
|---|---|---|---|
| Class | Noun, PascalCase | `OrderService` | `doOrder` |
| Interface | Noun, PascalCase (NO `I` prefix) | `PaymentGateway` | `IPaymentGateway` |
| Abstract | Prefix `Abstract` or `Base` | `AbstractController` | `ControllerBase` |
| Method | Verb, camelCase | `calculatePrice()` | `price()` |
| Boolean | `is`, `has`, `can`, `should` | `isExpired` | `expired` |
| Constant | UPPER_SNAKE_CASE | `MAX_RETRY_LIMIT` | `maxRetry` |
| DTO | Suffix `Request` / `Response` | `UserRequest` | `UserDTO` |
| Enum | Singular noun, UPPER values | `OrderStatus { PENDING }` | `OrderStatuses` |

## Anti-Patterns

- ❌ **No Redundancy:** `Order.orderDate` → use `Order.createdAt`
- ❌ **No Abbreviations:** `usrSvc` → use `UserService`
- ✅ **ALL code, comments, variables MUST be in English**
