import functools
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL

__all__ = ["app_settings"]


class DatabaseSettings(BaseModel):
    """Database settings."""

    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    user: str = Field(default="postgres", description="Database user")
    password: SecretStr = Field(default=SecretStr("postgres"), description="Database password")
    database: str = Field(default="fastapi_base", description="Database name")

    pool_size: int = Field(default=10, description="Pool size")
    pool_recycle: int = Field(default=1800, description="Pool recycle")
    max_overflow: int = Field(default=20, description="Max overflow")
    pool_timeout: int = Field(default=30, description="Pool timeout")
    pool_pre_ping: bool = Field(default=True, description="Pool pre ping")

    driver: str = Field(default="asyncpg", description="Database driver")
    database_uri: URL = Field(default=None, description="Computed database URI")  # type: ignore[assignment]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def build_database_uri(self) -> "DatabaseSettings":
        """Build the database URL from connection settings."""
        self.database_uri = URL.create(
            drivername=f"postgresql+{self.driver}" if "+" not in self.driver else self.driver,
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
        )
        return self


class AuthSettings(BaseModel):
    """Authentication and authorization settings."""

    # JWT (RS256 — public/private key files)
    jwt_algorithm: Literal["RS256"] = Field(
        default="RS256",
        description="JWT signing algorithm. Hard-pinned to RS256 to block RS256->HS256 confusion.",
    )
    jwt_private_key_path: Path = Field(
        default=Path("./keys/jwt_private.pem"),
        description="Path to RSA private key (PEM)",
    )
    jwt_public_key_path: Path = Field(
        default=Path("./keys/jwt_public.pem"),
        description="Path to RSA public key (PEM)",
    )
    jwt_issuer: str = Field(
        default="fastapi-base",
        description="JWT 'iss' claim, verified on decode; tokens minted by other issuers are rejected.",
    )
    jwt_audience: str = Field(
        default="fastapi-base",
        description="JWT 'aud' claim, verified on decode; tokens minted for other audiences are rejected.",
    )
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=30, ge=1)
    challenge_token_expire_minutes: int = Field(default=5, ge=1, description="Lifetime of the 2FA challenge JWT")

    # OTP (email verification)
    otp_length: int = Field(default=6, ge=4, le=10)
    otp_expire_minutes: int = Field(default=10, ge=1)
    otp_max_attempts: int = Field(default=5, ge=1)

    # TOTP (2FA)
    totp_issuer: str = Field(default="FastAPI Base", description="Issuer name shown in authenticator apps")

    # Google OAuth2
    google_client_id: str = Field(default="")
    google_client_secret: SecretStr = Field(default=SecretStr(""))
    google_redirect_uri: str = Field(default="http://localhost:8000/api/v1/auth/oauth/google/callback")


class RBACSettings(BaseModel):
    """RBAC / Casbin settings."""

    # Optional Redis-backed watcher. When set, ``create_enforcer`` attaches a
    # pub/sub watcher so policy mutations on one worker invalidate the in-memory
    # enforcer on every other worker. Required before running
    # ``uvicorn --workers >1``; leave unset for single-worker dev.
    #
    # Install the optional dependency separately, e.g.:
    #     uv add casbin-redis-watcher
    watcher_redis_url: str | None = Field(
        default=None,
        description="Redis URL for the Casbin watcher (e.g. redis://localhost:6379/0)",
    )


class EmailSettings(BaseModel):
    """Email sender settings (SMTP + Jinja templates)."""

    sender_address: str = Field(default="no-reply@fastapi-base.local")
    sender_name: str = Field(default="FastAPI Base")

    # SMTP — defaults point at the MailHog container in compose.yml.
    smtp_host: str = Field(default="localhost")
    smtp_port: int = Field(default=1025)
    smtp_use_tls: bool = Field(default=False)
    smtp_username: SecretStr = Field(default=SecretStr(""))
    smtp_password: SecretStr = Field(default=SecretStr(""))
    smtp_timeout_seconds: int = Field(default=5, ge=1)

    # Jinja template directory.
    template_dir: Path = Field(default=Path("apps/core/email/templates"))


class ApplicationSettings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
    )

    # Endpoint settings
    host: str = Field(default="0.0.0.0", description="Host")
    port: int = Field(default=8000, description="Port")
    reload: bool = Field(default=False, description="Reload")
    workers: int = Field(default=1, description="Workers")
    app_name: str = Field(default="FastAPI Base", description="Application display name")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins (set via CORS_ORIGINS env var)",
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings, description="Database settings")
    auth: AuthSettings = Field(default_factory=AuthSettings, description="Auth settings")
    email: EmailSettings = Field(default_factory=EmailSettings, description="Email settings")
    rbac: RBACSettings = Field(default_factory=RBACSettings, description="RBAC / Casbin settings")


@functools.lru_cache
def get_settings() -> ApplicationSettings:
    """Get the application settings."""
    return ApplicationSettings()


app_settings = get_settings()
