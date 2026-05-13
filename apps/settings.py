import functools
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL

__all__ = ["StorageSettings", "app_settings"]


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

    # Optional read-replica connection. When ``reader_host`` is set, a
    # second ``reader_uri`` is built and ``engine_factory(READER)`` will
    # use it; otherwise the reader engine reuses the writer URI. Set
    # ``DB_READER_HOST`` (and optionally ``DB_READER_PORT`` / ``_USER`` /
    # ``_PASSWORD`` / ``_DATABASE``) in the environment to enable.
    reader_host: str | None = Field(default=None, description="Read-replica host (optional)")
    reader_port: int | None = Field(default=None, description="Read-replica port (defaults to ``port``)")
    reader_user: str | None = Field(default=None, description="Read-replica user (defaults to ``user``)")
    reader_password: SecretStr | None = Field(
        default=None,
        description="Read-replica password (defaults to ``password``)",
    )
    reader_database: str | None = Field(default=None, description="Read-replica database (defaults to ``database``)")
    reader_uri: URL | None = Field(default=None, description="Computed read-replica URI; None if no replica configured")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def build_database_uri(self) -> "DatabaseSettings":
        """Build writer (and optional reader) URLs from connection settings."""
        drivername = f"postgresql+{self.driver}" if "+" not in self.driver else self.driver
        self.database_uri = URL.create(
            drivername=drivername,
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
        )
        if self.reader_host is not None:
            reader_password = self.reader_password if self.reader_password is not None else self.password
            self.reader_uri = URL.create(
                drivername=drivername,
                username=self.reader_user or self.user,
                password=reader_password.get_secret_value(),
                host=self.reader_host,
                port=self.reader_port or self.port,
                database=self.reader_database or self.database,
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

    # Optional Redis-backed watcher. When set, ``enforcer_factory`` attaches a
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


class StorageSettings(BaseModel):
    """Object-storage settings (LocalStack S3 in dev, real AWS S3 in prod).

    Defaults point at the LocalStack container declared in ``compose.yml``
    so dev-mode flows just work after ``docker compose up``.
    """

    s3_endpoint_url: str | None = Field(
        default="http://localhost:4566",
        description=(
            "Custom S3 endpoint. Set to ``None`` to use the AWS default "
            "(production); keep the LocalStack URL for local dev."
        ),
    )
    s3_region: str = Field(default="us-east-1", description="AWS region.")
    s3_bucket: str = Field(
        default="fastapi-base-blog",
        description="Default bucket for blog media.",
    )
    s3_access_key_id: SecretStr = Field(
        default=SecretStr("test"),
        description="Access key (LocalStack accepts any value; real AWS requires the IAM key).",
    )
    s3_secret_access_key: SecretStr = Field(
        default=SecretStr("test"),
        description="Secret key (LocalStack accepts any value).",
    )

    presign_expires_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        description="Lifetime of presigned upload URLs (seconds).",
    )
    max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        description="Server-enforced cap on direct-to-S3 uploads (bytes).",
    )
    use_path_style: bool = Field(
        default=True,
        description=(
            "Path-style addressing for S3 URLs. Required for LocalStack "
            "(``http://host:4566/<bucket>/<key>``). Disable for real AWS S3."
        ),
    )


