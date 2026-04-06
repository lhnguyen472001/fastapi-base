import enum

from libs.exceptions.errors import ConflictError, NotFoundError


class UserErrorCodes(enum.StrEnum):
    """User module error codes."""

    USER001 = "USER001"  # User not found
    USER002 = "USER002"  # User already exists (email/username conflict)
    USER003 = "USER003"  # User inactive


class UserNotFoundError(NotFoundError):
    """Raised when a user is not found."""

    code: str = UserErrorCodes.USER001

    def __init__(self, *, message: str = "User not found.") -> None:
        super().__init__(code=self.code, message=message)


class UserAlreadyExistsError(ConflictError):
    """Raised when a user with the same email or username already exists."""

    code: str = UserErrorCodes.USER002

    def __init__(self, *, message: str = "User already exists.") -> None:
        super().__init__(code=self.code, message=message)


class UserInactiveError(NotFoundError):
    """Raised when attempting to operate on an inactive user."""

    code: str = UserErrorCodes.USER003

    def __init__(self, *, message: str = "User is inactive.") -> None:
        super().__init__(code=self.code, message=message)
