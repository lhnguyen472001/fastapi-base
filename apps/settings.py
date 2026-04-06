import functools

from pydantic import BaseModel, Field, SecretStr, model_validator
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

    @model_validator(mode="after")
    def build_database_uri(self) -> "DatabaseSettings":
        """Validate the database URL."""
        self.database_uri = URL.create(
            drivername=self.driver,
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
        )
        return self


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

    db: DatabaseSettings = Field(default_factory=DatabaseSettings, description="Database settings")


@functools.lru_cache()
def get_settings() -> ApplicationSettings:
    """Get the application settings."""
    return ApplicationSettings()


app_settings = get_settings()
