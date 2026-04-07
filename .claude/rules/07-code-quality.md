---
description: Code quality standards for FastAPI Base — logging, messages, configuration, comments. Apply to ALL coding tasks.
---

# Code Quality Standards

## Logging

- Use `loguru` (project standard), NEVER `print()` for application output
- Format: `{ClassName} - {method_name} - {message}`
- Use f-strings with loguru (loguru handles lazy evaluation)
- Log structured context data, not just messages

```python
from loguru import logger

# Standard logging
logger.info(f"UserService - create - Creating user: {username}")
logger.error(f"UserService - create - Failed to create user: {error}")

# With structured context
logger.bind(user_id=user_id, action="create").info("User created successfully")

# NEVER use print
print(f"Creating user: {username}")  # FORBIDDEN
```

## Error Messages

- NEVER hardcode error messages in business logic
- Define error codes as `StrEnum` in each module's `exceptions.py`
- Use `BackendError` subclasses with descriptive messages
- Error messages should be user-friendly and actionable

```python
import enum

class UserErrorCodes(enum.StrEnum):
    USER001 = "USER001"  # User not found
    USER002 = "USER002"  # User already exists
    USER003 = "USER003"  # User is inactive

class UserNotFoundException(BackendError):
    code = UserErrorCodes.USER001
    status_code = 404

# Raise with message
raise UserNotFoundException(message=f"User with ID {user_id} not found")

# NEVER hardcode error strings directly
raise Exception("User not found: " + str(user_id))  # FORBIDDEN
```

## Configuration

- NEVER hardcode configuration values
- All config via `pydantic-settings` from environment variables
- Sensitive data (passwords, JWT secrets): NO defaults — must be set in env
- New env vars -> update `.env.example`

```python
# apps/settings.py — pydantic-settings
class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")

    host: str = Field(default="0.0.0.0")
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)

# Access via singleton
from apps.settings import app_settings
engine = create_async_engine(app_settings.db.database_uri)
```

## Code Comments

- NEVER add inline comments explaining what code does
- NEVER leave commented-out code
- Self-documenting code with clear naming
- Only comment: complex business logic, workarounds, non-obvious behavior
- Use Google-style docstrings for all public functions/classes

```python
# BAD — narrating what the code does
user = await repo.get(id)  # Get user from database
if user is None:  # Check if user exists
    raise NotFoundException()  # Raise not found error

# GOOD — self-documenting, no comments needed
user = await repo.get(id)
if user is None:
    raise UserNotFoundException(message=f"User {id} not found")

# GOOD — commenting non-obvious behavior
# RoutingSession directs reads to replica and writes to primary
# based on the statement type (SELECT vs INSERT/UPDATE/DELETE)
class RoutingSession(Session):
    ...
```

## Docstrings (Google Style)

```python
async def list_users(
    session: AsyncSession,
    *,
    filters: list[StatementFilter] | None = None,
    limit: int = 20,
) -> tuple[list[User], int]:
    """List users with optional filtering.

    Args:
        session: Database session.
        filters: Optional list of statement filters.
        limit: Maximum number of results.

    Returns:
        Tuple of (users list, total count).

    Raises:
        BackendError: If database query fails.
    """
```

## Language

- NEVER use Vietnamese (or any non-English language) in code, comments, variables
- ALL code MUST be in English
- Git commit messages in English
- Exception/error messages in English

## Linting & Formatting

- Use `ruff` for both linting and formatting
- Run `uv run ruff check .` before committing
- Run `uv run ruff format .` before committing
- Fix all linter errors before submitting code
