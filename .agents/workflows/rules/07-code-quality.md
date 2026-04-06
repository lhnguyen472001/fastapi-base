# Code Quality Standards

## Logging

- ✅ Format: `{ClassName} - {methodName} - {message}`
- ✅ `@Slf4j` from Lombok
- ✅ SLF4J placeholders `{}` — ❌ NEVER string concatenation

```java
log.info("UserServiceImpl - create - Creating user: {}", username);

// ❌ NEVER
log.info("Creating user: " + username);
```

## Messages & Validation

- ❌ **NEVER** hardcode error messages
- ✅ Errors: `MessageService.getMessage("error.user.not.found")`
- ✅ Validation: `@NotBlank(message = "{validation.user.username.required}")`
- ✅ Key pattern: `{category}.{entity}.{action}.{detail}`

```java
// ✅ MessageService
throw new KofosException(
    UserErrorCode.NOT_FOUND,
    messageService.getMessage("error.user.not.found", userId)
);

// ❌ Hardcoded
throw new KofosException("User not found: " + userId);
```

## Configuration

- ❌ **NEVER** hardcode config values
- ✅ Pattern: `${ENV_VAR:default}` in `application.yml`
- ✅ Sensitive data: **NO defaults** (passwords, JWT secrets)
- ✅ New env var → update `.env.*.example` AND `.env.example`

## Code Comments

- ❌ AVOID inline comments explaining what code does
- ❌ AVOID commented-out code
- ✅ Self-documenting code with clear naming
- ✅ Only comment: complex business logic, workarounds, non-obvious behavior

## Language

- ❌ **NEVER** Vietnamese in code, comments, variables
- ✅ ALL code MUST be in English
