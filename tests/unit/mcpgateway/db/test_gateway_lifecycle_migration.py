# -*- coding: utf-8 -*-
"""Tests for gateway lifecycle Alembic migration."""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from mcpgateway.db import Gateway as DbGateway

MODULE_NAME = "mcpgateway.alembic.versions.6c0e5f8a9b1d_add_gateway_lifecycle_fields"
REVISION = "6c0e5f8a9b1d"  # pragma: allowlist secret
DOWN_REVISION = "0a089912b5f0"  # pragma: allowlist secret
GATEWAY_TABLE = "gateways"
LIFECYCLE_COLUMNS = {
    "status",
    "status_message",
    "registration_attempts",
    "next_retry_at",
    "last_error",
}
LIFECYCLE_INDEX = "idx_gateways_status_next_retry_at"
CLAIM_COLUMNS = {
    "lifecycle_claimed_by",
    "lifecycle_claimed_at",
    "lifecycle_claim_expires_at",
}
CLAIM_INDEX = "idx_gateways_lifecycle_claim"


def _migration_context(conn):
    """Create a migration context for a connection."""
    return MigrationContext.configure(conn, opts={"as_sql": False})


def _create_gateway_table(conn) -> None:
    """Create a minimal pre-migration gateways table."""
    conn.execute(sa.text("""
        CREATE TABLE gateways (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL,
            url VARCHAR(767) NOT NULL
        )
    """))


def _column_names(conn) -> set[str]:
    """Return current gateway column names."""
    return {column["name"] for column in sa.inspect(conn).get_columns(GATEWAY_TABLE)}


def _index_names(conn) -> set[str]:
    """Return current gateway index names."""
    return {index["name"] for index in sa.inspect(conn).get_indexes(GATEWAY_TABLE)}


class TestGatewayLifecycleMigrationStructure:
    """Verify migration module metadata."""

    def test_migration_module_imports(self):
        """Migration module imports."""
        assert importlib.import_module(MODULE_NAME) is not None

    def test_migration_revision_id(self):
        """Revision ID matches expected value."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        """Down revision points at previous head."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_migration_functions_have_no_parameters(self):
        """upgrade() and downgrade() accept no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0

    def test_gateway_orm_metadata_includes_claim_index(self):
        """ORM table metadata matches claim index created by migration."""
        index_columns = {index.name: tuple(column.name for column in index.columns) for index in DbGateway.__table__.indexes}
        assert index_columns[CLAIM_INDEX] == ("status", "next_retry_at", "lifecycle_claim_expires_at")


class TestGatewayLifecycleMigrationDefaults:
    """Verify lifecycle default/backfill behavior."""

    def test_upgrade_backfills_existing_gateways_and_sets_insert_defaults(self):
        """Existing and newly inserted gateways receive active lifecycle defaults."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_gateway_table(conn)
                conn.execute(
                    sa.text("INSERT INTO gateways (id, name, slug, url) VALUES (:id, :name, :slug, :url)"),
                    {"id": "gw-existing", "name": "Existing", "slug": "existing", "url": "https://example.com"},
                )
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert LIFECYCLE_COLUMNS <= _column_names(conn)
                assert CLAIM_COLUMNS <= _column_names(conn)
                assert LIFECYCLE_INDEX in _index_names(conn)
                assert CLAIM_INDEX in _index_names(conn)

                existing = conn.execute(sa.text("SELECT status, status_message, registration_attempts, next_retry_at, last_error FROM gateways WHERE id = 'gw-existing'")).one()
                assert existing == ("active", None, 0, None, None)
                existing_claim = conn.execute(
                    sa.text("SELECT lifecycle_claimed_by, lifecycle_claimed_at, lifecycle_claim_expires_at FROM gateways WHERE id = 'gw-existing'")
                ).one()
                assert existing_claim == (None, None, None)

                conn.execute(
                    sa.text("INSERT INTO gateways (id, name, slug, url) VALUES (:id, :name, :slug, :url)"),
                    {"id": "gw-new", "name": "New", "slug": "new", "url": "https://new.example.com"},
                )
                inserted = conn.execute(sa.text("SELECT status, registration_attempts FROM gateways WHERE id = 'gw-new'")).one()
                assert inserted == ("active", 0)
        finally:
            engine.dispose()


class TestGatewayLifecycleClaimMigrationDefaults:
    """Verify lifecycle claim default/backfill behavior."""

    def test_upgrade_adds_nullable_claim_columns_and_index(self):
        """Existing gateways backfill with no active lifecycle claim from same migration."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_gateway_table(conn)
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN next_retry_at DATETIME"))
                conn.execute(
                    sa.text("INSERT INTO gateways (id, name, slug, url) VALUES (:id, :name, :slug, :url)"),
                    {"id": "gw-existing", "name": "Existing", "slug": "existing", "url": "https://example.com"},
                )
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert CLAIM_COLUMNS <= _column_names(conn)
                assert CLAIM_INDEX in _index_names(conn)
                existing = conn.execute(
                    sa.text("SELECT lifecycle_claimed_by, lifecycle_claimed_at, lifecycle_claim_expires_at FROM gateways WHERE id = 'gw-existing'")
                ).one()
                assert existing == (None, None, None)
        finally:
            engine.dispose()

    def test_claim_downgrade_removes_columns_and_index(self):
        """downgrade() removes lifecycle claim fields and index from same migration."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_gateway_table(conn)
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN next_retry_at DATETIME"))
                conn.commit()
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()
                    module.downgrade()

                assert CLAIM_COLUMNS.isdisjoint(_column_names(conn))
                assert CLAIM_INDEX not in _index_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent_when_columns_already_exist(self):
        """upgrade() is a no-op when lifecycle fields already exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_gateway_table(conn)
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN status_message TEXT"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN registration_attempts INTEGER NOT NULL DEFAULT 0"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN next_retry_at DATETIME"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN last_error TEXT"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN lifecycle_claimed_by VARCHAR(64)"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN lifecycle_claimed_at DATETIME"))
                conn.execute(sa.text("ALTER TABLE gateways ADD COLUMN lifecycle_claim_expires_at DATETIME"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert LIFECYCLE_COLUMNS <= _column_names(conn)
                assert CLAIM_COLUMNS <= _column_names(conn)
                assert LIFECYCLE_INDEX in _index_names(conn)
                assert CLAIM_INDEX in _index_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_removes_lifecycle_columns_and_index(self):
        """downgrade() removes lifecycle fields and polling index."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_gateway_table(conn)
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()
                    module.downgrade()

                assert LIFECYCLE_COLUMNS.isdisjoint(_column_names(conn))
                assert CLAIM_COLUMNS.isdisjoint(_column_names(conn))
                assert LIFECYCLE_INDEX not in _index_names(conn)
                assert CLAIM_INDEX not in _index_names(conn)
        finally:
            engine.dispose()
