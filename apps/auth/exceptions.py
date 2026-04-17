"""Auth module exceptions."""

import enum

from apps.core.exceptions.errors import BadRequestError, UnauthorizedError


class AuthErrorCodes(enum.StrEnum):
    """Auth module error codes."""

    AUTH001 = "AUTH001"  # Invalid credentials
    AUTH002 = "AUTH002"  # Invalid / malformed / wrong-type token
    AUTH003 = "AUTH003"  # Token expired
    AUTH004 = "AUTH004"  # Refresh token revoked or unknown
    AUTH005 = "AUTH005"  # Email not verified
    AUTH006 = "AUTH006"  # OTP wrong / expired / exhausted
    AUTH007 = "AUTH007"  # 2FA required (login step 2 needed)
    AUTH008 = "AUTH008"  # 2FA code invalid
    AUTH009 = "AUTH009"  # OAuth provider error
    AUTH010 = "AUTH010"  # 2FA not enabled (when trying to disable)
    AUTH011 = "AUTH011"  # OAuth state token expired
    AUTH012 = "AUTH012"  # OAuth state token invalid or subject mismatch
    AUTH013 = "AUTH013"  # OAuth provider reported the email as not verified


class InvalidCredentialsError(UnauthorizedError):
    """Wrong email/password or unknown user. Same error to avoid enumeration."""

    code: str = AuthErrorCodes.AUTH001

    def __init__(self, *, message: str = "Invalid email or password.") -> None:
        super().__init__(code=self.code, message=message)


class InvalidTokenError(UnauthorizedError):
    """JWT signature/type/format failed validation."""

    code: str = AuthErrorCodes.AUTH002

    def __init__(self, *, message: str = "Invalid token.") -> None:
        super().__init__(code=self.code, message=message)


class TokenExpiredError(UnauthorizedError):
    """JWT past its ``exp`` claim."""

    code: str = AuthErrorCodes.AUTH003

    def __init__(self, *, message: str = "Token has expired.") -> None:
        super().__init__(code=self.code, message=message)


class RefreshTokenRevokedError(UnauthorizedError):
    """Refresh token was already used, revoked, or never existed."""

    code: str = AuthErrorCodes.AUTH004

    def __init__(self, *, message: str = "Refresh token is no longer valid.") -> None:
        super().__init__(code=self.code, message=message)


class EmailNotVerifiedError(UnauthorizedError):
    """User's email has not been verified yet."""

    code: str = AuthErrorCodes.AUTH005

    def __init__(self, *, message: str = "Email address is not verified.") -> None:
        super().__init__(code=self.code, message=message)


class InvalidOtpError(BadRequestError):
    """OTP code is wrong, expired, exhausted, or already used."""

    code: str = AuthErrorCodes.AUTH006

    def __init__(self, *, message: str = "Invalid or expired verification code.") -> None:
        super().__init__(code=self.code, message=message)


class TwoFactorRequiredError(UnauthorizedError):
    """Login step 1 succeeded but 2FA challenge must be answered."""

    code: str = AuthErrorCodes.AUTH007

    def __init__(self, *, message: str = "Two-factor authentication required.") -> None:
        super().__init__(code=self.code, message=message)


class InvalidTwoFactorCodeError(UnauthorizedError):
    """The TOTP code does not match the user's secret."""

    code: str = AuthErrorCodes.AUTH008

    def __init__(self, *, message: str = "Invalid two-factor authentication code.") -> None:
        super().__init__(code=self.code, message=message)


class OAuthProviderError(BadRequestError):
    """Google rejected the code, network error, or userinfo malformed."""

    code: str = AuthErrorCodes.AUTH009

    def __init__(self, *, message: str = "OAuth provider error.") -> None:
        super().__init__(code=self.code, message=message)


class TwoFactorNotEnabledError(BadRequestError):
    """Disable-2FA called on a user without 2FA enabled."""

    code: str = AuthErrorCodes.AUTH010

    def __init__(self, *, message: str = "Two-factor authentication is not enabled.") -> None:
        super().__init__(code=self.code, message=message)


class OAuthStateExpiredError(UnauthorizedError):
    """The signed OAuth state token is past its ``exp`` claim."""

    code: str = AuthErrorCodes.AUTH011

    def __init__(self, *, message: str = "OAuth state has expired.") -> None:
        super().__init__(code=self.code, message=message)


class OAuthStateInvalidError(UnauthorizedError):
    """The OAuth state token failed signature/type/subject validation.

    Used for every form of tampering: wrong signature, wrong token type,
    or a subject claim that is not ``oauth_state``. Message is generic to
    avoid leaking which check failed.
    """

    code: str = AuthErrorCodes.AUTH012

    def __init__(self, *, message: str = "OAuth state is invalid.") -> None:
        super().__init__(code=self.code, message=message)


class OAuthEmailNotVerifiedError(BadRequestError):
    """The OAuth provider returned ``email_verified=false``.

    We refuse to create/link accounts from unverified provider emails
    because otherwise an attacker who controls an SMTP relay could take
    over an account that was about to be registered with that address.
    """

    code: str = AuthErrorCodes.AUTH013

    def __init__(self, *, message: str = "OAuth account email is not verified.") -> None:
        super().__init__(code=self.code, message=message)
