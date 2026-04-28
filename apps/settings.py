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
    oauth_state_expire_minutes: int = Field(
        default=5,
        ge=1,
        description="Lifetime of the signed OAuth state JWT (and its companion HttpOnly cookie).",
    )

    # OTP (email verification)
    otp_length: int = Field(default=6, ge=4, le=10)
    otp_expire_minutes: int = Field(default=10, ge=1)
    otp_max_attempts: int = Field(default=5, ge=1)

    # TOTP (2FA)
    totp_issuer: str = Field(default="FastAPI Base", description="Issuer name shown in authenticator apps")
    totp_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Fernet key (44 url-safe base64 chars) used to encrypt the TOTP "
            "secret column at rest. REQUIRED in production; an empty value "
            "in dev/test falls back to a deterministic per-process key."
        ),
    )

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

    # Auto-seed permissions and Casbin policies from ``@rbac_resource``-decorated
    # models at startup. Off by default — flip on once the system_admin role is
    # the canonical bootstrap role for your environment.
    auto_seed_resources_from_registry: bool = Field(
        default=False,
        description=(
            "If true, the lifespan hook reads apps.rbac.registry._RESOURCE_REGISTRY "
            "and idempotently inserts the matching Permission rows + admin Casbin "
            "policies on every worker boot."
        ),
    )
    system_admin_role_name: str = Field(
        default="system_admin",
        description="Role granted every (resource, action) pair declared via @rbac_resource.",
    )


class RedisSettings(BaseModel):
    """Redis connection settings (cache, distributed locks, etc.).

    The module is a no-op when ``enabled=False`` — ``get_redis_client()``
    returns ``None`` and ``CacheManager`` short-circuits every call. Flip
    on once Redis is reachable from the app process.
    """

    enabled: bool = Field(
        default=False,
        description="Master switch — disable to bypass Redis entirely (dev / tests without Redis).",
    )
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    database: int = Field(default=0, ge=0, description="Redis logical database index")
    password: SecretStr | None = Field(default=None, description="Redis password (optional)")
    max_connections: int = Field(default=20, ge=1, description="Connection pool size")
    socket_timeout: float = Field(default=5.0, gt=0, description="Per-operation socket timeout (seconds)")
    socket_connect_timeout: float = Field(default=5.0, gt=0, description="Connection establish timeout (seconds)")
    decode_responses: bool = Field(
        default=True,
        description="Auto-decode bytes -> str. Required for the JSON-based CacheManager.",
    )


class RateLimitSettings(BaseModel):
    """Per-process rate-limiting settings (slowapi)."""

    storage_uri: str = Field(
        default="memory://",
        description=(
            "slowapi/limits storage backend URI. ``memory://`` is per-worker "
            "(fine for single-worker dev); use ``redis://host:port/db`` for "
            "multi-worker so limits are shared."
        ),
    )
    enabled: bool = Field(
        default=True,
        description="Master switch — set to false to bypass all rate limits (tests).",
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
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings, description="Rate-limit settings")
    redis: RedisSettings = Field(default_factory=RedisSettings, description="Redis settings")

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "ApplicationSettings":
        """Refuse to boot in production with default dev secrets or partial OAuth config.

        Local dev keeps working because ``environment`` defaults to
        ``"development"``; the production checks only fire when
        ``ENVIRONMENT=production`` is set in the environment.

        OAuth pairing is enforced regardless of environment: the Google
        OAuth fields must be set together or omitted together. A half-
        configured client silently breaks the callback flow, and the
        check costs nothing.
        """
        if self.environment.lower() == "production" and self.db.password.get_secret_value() == _DEFAULT_DEV_DB_PASSWORD:
            msg = (
                "DB_PASSWORD is the default dev value but ENVIRONMENT=production. "
                "Set DB_PASSWORD to the real production credential."
            )
            raise ValueError(msg)

        if self.environment.lower() == "production" and not self.auth.totp_encryption_key.get_secret_value():
            msg = (
                "AUTH_TOTP_ENCRYPTION_KEY must be set in production. "
                "Generate one with `uv run python scripts/generate_totp_key.py`."
            )
            raise ValueError(msg)

        client_id = self.auth.google_client_id
        client_secret = self.auth.google_client_secret.get_secret_value()
        if bool(client_id) != bool(client_secret):
            msg = (
                "AUTH_GOOGLE_CLIENT_ID and AUTH_GOOGLE_CLIENT_SECRET must both be set "
                "or both be empty; partial OAuth config breaks the Google callback."
            )
            raise ValueError(msg)

        return self


@functools.lru_cache
def get_settings() -> ApplicationSettings:
    """Get the application settings."""
    return ApplicationSettings()


app_settings = get_settings()