class ObservabilitySettings(BaseModel):
    """OpenTelemetry tracing settings.

    The module is a no-op when ``enabled=False`` so dev / test runs do
    not require an OTel collector. Flip on to install the tracer provider
    and instrument FastAPI / SQLAlchemy / Redis. ``otlp_endpoint`` may be
    omitted even when enabled — the provider is still installed (logs
    carry ``trace_id`` / ``span_id``) but no exporter is attached.
    """

    enabled: bool = Field(
        default=False,
        description="Master switch — install tracer provider + instrumentors when true.",
    )
    service_name: str = Field(
        default="fastapi-base",
        description="``service.name`` resource attribute attached to every span.",
    )
    otlp_endpoint: str | None = Field(
        default=None,
        description=(
            "Default OTLP/gRPC endpoint used by traces, logs, and metrics "
            "when no signal-specific override is set. "
            "Example: http://otel-collector:4317 — leave empty to skip exporting."
        ),
    )
    otlp_logs_endpoint: str | None = Field(
        default=None,
        description=(
            "OTLP/gRPC endpoint for the LogRecord exporter. Falls back to "
            "``otlp_endpoint`` when unset. Leave empty to disable log export "
            "while keeping traces/metrics."
        ),
    )
    otlp_metrics_endpoint: str | None = Field(
        default=None,
        description=(
            "OTLP/gRPC endpoint for the periodic metric reader. Falls back to "
            "``otlp_endpoint`` when unset. Leave empty to disable metric export."
        ),
    )
    logs_export_enabled: bool = Field(
        default=True,
        description=(
            "Install the OTel LoggerProvider + loguru OTLP sink when "
            "observability is enabled. Disable to keep logs local."
        ),
    )
    metrics_export_enabled: bool = Field(
        default=True,
        description=(
            "Install the OTel MeterProvider + periodic OTLP exporter when "
            "observability is enabled. Disable to skip metrics."
        ),
    )
    metric_export_interval_millis: int = Field(
        default=30_000,
        ge=1_000,
        description="Interval for the OTLP periodic metric reader (milliseconds).",
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


class BlogSettings(BaseModel):
    """Blog-module operational tunables.

    Env vars use the ``BLOG_`` prefix and map onto these fields via the
    project-wide ``env_nested_delimiter='_'`` + ``env_nested_max_split=1``
    rule, e.g. ``BLOG_POST_VERSION_RETENTION_LIMIT=25`` →
    ``app_settings.blog.post_version_retention_limit``.
    """

    post_version_retention_limit: int = Field(
        default=20,
        ge=1,
        description=(
            "Cap on non-published draft versions kept per post. The retention "
            "sweeper trims older non-published rows; published-snapshot rows "
            "are never purged."
        ),
    )
    post_version_compression_level: int = Field(
        default=3,
        ge=1,
        le=22,
        description=(
            "zstd compression level for ``post_versions.content_json_compressed``. "
            "1=fast, 22=max ratio; level 3 is the standard speed/ratio balance."
        ),
    )
    post_version_sweep_interval: float = Field(
        default=600.0,
        ge=1.0,
        description="Seconds between post-version retention-sweep ticks.",
    )
    large_content_bytes: int = Field(
        default=65_536,
        ge=1_024,
        le=16 * 1024 * 1024,
        description=(
            "Editor JSON payload size at or above which the Tiptap content "
            "pipeline (render_html + sanitize_html + compress + word/text "
            "extraction) is offloaded to a worker thread via "
            "``asyncio.to_thread``. Below this threshold the pipeline runs "
            "inline (no thread hand-off cost). Valid range: 1 KiB to 16 MiB."
        ),
    )

    # Engagement — comment edit window + moderation sweeper.
    post_comment_edit_window_seconds: int = Field(
        default=15 * 60,
        ge=60,
        description=(
            "Window (seconds since ``created_at``) during which an "
            "authenticated author can edit their own comment. Anonymous "
            "comments are never editable regardless of this value."
        ),
    )
    post_comment_moderation_pending_ttl_seconds: int = Field(
        default=30 * 24 * 3600,
        ge=3600,
        description=(
            "TTL (seconds) for anonymous comments stuck in the moderation "
            "queue. The leader-elected sweeper purges ``state='pending'`` "
            "rows older than this. Default 30 days."
        ),
    )
    post_comment_moderation_sweep_interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Seconds between comment-moderation sweeper ticks (default hourly).",
    )

    # Engagement — rate-limit thresholds (slowapi-formatted strings).
    post_like_rate_limit: str = Field(
        default="60/minute",
        description=(
            "slowapi limit string for like / unlike requests, keyed per "
            "authenticated user (FR-024a)."
        ),
    )
    post_comment_auth_rate_limit: str = Field(
        default="10/minute",
        description=(
            "slowapi limit string for authenticated comment submissions, "
            "keyed per ``current_user.id`` (FR-024)."
        ),
    )
    post_comment_anonymous_rate_limit: str = Field(
        default="3/minute;30/day",
        description=(
            "slowapi compound limit string for anonymous comment "
            "submissions, keyed per source IP (FR-024b). The per-day clamp "
            "catches slow-drip spammers that the per-minute limit misses."
        ),
    )


_DEFAULT_DEV_DB_PASSWORD = "postgres"  # noqa: S105 — sentinel value compared against, not a real password


class ApplicationSettings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="ignore",
    )

    # Endpoint settings
    host: str = Field(default="0.0.0.0", description="Host")  # noqa: S104
    port: int = Field(default=8000, description="Port")
    reload: bool = Field(default=False, description="Reload")
    workers: int = Field(default=1, description="Workers")
    app_name: str = Field(default="FastAPI Base", description="Application display name")
    environment: str = Field(
        default="development",
        description="Deployment environment: development | staging | production",
    )
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
    storage: StorageSettings = Field(default_factory=StorageSettings, description="Object-storage (S3) settings")
    observability: ObservabilitySettings = Field(
        default_factory=ObservabilitySettings,
        description="OpenTelemetry tracing settings",
    )
    blog: BlogSettings = Field(default_factory=BlogSettings, description="Blog-module operational tunables")

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
