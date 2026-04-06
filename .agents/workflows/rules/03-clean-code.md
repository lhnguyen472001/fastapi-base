# Java & Spring Boot Clean Code

**Stack:** Java 21+, Spring Boot 3.x, Lombok

## Immutability — Prefer `record`

```java
// ✅ record for DTOs and data containers
public record CreateUserDto(String username, String email, String role) {}
public record UserResponse(String id, String username, UserStatus status) {}

// Use @Data @Builder for Domain Models needing mutability
```

## Injection — Constructor Only

```java
// ✅ Constructor injection via Lombok
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {
    private final UserRepository userRepository;
    private final MessageService messageService;
}

// ❌ FORBIDDEN: Field injection
@Autowired private UserRepository userRepository;
```

## Early Return — Reduce Nesting

```java
// ✅ Early return
public User findActiveUser(String id) {
    User user = userRepository.findById(id)
        .orElseThrow(() -> new KofosException(UserErrorCode.NOT_FOUND,
            messageService.getMessage("error.user.not.found")));
    if (!user.isActive()) {
        throw new KofosException(UserErrorCode.INACTIVE,
            messageService.getMessage("error.user.inactive"));
    }
    return user;
}

// ❌ Nested if-else — AVOID
```

## Mapping — MapStruct

- Use **MapStruct** for Entity ↔ DTO conversion
- ❌ NEVER return JPA Entity directly from Controller

## Function & Class Limits

| Constraint | Target | Maximum |
|---|---|---|
| Function length | 20–35 lines | 50 lines |
| Parameters | ≤ 3 | >3 → use DTO |
| Nesting depth | ≤ 2 levels | Extract methods |
| Class length | 200–500 lines | 600 lines |

**Refactoring triggers:**
- Function > 50 lines → extract methods
- Function > 3 params → create DTO
- Nesting > 2 levels → early returns / extract
- Class > 600 lines → split into multiple classes
