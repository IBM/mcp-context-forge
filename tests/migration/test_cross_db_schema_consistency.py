# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_cross_db_schema_consistency.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Cross-database schema consistency test.

Runs the current target image against SQLite and PostgreSQL, applies
Alembic migrations to head, introspects both schemas via SQLAlchemy,
and asserts that all tables, columns, primary keys, foreign keys, and
unique constraints are identical — modulo a well-documented set of
engine-specific type equivalences.
"""

# Standard
import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional, Set

# Third-Party
import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_IMAGE = os.environ.get("UPGRADE_TARGET_IMAGE", "mcpgateway/mcpgateway:latest")

# SQLAlchemy introspection script executed *inside* the running container via
# `docker exec`.  It emits one JSON object to stdout.
_INTROSPECT_SCRIPT = r"""
import json, sys
import sqlalchemy as sa

db_url = sys.argv[1]
engine = sa.create_engine(db_url, echo=False)
inspector = sa.inspect(engine)

schema: dict = {}
for table_name in sorted(inspector.get_table_names()):
    cols = {}
    for col in inspector.get_columns(table_name):
        raw = str(col["type"]).upper()
        # Strip precision/length: VARCHAR(256) -> VARCHAR
        import re
        raw = re.sub(r'\([^)]*\)', '', raw).strip()
        cols[col["name"]] = raw

    pk = sorted(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
    fks = sorted(
        [
            {
                "constrained_columns": sorted(fk["constrained_columns"]),
                "referred_table": fk["referred_table"],
                "referred_columns": sorted(fk["referred_columns"]),
            }
            for fk in inspector.get_foreign_keys(table_name)
        ],
        key=lambda x: str(x),
    )
    uqs = sorted(
        [sorted(u["column_names"]) for u in inspector.get_unique_constraints(table_name)]
    )
    schema[table_name] = {
        "columns": cols,
        "primary_key": pk,
        "foreign_keys": fks,
        "unique_constraints": uqs,
    }

print(json.dumps(schema))
engine.dispose()
"""

# ---------------------------------------------------------------------------
# Engine-specific type equivalences
# These are canonical differences between SQLite and PostgreSQL that do NOT
# represent schema drift — they are inherent to each engine's type system.
# ---------------------------------------------------------------------------

# Map each engine's concrete type to a canonical form for comparison.
_TYPE_CANON: Dict[str, str] = {
    # Integer family
    "INTEGER": "INTEGER",
    "INT": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    # Text family
    "TEXT": "TEXT",
    "VARCHAR": "TEXT",
    "CLOB": "TEXT",
    "CHAR": "TEXT",
    "CHARACTER VARYING": "TEXT",
    # Boolean family
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    # Datetime family
    "DATETIME": "DATETIME",
    "TIMESTAMP": "DATETIME",
    "TIMESTAMP WITHOUT TIME ZONE": "DATETIME",
    "TIMESTAMP WITH TIME ZONE": "DATETIME",
    # Float family
    "FLOAT": "FLOAT",
    "REAL": "FLOAT",
    "DOUBLE PRECISION": "FLOAT",
    "NUMERIC": "FLOAT",
    "DECIMAL": "FLOAT",
    # JSON family
    "JSON": "JSON",
    "JSONB": "JSON",
    # Binary
    "BLOB": "BLOB",
    "BYTEA": "BLOB",
    "VARBINARY": "BLOB",
}

# Tables that exist in one engine only due to engine-specific plumbing.
# Add entries here when a migration legitimately creates an engine-only table.
_ENGINE_ONLY_TABLES: Set[str] = set()

# alembic_version is always present — not interesting to diff.
_SKIP_TABLES: Set[str] = {"alembic_version"}


def _canon(raw_type: str) -> str:
    """Return the canonical type string for *raw_type*."""
    return _TYPE_CANON.get(raw_type.upper(), raw_type.upper())


def _normalise_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *raw* with types replaced by their canonical forms."""
    out: Dict[str, Any] = {}
    for table, info in raw.items():
        if table in _SKIP_TABLES:
            continue
        out[table] = {
            "columns": {col: _canon(typ) for col, typ in info["columns"].items()},
            "primary_key": info["primary_key"],
            "foreign_keys": info["foreign_keys"],
            "unique_constraints": info["unique_constraints"],
        }
    return out


# ---------------------------------------------------------------------------
# Container helpers
# ---------------------------------------------------------------------------


def _run(args, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess, raise on non-zero exit."""
    result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(a) for a in args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _wait_health(url: str, timeout: int = 120) -> None:
    """Poll *url* until it returns HTTP 200 or *timeout* seconds elapse."""
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"Health check timed out: {url}")


def _wait_pg_ready(container: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "mcp"],
            capture_output=True,
            check=False,
        )
        if r.returncode == 0:
            return
        time.sleep(1)
    raise TimeoutError(f"PostgreSQL not ready in container {container}")


def _introspect_in_container(container: str, db_url: str) -> Dict[str, Any]:
    """Exec the introspection script inside *container* and return parsed JSON."""
    result = subprocess.run(
        [
            "docker", "exec", container,
            "/app/.venv/bin/python3", "-c",
            _INTROSPECT_SCRIPT, db_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Introspection failed in {container}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Pytest fixtures (module-scoped so containers are shared within the module)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _sqlite_schema(tmp_path_factory, container_runtime):
    """Boot TARGET_IMAGE with SQLite, run migrations, return raw schema dict."""
    tmp = tmp_path_factory.mktemp("sqlite_schema")
    tmp.chmod(0o777)
    db_file = tmp / "mcp-schema-test.db"
    db_file.touch()
    db_file.chmod(0o666)

    container: Optional[str] = None
    try:
        result = _run([
            "docker", "run", "-d",
            "--name", f"schema-test-sqlite-{int(time.time())}",
            "-p", "0:4444",
            "-e", f"DATABASE_URL=sqlite:////app/data/{db_file.name}",
            "-e", "AUTH_REQUIRED=false",
            "-e", "CACHE_TYPE=memory",
            "-e", "HOST=0.0.0.0",
            "-e", "PORT=4444",
            "-e", "MCPGATEWAY_UI_ENABLED=false",
            "-e", "MCPGATEWAY_ADMIN_API_ENABLED=true",
            "-e", "LOG_LEVEL=INFO",
            "-v", f"{tmp}:/app/data",
            TARGET_IMAGE,
        ])
        container = result.stdout.strip()

        # Discover the mapped port
        port_result = _run(["docker", "port", container, "4444/tcp"])
        host_port = port_result.stdout.strip().split(":")[-1]

        _wait_health(f"http://127.0.0.1:{host_port}/health")

        db_url = f"sqlite:////app/data/{db_file.name}"
        schema = _introspect_in_container(container, db_url)
        logger.info(f"SQLite schema introspected: {len(schema)} tables")
        return schema

    finally:
        if container:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


@pytest.fixture(scope="module")
def _postgres_schema(tmp_path_factory, container_runtime):
    """Boot TARGET_IMAGE with PostgreSQL, run migrations, return raw schema dict."""
    network: Optional[str] = None
    pg_container: Optional[str] = None
    gw_container: Optional[str] = None

    run_id = int(time.time())
    network = f"schema-test-net-{run_id}"
    pg_container_name = f"schema-test-pg-{run_id}"
    gw_container_name = f"schema-test-gw-{run_id}"

    try:
        _run(["docker", "network", "create", network])

        _run([
            "docker", "run", "-d",
            "--name", pg_container_name,
            "--network", network,
            "-e", "POSTGRES_USER=postgres",
            "-e", "POSTGRES_PASSWORD=schema-test-pw",
            "-e", "POSTGRES_DB=mcp",
            "postgres:18",
        ])
        pg_container = pg_container_name
        _wait_pg_ready(pg_container)

        db_url = f"postgresql+psycopg://postgres:schema-test-pw@{pg_container_name}:5432/mcp"  # pragma: allowlist secret

        result = _run([
            "docker", "run", "-d",
            "--name", gw_container_name,
            "--network", network,
            "-p", "0:4444",
            "-e", f"DATABASE_URL={db_url}",
            "-e", "AUTH_REQUIRED=false",
            "-e", "CACHE_TYPE=memory",
            "-e", "HOST=0.0.0.0",
            "-e", "PORT=4444",
            "-e", "MCPGATEWAY_UI_ENABLED=false",
            "-e", "MCPGATEWAY_ADMIN_API_ENABLED=true",
            "-e", "LOG_LEVEL=INFO",
            TARGET_IMAGE,
        ])
        gw_container = result.stdout.strip()

        port_result = _run(["docker", "port", gw_container, "4444/tcp"])
        host_port = port_result.stdout.strip().split(":")[-1]
        _wait_health(f"http://127.0.0.1:{host_port}/health")

        schema = _introspect_in_container(gw_container, db_url)
        logger.info(f"PostgreSQL schema introspected: {len(schema)} tables")
        return schema

    finally:
        for c in [gw_container, pg_container]:
            if c:
                subprocess.run(["docker", "rm", "-f", c], capture_output=True, check=False)
        if network:
            subprocess.run(["docker", "network", "rm", network], capture_output=True, check=False)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestCrossDBSchemaConsistency:
    """Verify the same migration head produces equivalent schemas on both engines.

    Starts the target image twice — once with SQLite, once with PostgreSQL —
    applies Alembic migrations to head in each case, then compares the
    resulting schemas after normalising engine-specific type differences.
    """

    def test_same_tables_exist(self, _sqlite_schema, _postgres_schema):
        """Both engines must produce the same set of table names."""
        sqlite_tables = set(_sqlite_schema) - _SKIP_TABLES - _ENGINE_ONLY_TABLES
        pg_tables = set(_postgres_schema) - _SKIP_TABLES - _ENGINE_ONLY_TABLES

        only_sqlite = sqlite_tables - pg_tables
        only_pg = pg_tables - sqlite_tables

        assert not only_sqlite, (
            f"Tables present in SQLite but not PostgreSQL: {sorted(only_sqlite)}"
        )
        assert not only_pg, (
            f"Tables present in PostgreSQL but not SQLite: {sorted(only_pg)}"
        )
        logger.info(f"✅ Both engines have the same {len(sqlite_tables)} tables")

    def test_column_names_match(self, _sqlite_schema, _postgres_schema):
        """Each table must have the same column names on both engines."""
        sqlite_norm = _normalise_schema(_sqlite_schema)
        pg_norm = _normalise_schema(_postgres_schema)

        mismatches: Dict[str, Any] = {}
        for table in sorted(sqlite_norm):
            if table not in pg_norm:
                continue
            sq_cols = set(sqlite_norm[table]["columns"])
            pg_cols = set(pg_norm[table]["columns"])
            if sq_cols != pg_cols:
                mismatches[table] = {
                    "only_sqlite": sorted(sq_cols - pg_cols),
                    "only_postgres": sorted(pg_cols - sq_cols),
                }

        assert not mismatches, (
            "Column name mismatches between engines:\n"
            + json.dumps(mismatches, indent=2)
        )
        logger.info("✅ Column names match on all tables")

    def test_column_types_match(self, _sqlite_schema, _postgres_schema):
        """Column types must be equivalent (after canonical normalisation)."""
        sqlite_norm = _normalise_schema(_sqlite_schema)
        pg_norm = _normalise_schema(_postgres_schema)

        mismatches: Dict[str, Any] = {}
        for table in sorted(sqlite_norm):
            if table not in pg_norm:
                continue
            sq_cols = sqlite_norm[table]["columns"]
            pg_cols = pg_norm[table]["columns"]
            col_diff = {
                col: {"sqlite": sq_cols[col], "postgres": pg_cols[col]}
                for col in sq_cols
                if col in pg_cols and sq_cols[col] != pg_cols[col]
            }
            if col_diff:
                mismatches[table] = col_diff

        assert not mismatches, (
            "Column type mismatches (after normalisation) between engines:\n"
            + json.dumps(mismatches, indent=2)
            + "\n\nIf this is a known engine-specific difference, add a mapping to _TYPE_CANON."
        )
        logger.info("✅ Column types are equivalent across both engines")

    def test_primary_keys_match(self, _sqlite_schema, _postgres_schema):
        """Primary key columns must be identical on both engines."""
        sqlite_norm = _normalise_schema(_sqlite_schema)
        pg_norm = _normalise_schema(_postgres_schema)

        mismatches: Dict[str, Any] = {}
        for table in sorted(sqlite_norm):
            if table not in pg_norm:
                continue
            if sqlite_norm[table]["primary_key"] != pg_norm[table]["primary_key"]:
                mismatches[table] = {
                    "sqlite": sqlite_norm[table]["primary_key"],
                    "postgres": pg_norm[table]["primary_key"],
                }

        assert not mismatches, (
            "Primary key mismatches between engines:\n"
            + json.dumps(mismatches, indent=2)
        )
        logger.info("✅ Primary keys match on all tables")

    def test_foreign_keys_match(self, _sqlite_schema, _postgres_schema):
        """Foreign key relationships must be identical on both engines."""
        sqlite_norm = _normalise_schema(_sqlite_schema)
        pg_norm = _normalise_schema(_postgres_schema)

        mismatches: Dict[str, Any] = {}
        for table in sorted(sqlite_norm):
            if table not in pg_norm:
                continue
            if sqlite_norm[table]["foreign_keys"] != pg_norm[table]["foreign_keys"]:
                mismatches[table] = {
                    "sqlite": sqlite_norm[table]["foreign_keys"],
                    "postgres": pg_norm[table]["foreign_keys"],
                }

        assert not mismatches, (
            "Foreign key mismatches between engines:\n"
            + json.dumps(mismatches, indent=2)
        )
        logger.info("✅ Foreign keys match on all tables")
