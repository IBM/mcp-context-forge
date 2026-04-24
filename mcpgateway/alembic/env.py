# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/env.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

Alembic environment configuration for database migrations.
This module configures the Alembic migration environment for ContextForge
application. It sets up both offline and online migration modes, configures
logging, and establishes the database connection parameters.

The module performs the following key functions:
- Configures Alembic to locate migration scripts in the mcpgateway package
- Sets up Python logging based on the alembic.ini configuration
- Imports the SQLAlchemy metadata from the application models
- Configures the database URL from application settings
- Provides functions for running migrations in both offline and online modes

Offline mode generates SQL scripts without connecting to the database, while
online mode executes migrations directly against a live database connection.

Attributes:
    config (Config): The Alembic configuration object loaded from alembic.ini.
    target_metadata (MetaData): SQLAlchemy metadata object containing all
        table definitions from the application models.

Examples:
    Running migrations in offline mode::

        alembic upgrade head --sql

    Running migrations in online mode::

        alembic upgrade head

    The module is typically not imported directly but is used by Alembic
    when executing migration commands.

Note:
    This file is automatically executed by Alembic and should not be
    imported or run directly by application code.
"""

# Standard
import logging
from importlib.resources import files
from logging.config import fileConfig

# Third-Party
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
from alembic.config import Config
from sqlalchemy import engine_from_config, pool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base

# from mcpgateway.db import get_metadata
# target_metadata = get_metadata()


# Create config object - this is the standard way in Alembic
config = getattr(context, "config", None) or Config()


def _inside_alembic() -> bool:
    """Detect if this module is being executed by the Alembic CLI.

    This function checks whether the current execution context is within
    an Alembic migration environment. It's used to prevent migration code
    from running when this module is imported for other purposes (e.g.,
    during testing or when importing models).

    The detection works by checking for the presence of the '_proxy' attribute
    on the alembic.context object. This attribute is set internally by Alembic
    when it loads and executes the env.py file during migration operations.

    Returns:
        bool: True if running under Alembic CLI (e.g., during 'alembic upgrade',
            'alembic downgrade', etc.), False if imported normally by Python
            code or during testing.

    Examples:
        >>> # Normal import context (no _proxy attribute)
        >>> import types
        >>> fake_context = types.SimpleNamespace()
        >>> import mcpgateway.alembic.env as env_module
        >>> original_context = env_module.context
        >>> env_module.context = fake_context
        >>> env_module._inside_alembic()
        False

        >>> # Simulated Alembic context (with _proxy attribute)
        >>> fake_context._proxy = True
        >>> env_module._inside_alembic()
        True

        >>> # Restore original context
        >>> env_module.context = original_context

    Note:
        This guard is crucial to prevent the migration execution code at the
        bottom of this module from running during normal imports. Without it,
        importing this module would attempt to run migrations every time.
    """
    return getattr(context, "_proxy", None) is not None


config.set_main_option("script_location", str(files("mcpgateway").joinpath("alembic")))

# Only apply alembic.ini logging when root has no handlers (standalone CLI).
# Skip when imported from the gateway lifespan to avoid fileConfig() resetting
# root handlers/level (disable_existing_loggers does not protect root).
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(
        config.config_file_name,
        disable_existing_loggers=False,
    )

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Escape '%' characters in URL to avoid configparser interpolation errors
# (e.g., URL-encoded passwords like %40 for '@')
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("%", "%%"),
)


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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    connection = config.attributes.get("connection")

    if connection is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()

    else:
        # Alembic already has a connection (e.g., in tests)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if _inside_alembic():
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
