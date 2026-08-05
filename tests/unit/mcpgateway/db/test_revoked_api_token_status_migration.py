# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_revoked_api_token_status_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for migration e5136a7c9d01.
"""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

MODULE_NAME = "mcpgateway.alembic.versions.e5136a7c9d01_repair_revoked_api_token_status"


def _run_upgrade(connection) -> None:
    context = MigrationContext.configure(connection, opts={"as_sql": False})
    with Operations.context(context):
        importlib.import_module(MODULE_NAME).upgrade()


def test_repair_statement_uses_postgresql_booleans():
    """PostgreSQL SQL must not compare BOOLEAN columns with integer literals."""
    migration = importlib.import_module(MODULE_NAME)

    sql = str(
        migration._repair_statement().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "SET is_active=false" in sql
    assert "is_active IS true" in sql
    assert "is_active = 0" not in sql
    assert "is_active = 1" not in sql


def test_upgrade_repairs_only_revoked_active_tokens():
    """Existing revoked rows become inactive without changing valid tokens."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE email_api_tokens (jti VARCHAR PRIMARY KEY, is_active BOOLEAN NOT NULL)"))
            connection.execute(sa.text("CREATE TABLE token_revocations (jti VARCHAR PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO email_api_tokens (jti, is_active) VALUES ('revoked-active', true), ('valid-active', true), ('revoked-inactive', false)"))
            connection.execute(sa.text("INSERT INTO token_revocations (jti) VALUES ('revoked-active'), ('revoked-inactive')"))

            _run_upgrade(connection)

            states = dict(connection.execute(sa.text("SELECT jti, is_active FROM email_api_tokens")).all())
            assert states == {"revoked-active": 0, "valid-active": 1, "revoked-inactive": 0}
    finally:
        engine.dispose()


def test_upgrade_skips_missing_tables():
    """Partial schemas remain safe."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            _run_upgrade(connection)
            connection.execute(sa.text("CREATE TABLE email_api_tokens (jti VARCHAR PRIMARY KEY, is_active BOOLEAN NOT NULL)"))
            _run_upgrade(connection)
    finally:
        engine.dispose()


def test_upgrade_is_idempotent():
    """Repeated upgrades leave repaired and valid rows unchanged."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE email_api_tokens (jti VARCHAR PRIMARY KEY, is_active BOOLEAN NOT NULL)"))
            connection.execute(sa.text("CREATE TABLE token_revocations (jti VARCHAR PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO email_api_tokens (jti, is_active) VALUES ('revoked', 1), ('valid', 1)"))
            connection.execute(sa.text("INSERT INTO token_revocations (jti) VALUES ('revoked')"))

            _run_upgrade(connection)
            _run_upgrade(connection)

            states = dict(connection.execute(sa.text("SELECT jti, is_active FROM email_api_tokens")).all())
            assert states == {"revoked": 0, "valid": 1}
    finally:
        engine.dispose()
