# Code Quality Standards

## Logging

- Use `logging` module (or `loguru` if configured) — NEVER `print()`
- Format: `{ClassName} - {method_name} - {message}`
- Use f-string or `%s` placeholders — NEVER string concatenation in log calls

```python
import logging

logger = logging.getLogger(__name__)

class UserService:
    async def create_user(self, session: AsyncSession, *, data: CreateUserRequest) -> UserResponse:
        logger.info("UserService - create_user - Creating user: %s", data.username)
        ...
        logger.error("UserService - create_user - Failed: %s", str(exc))

# NEVER
logger.info("Creating user: " + username)
print(f"Creating user: {username}")
```

## Error Handling

- Extend `BackendError` for domain exceptions
- Define module-specific error codes as `StrEnum`
- NEVER hardcode error messages — use structured error codes
- Use early return with specific exceptions

```python
# Module error codes
class UserErrorCodes(enum.StrEnum):
    USER001 = "USER001"  # User not found
    USER002 = "USER002"  # User already exists
    USER003 = "USER003"  # User inactive

# Custom exception
class UserNotFoundError(BackendError):
    code = UserErrorCodes.USER001
    status_code = 404

    def __init__(self, *, message: str = "User not found.") -> None:
        super().__init__(message=message, status=JsonResponseStatuses.ERROR)

# NEVER hardcode errors
raise Exception("User not found: " + user_id)  # FORBIDDEN
```

## Configuration

- NEVER hardcode config values in code
- ALL settings via `pydantic-settings` (`apps/settings.py`)
- Environment variables with sensible defaults
- Sensitive data (passwords, JWT secrets): NO defaults — must be set in env

```python
# Settings pattern
class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="_")

    host: str = Field(default="0.0.0.0")
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)

# Access via singleton
from apps.settings import app_settings
app_settings.db.host

# New env var → update .env.example
```

## Code Comments

- AVOID inline comments explaining what code does
- AVOID commented-out code — use git history
- Self-documenting code with clear naming
- Only comment: complex business logic, workarounds, non-obvious behavior
- Use Google-style docstrings for all public functions

```python
# Docstring format
async def create_user(
    self, session: AsyncSession, *, data: CreateUserRequest
) -> UserResponse:
    """Create a new user.

    Args:
        session: Database session.
        data: User creation data.

    Returns:
        Created user response.

    Raises:
        UserAlreadyExistsError: If email or username already taken.
    """
```

## Import Order

Follow this strict order (enforced by `ruff`):

1. Standard library (`import os`, `import uuid`)
2. Third-party (`from fastapi import ...`, `from sqlalchemy import ...`)
3. Local (`from apps.user.models import ...`, `from libs.schemas import ...`)

Separate each group with a blank line.

## Language

- NEVER Vietnamese in code, comments, variables, or commit messages
- ALL code MUST be in English
- Exception: user-facing messages can be localized (but keys/codes remain English)
