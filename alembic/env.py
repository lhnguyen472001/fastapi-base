import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so they register with the shared metadata
from apps.auth import models as _auth_models  # noqa: E402, F401
from apps.core.database.registry import orm_registry  # noqa: E402
from apps.settings import app_settings  # noqa: E402
from apps.user import models as _user_models  # noqa: E402, F401
from apps.rbac import models as _rbac_models  # noqa: E402, F401
from apps.product import models as _product_models  # noqa: E402, F401
from apps.workspace import models as _workspace_models  # noqa: E402, F401
from apps.blog import models as _blog_models  # noqa: E402, F401

target_metadata = orm_registry.metadata

# Use a masked URL for the ini option (ends up in alembic logs);
# the real URL is injected via run_async_migrations() below.
config.set_main_option(
    "sqlalchemy.url",
    app_settings.db.database_uri.render_as_string(hide_password=True),
)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def render_item(type_: str, obj, autogen_context) -> object:
    """Render custom DateTimeUTC with a fully-qualified import."""
    if type_ == "type" and obj.__class__.__module__.startswith("apps."):
        autogen_context.imports.add(f"import {obj.__class__.__module__}")
        return f"{obj.__class__.__module__}.{obj.__class__.__name__}()"
    return False


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    section = config.get_section(config.config_ini_section, {})
    # Override the masked URL with the real one (with password) for the engine,
    # without writing it back to the ini option that gets logged.
    section["sqlalchemy.url"] = app_settings.db.database_uri.render_as_string(hide_password=False)
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
