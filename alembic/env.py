# -*- coding: utf-8 -*-
"""Alembic migration environment wired to mcpgateway models & settings."""

from __future__ import with_statement

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ✨  Import the project's SQLAlchemy metadata & runtime DB URL
from mcpgateway.db import Base
from mcpgateway.config import settings

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

# Configure Python logging via alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# Metadata for "autogenerate"
target_metadata = Base.metadata


def _get_url() -> str:
    """Return the database URL from project settings."""
    return settings.database_url


# ---------------------------------------------------------------------------
# Offline migrations
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations without a DB connection (generates SQL scripts)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,          # detect column type changes
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
