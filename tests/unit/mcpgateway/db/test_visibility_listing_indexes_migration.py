# -*- coding: utf-8 -*-
"""Tests for visibility listing index migration."""

# Standard
import importlib
import os

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.8d0f7c2a9b31_add_visibility_listing_order_indexes"


def _postgres_url(test_db_url):
    """Return the configured Postgres URL, if this test run has one."""
    if os.environ.get("TEST_POSTGRES_URL"):
        return os.environ["TEST_POSTGRES_URL"]
    if test_db_url.startswith("postgresql"):
        return test_db_url
    return None


def _migration_context(conn):
    """Return an Alembic migration context bound to conn."""
    return MigrationContext.configure(conn, opts={"as_sql": False})


def _pg_engine(postgres_url):
    """Return a PostgreSQL engine for migration tests."""
    return sa.create_engine(postgres_url)


def _create_visibility_table(conn, table_name):
    """Create a minimal visibility table that satisfies migration preconditions."""
    conn.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
    conn.execute(sa.text("""
            CREATE TABLE {table_name} (
                id VARCHAR PRIMARY KEY,
                team_id VARCHAR,
                owner_email VARCHAR,
                visibility VARCHAR NOT NULL,
                enabled BOOLEAN NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
            """.format(table_name=table_name)))
    conn.commit()


def _drop_visibility_tables(conn, table_names):
    """Drop minimal visibility tables."""
    for table_name in table_names:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
    conn.commit()


def _index_name(table_name):
    """Return the migration index name for table_name."""
    return f"idx_{table_name}_private_owner_team_order"


def _index_names(conn, table_name):
    """Return indexes on table_name."""
    return {index["name"] for index in sa.inspect(conn).get_indexes(table_name)}


def _index_definition(conn, table_name):
    """Return the PostgreSQL index definition for the migration index."""
    row = conn.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE tablename = :table_name AND indexname = :name"),
        {"table_name": table_name, "name": _index_name(table_name)},
    ).one_or_none()
    return row[0] if row else None


def test_visibility_listing_index_upgrade_is_idempotent_and_downgrades(test_db_url):
    """Migration creates private owner/team indexes once and drops them."""
    postgres_url = _postgres_url(test_db_url)
    if not postgres_url:
        pytest.skip("PostgreSQL test database not configured")

    module = importlib.import_module(MODULE_NAME)
    table_names = module.VISIBILITY_TABLES
    engine = _pg_engine(postgres_url)
    try:
        with engine.connect() as conn:
            for table_name in table_names:
                _create_visibility_table(conn, table_name)

            ctx = _migration_context(conn)
            with Operations.context(ctx):
                module.upgrade()
                module.upgrade()

            for table_name in table_names:
                assert _index_name(table_name) in _index_names(conn, table_name)
                index_definition = _index_definition(conn, table_name)
                assert "team_id" in index_definition
                assert "owner_email" in index_definition
                assert "enabled" in index_definition
                assert "visibility" in index_definition
                assert "private" in index_definition

            with Operations.context(ctx):
                module.downgrade()

            for table_name in table_names:
                assert _index_name(table_name) not in _index_names(conn, table_name)
    finally:
        with engine.connect() as conn:
            _drop_visibility_tables(conn, table_names)
        engine.dispose()
