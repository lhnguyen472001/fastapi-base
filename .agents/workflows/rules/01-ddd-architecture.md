# DDD 4-Layer Architecture

## Layer Structure

```
Presentation → Application → Domain → Infrastructure
```

Dependencies **ONLY flow downward**. ❌ NEVER import from layers above.

## Presentation Layer (`presentation/`)

- Controllers inject **Adapters** (`{Entity}Adapter`), NOT Services
- Return **Presentation DTOs** — ❌ NEVER Domain Models
- Use `@Valid` for request validation

```java
@RestController
@RequestMapping("/api/v1/users")
@RequiredArgsConstructor
public class UserController {
    private final UserAdapter userAdapter; // ✅ Adapter

    @PostMapping
    public ResponseEntity<BaseResponse<UserResponse>> create(
            @Valid @RequestBody CreateUserRequest request) {
        return ResponseEntity.ok(BaseResponse.success(userAdapter.create(request)));
    }
}
```

## Application Layer (`application/`)

- Use Domain Repositories (interfaces) and Domain Models only
- ❌ NEVER import Presentation or Infrastructure
- `@Transactional` placed here

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class UserServiceImpl implements UserService {
    private final UserRepository userRepository;       // ✅ Domain Repository
    private final SecurityContextService securityCtx;  // ✅ Domain Service

    @Override
    @Transactional
    public UserDto create(CreateUserDto request) {
        log.info("UserServiceImpl - create - Creating user: {}", request.username());
        User user = UserApplicationMapper.toDomain(request);
        return UserApplicationMapper.toDto(userRepository.save(user));
    }
}
```

## Domain Layer (`domain/`)

- **Pure POJO** — ❌ NO JPA, NO Spring annotations
- CAN have business methods
- Repository/Service: **interfaces only**

```java
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class User {
    private String id;
    private String username;
    private UserStatus status;

    public boolean isActive() { return status == UserStatus.ACTIVE; }
}
```

## Infrastructure Layer (`infrastructure/`)

- Implements Domain interfaces via Repository Adapters
- Maps JPA Entities ↔ Domain Models

```java
@Component
@RequiredArgsConstructor
public class UserRepositoryAdapter implements UserRepository {
    private final UserJpaRepository jpaRepository;

    @Override
    public Optional<User> findById(String id) {
        return jpaRepository.findById(id).map(UserMapper::toDomain);
    }

    @Override
    public User save(User user) {
        return UserMapper.toDomain(jpaRepository.save(UserMapper.toEntity(user)));
    }
}
```

## Data Flow

```
HTTP → Controller → Adapter(PresDTO→AppDTO) → Service → Mapper(AppDTO→Domain)
→ Repository(interface) → Adapter(Domain→Entity) → DB → reverse path
```
