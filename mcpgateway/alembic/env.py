# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/env.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

Alembic environment configuration for database migrations.
This module configures the Alembic migration environment for the MCP Gateway
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

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(
        config.config_file_name,
        disable_existing_loggers=False,
    )

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel

# MariaDB naming convention for shorter FK names
mariadb_naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


# MariaDB metadata modifications
def _modify_metadata_for_mariadb():
    """Force VARCHAR length and replace unsupported types for MariaDB."""
    # Third-Party
    from sqlalchemy import String, Text
    from sqlalchemy.dialects import postgresql

    for table in Base.metadata.tables.values():
        for column in table.columns:
            # UUID → String(36)
            if isinstance(column.type, postgresql.UUID):
                column.type = String(36)
            # Bare String without length → String(255)
            elif isinstance(column.type, String) and column.type.length is None:
                column.type = String(255)
            # JSONB → Text (simple fallback)
            elif hasattr(column.type, "__class__") and "JSONB" in str(column.type.__class__):
                column.type = Text
            # ARRAY → Text
            elif hasattr(column.type, "__class__") and "ARRAY" in str(column.type.__class__):
                column.type = Text


# MariaDB modifications will be applied when needed during table creation
# Do not apply automatically during import to avoid SQLAlchemy column management issues

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

    def configure_for_mariadb(connection):
        """
        Apply MariaDB-specific autogenerate rules.

        Args:
            connection: SQLAlchemy Connection object.
                The active database connection being used by Alembic during
                autogenerate. Used to apply MariaDB-specific type replacements
                and rules.
        """
        # Third-Party
        from sqlalchemy import String, VARCHAR
        from sqlalchemy.dialects import postgresql

        # Apply naming convention
        target_metadata.naming_convention = mariadb_naming_convention

        def render_item(type_, obj, _autogen_context):
            """Render SQLAlchemy types for MariaDB compatibility.

            Args:
                type_: The SQLAlchemy type being rendered.
                obj: The schema object (column, constraint, etc.).
                _autogen_context: Alembic autogenerate context (unused).

            Returns:
                str or False: String representation of the type for MariaDB,
                    or False to use default rendering.
            """
            # UUID → String(36)
            if isinstance(type_, postgresql.UUID):
                return "String(36)"

            # JSONB → JSON (MariaDB ≥ 10.4) else TEXT
            if "JSONB" in str(type_.__class__):
                version = connection.engine.dialect.server_version_info
                return "JSON" if version >= (10, 4) else "Text"

            # ARRAY → TEXT (comma-separated values)
            if "ARRAY" in str(type_.__class__):
                return "Text"

            # VARCHAR with no length → 255
            if isinstance(type_, (String, VARCHAR)):
                return f"String({type_.length or 255})"

            return False

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            # prevent Alembic from generating tables that already exist
            include_object=lambda obj, name, type_, _reflected, _compare_to: not (type_ == "table" and connection.dialect.has_table(connection, name)),
        )

    # ----------------------------------------------------------------------

    connection = config.attributes.get("connection")

    if connection is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            if connection.engine.dialect.name == "mariadb":
                configure_for_mariadb(connection)
            else:
                context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()

    else:
        # Alembic already has a connection (e.g., in tests)
        if connection.engine.dialect.name == "mariadb":
            configure_for_mariadb(connection)
        else:
            context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if _inside_alembic():
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
