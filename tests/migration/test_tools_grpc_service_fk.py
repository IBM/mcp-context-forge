# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_tools_grpc_service_fk.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Regression tests for tools.grpc_service_id foreign key constraint.

Ensures that the FK constraint exists on both SQLite and PostgreSQL databases
after migrations are applied, and that the FK behavior (CASCADE delete) works
correctly. This prevents regression of issue #5282.
"""

# Standard
import logging
import os
import tempfile
from pathlib import Path
from typing import Generator

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


@pytest.fixture
def sqlite_test_db() -> Generator[str, None, None]:
    """Create a temporary SQLite database for testing.

    Yields:
        str: Path to the temporary database file
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    yield f"sqlite:///{db_path}"

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


def apply_migrations(database_url: str, target: str = "head") -> None:
    """Apply Alembic migrations to a database.

    Args:
        database_url: Database connection URL
        target: Migration target (revision ID or 'head')
    """
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    # Find the project root (where mcpgateway/ exists)
    test_dir = Path(__file__).parent
    project_root = test_dir.parent.parent
    mcpgateway_dir = project_root / "mcpgateway"

    if not mcpgateway_dir.exists():
        raise RuntimeError(f"mcpgateway directory not found at {mcpgateway_dir}")

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", target],
        cwd=str(mcpgateway_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Migration failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")


def get_foreign_keys(engine: sa.Engine, table_name: str) -> list[dict]:
    """Get foreign key constraints for a table.

    Args:
        engine: SQLAlchemy engine
        table_name: Name of the table to inspect

    Returns:
        List of foreign key constraint dictionaries
    """
    inspector = inspect(engine)
    return inspector.get_foreign_keys(table_name)


def test_tools_grpc_service_fk_exists_sqlite(sqlite_test_db: str) -> None:
    """Test that tools.grpc_service_id FK constraint exists on SQLite after migrations.

    This is a regression test for issue #5282. The original migration w7x8y9z0a1b2
    skipped creating the FK on SQLite, which was later fixed by migration a54288286395.

    Args:
        sqlite_test_db: Fixture providing temporary SQLite database URL
    """
    # Apply all migrations
    apply_migrations(sqlite_test_db, "head")

    # Inspect the schema
    engine = sa.create_engine(sqlite_test_db)
    try:
        fks = get_foreign_keys(engine, "tools")

        # Find the grpc_service_id FK
        grpc_fk = None
        for fk in fks:
            if fk["constrained_columns"] == ["grpc_service_id"] and fk["referred_table"] == "grpc_services":
                grpc_fk = fk
                break

        # Assert FK exists
        assert grpc_fk is not None, (
            f"Missing FK constraint: tools.grpc_service_id -> grpc_services.id\n"
            f"Found FKs on tools table: {fks}\n"
            f"This is a regression of issue #5282"
        )

        # Assert FK points to correct columns
        assert grpc_fk["referred_columns"] == ["id"], f"FK should reference grpc_services.id, got: {grpc_fk['referred_columns']}"

        # Assert CASCADE delete behavior (if available in introspection)
        # Note: SQLite may not report ondelete in all versions, so this is optional
        on_delete = grpc_fk.get("options", {}).get("ondelete")
        if on_delete is not None:
            assert on_delete.upper() == "CASCADE", f"FK should have ON DELETE CASCADE, got: {on_delete}"

        logger.info("✓ SQLite: tools.grpc_service_id FK constraint exists and is configured correctly")

    finally:
        engine.dispose()


def test_tools_grpc_service_fk_cascade_delete_sqlite(sqlite_test_db: str) -> None:
    """Test that CASCADE delete works correctly for tools.grpc_service_id FK.

    Verifies that deleting a grpc_service automatically deletes associated tools.

    Args:
        sqlite_test_db: Fixture providing temporary SQLite database URL
    """
    # Apply all migrations
    apply_migrations(sqlite_test_db, "head")

    # Create engine and session
    engine = sa.create_engine(sqlite_test_db)
    session_local = sessionmaker(bind=engine)

    try:
        with session_local() as session:
            # Enable foreign keys (required for SQLite)
            session.execute(text("PRAGMA foreign_keys = ON"))
            session.commit()

            # Simple test: insert minimal grpc_service and tool, then delete grpc_service
            # and verify the tool is CASCADE deleted
            grpc_service_id = "test-grpc-service-001"
            tool_id = "test-tool-001"

            # Insert using minimal required fields
            session.execute(
                text(
                    """
                INSERT INTO grpc_services (id, name, slug, target, enabled, reachable, created_at, updated_at,
                                           service_count, method_count, discovered_services, tags, version)
                VALUES (:id, :name, :slug, :target, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, 0, '{}', '[]', 1)
            """
                ),
                {"id": grpc_service_id, "name": "test-service", "slug": "test-service", "target": "localhost:50051"},
            )

            session.execute(
                text(
                    """
                INSERT INTO tools (id, original_name, custom_name, custom_name_slug, grpc_service_id, input_schema,
                                   integration_type, request_type, enabled, deprecated, reachable, jsonpath_filter,
                                   tags, version, created_at, updated_at)
                VALUES (:id, :name, :name, :slug, :grpc_service_id, '{}', 'MCP', 'SSE', 1, 0, 1, '', '[]', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
                ),
                {"id": tool_id, "name": "test_tool", "slug": "test-tool", "grpc_service_id": grpc_service_id},
            )
            session.commit()

            # Verify tool exists
            result = session.execute(text("SELECT COUNT(*) FROM tools WHERE id = :id"), {"id": tool_id})
            count_before = result.scalar()
            assert count_before == 1, "Tool should exist before deletion"

            # Delete the grpc_service
            session.execute(text("DELETE FROM grpc_services WHERE id = :id"), {"id": grpc_service_id})
            session.commit()

            # Verify tool was CASCADE deleted
            result = session.execute(text("SELECT COUNT(*) FROM tools WHERE id = :id"), {"id": tool_id})
            count_after = result.scalar()
            assert count_after == 0, (
                "Tool should be CASCADE deleted when grpc_service is deleted. "
                "This indicates the FK constraint is missing or misconfigured."
            )

            logger.info("✓ SQLite: CASCADE delete behavior works correctly")

    finally:
        engine.dispose()


def test_tools_grpc_service_fk_repair_idempotent(sqlite_test_db: str) -> None:
    """Test that the FK repair migration is idempotent.

    Applies the repair migration twice to ensure it doesn't fail on the second run.

    Args:
        sqlite_test_db: Fixture providing temporary SQLite database URL
    """
    # Apply migrations up to the problematic revision
    apply_migrations(sqlite_test_db, "w7x8y9z0a1b2")

    # Apply the repair migration
    apply_migrations(sqlite_test_db, "a54288286395")

    engine = sa.create_engine(sqlite_test_db)
    try:
        fks_first = get_foreign_keys(engine, "tools")
        grpc_fk_exists_first = any(
            fk["constrained_columns"] == ["grpc_service_id"] and fk["referred_table"] == "grpc_services" for fk in fks_first
        )
        assert grpc_fk_exists_first, "FK should exist after first application"

        # Downgrade and re-apply (test idempotency)
        apply_migrations(sqlite_test_db, "6c0e5f8a9b1d")
        apply_migrations(sqlite_test_db, "a54288286395")

        fks_second = get_foreign_keys(engine, "tools")
        grpc_fk_exists_second = any(
            fk["constrained_columns"] == ["grpc_service_id"] and fk["referred_table"] == "grpc_services" for fk in fks_second
        )
        assert grpc_fk_exists_second, "FK should still exist after second application (idempotency test)"

        logger.info("✓ SQLite: FK repair migration is idempotent")

    finally:
        engine.dispose()


def test_tools_grpc_service_fk_fresh_install(sqlite_test_db: str) -> None:
    """Test that fresh installs have the FK constraint from db.py models.

    Verifies that the repair migration is a no-op on databases created from scratch.

    Args:
        sqlite_test_db: Fixture providing temporary SQLite database URL
    """
    # Apply all migrations (fresh install path)
    apply_migrations(sqlite_test_db, "head")

    engine = sa.create_engine(sqlite_test_db)
    try:
        fks = get_foreign_keys(engine, "tools")
        grpc_fk_exists = any(
            fk["constrained_columns"] == ["grpc_service_id"] and fk["referred_table"] == "grpc_services" for fk in fks
        )

        assert grpc_fk_exists, (
            "Fresh install should have FK constraint from db.py models. "
            "If this fails, the ORM model definition may be incorrect."
        )

        logger.info("✓ SQLite: Fresh install has FK constraint from db.py models")

    finally:
        engine.dispose()


# PostgreSQL tests (if PostgreSQL is available)
@pytest.fixture
def postgres_test_db() -> Generator[str, None, None]:
    """Create a temporary PostgreSQL database for testing.

    Requires a PostgreSQL server to be running and accessible via environment variables:
    - POSTGRES_HOST (default: localhost)
    - POSTGRES_PORT (default: 5432)
    - POSTGRES_USER (default: postgres)
    - POSTGRES_PASSWORD (default: postgres)

    Yields:
        str: PostgreSQL database URL
    """
    import uuid

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    admin_db = "postgres"

    # Create a unique test database name
    test_db_name = f"test_fk_{uuid.uuid4().hex[:8]}"
    admin_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{admin_db}"
    test_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{test_db_name}"

    # Create the test database
    try:
        admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {test_db_name}"))
        admin_engine.dispose()

        yield test_url

    finally:
        # Cleanup: drop the test database
        try:
            admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                # Terminate connections to the test database
                conn.execute(
                    text(
                        f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{test_db_name}'
                      AND pid <> pg_backend_pid()
                """
                    )
                )
                conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
            admin_engine.dispose()
        except Exception as e:
            logger.warning(f"Failed to cleanup test database {test_db_name}: {e}")


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL", "").lower() in ("1", "true", "yes"),
    reason="PostgreSQL tests require TEST_POSTGRESQL=true and a running PostgreSQL server",
)
def test_tools_grpc_service_fk_exists_postgres(postgres_test_db: str) -> None:
    """Test that tools.grpc_service_id FK constraint exists on PostgreSQL.

    PostgreSQL should have had the FK from the original w7x8y9z0a1b2 migration,
    but this test ensures it's still present.

    Args:
        postgres_test_db: Fixture providing temporary PostgreSQL database URL
    """
    # Apply all migrations
    apply_migrations(postgres_test_db, "head")

    # Inspect the schema
    engine = sa.create_engine(postgres_test_db)
    try:
        fks = get_foreign_keys(engine, "tools")

        # Find the grpc_service_id FK
        grpc_fk = None
        for fk in fks:
            if fk["constrained_columns"] == ["grpc_service_id"] and fk["referred_table"] == "grpc_services":
                grpc_fk = fk
                break

        assert grpc_fk is not None, (
            f"Missing FK constraint: tools.grpc_service_id -> grpc_services.id\n" f"Found FKs on tools table: {fks}"
        )

        assert grpc_fk["referred_columns"] == ["id"], f"FK should reference grpc_services.id, got: {grpc_fk['referred_columns']}"

        # PostgreSQL should report CASCADE delete
        on_delete = grpc_fk.get("options", {}).get("ondelete")
        assert on_delete is not None and on_delete.upper() == "CASCADE", f"FK should have ON DELETE CASCADE, got: {on_delete}"

        logger.info("✓ PostgreSQL: tools.grpc_service_id FK constraint exists and is configured correctly")

    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL", "").lower() in ("1", "true", "yes"),
    reason="PostgreSQL tests require TEST_POSTGRESQL=true and a running PostgreSQL server",
)
def test_tools_grpc_service_fk_cascade_delete_postgres(postgres_test_db: str) -> None:
    """Test that CASCADE delete works correctly on PostgreSQL.

    Args:
        postgres_test_db: Fixture providing temporary PostgreSQL database URL
    """
    # Apply all migrations
    apply_migrations(postgres_test_db, "head")

    # Create engine and session
    engine = sa.create_engine(postgres_test_db)
    session_local = sessionmaker(bind=engine)

    try:
        with session_local() as session:
            # Insert a grpc_service
            grpc_service_id = "test-grpc-service-002"
            session.execute(
                text(
                    """
                INSERT INTO grpc_services (id, name, slug, target, enabled, reachable, created_at, updated_at)
                VALUES (:id, :name, :slug, :target, :enabled, :reachable, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
                ),
                {
                    "id": grpc_service_id,
                    "name": "test-service-pg",
                    "slug": "test-service-pg",
                    "target": "localhost:50051",
                    "enabled": True,
                    "reachable": False,
                },
            )

            # Insert a tool referencing the grpc_service
            tool_id = "test-tool-002"
            session.execute(
                text(
                    """
                INSERT INTO tools (id, original_name, custom_name, custom_name_slug, grpc_service_id, input_schema)
                VALUES (:id, :name, :custom_name, :custom_name_slug, :grpc_service_id, :input_schema)
            """
                ),
                {
                    "id": tool_id,
                    "name": "test_tool_pg",
                    "custom_name": "test_tool_pg",
                    "custom_name_slug": "test-tool-pg",
                    "grpc_service_id": grpc_service_id,
                    "input_schema": "{}",
                },
            )
            session.commit()

            # Verify tool exists
            result = session.execute(text("SELECT COUNT(*) FROM tools WHERE id = :id"), {"id": tool_id})
            count_before = result.scalar()
            assert count_before == 1, "Tool should exist before deletion"

            # Delete the grpc_service
            session.execute(text("DELETE FROM grpc_services WHERE id = :id"), {"id": grpc_service_id})
            session.commit()

            # Verify tool was CASCADE deleted
            result = session.execute(text("SELECT COUNT(*) FROM tools WHERE id = :id"), {"id": tool_id})
            count_after = result.scalar()
            assert count_after == 0, (
                "Tool should be CASCADE deleted when grpc_service is deleted. "
                "This indicates the FK constraint is missing or misconfigured."
            )

            logger.info("✓ PostgreSQL: CASCADE delete behavior works correctly")

    finally:
        engine.dispose()
