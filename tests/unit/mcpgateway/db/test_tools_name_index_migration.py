# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_tools_name_index_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the non-unique tools.name index (issue #7044).
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

# First-Party
from mcpgateway.db import Base
from mcpgateway.db import Tool as DbTool

MODULE_NAME = "mcpgateway.alembic.versions.87e895734718_add_tools_name_index"
REVISION = "87e895734718"  # pragma: allowlist secret
DOWN_REVISION = "c7e91a2b4d60"  # pragma: allowlist secret
INDEX_NAME = "idx_tools_name"


@pytest.fixture
def migration():
    """Import the migration module under test."""
    return importlib.import_module(MODULE_NAME)


def _legacy_tools_table(conn) -> None:
    """Create a minimal pre-migration tools table holding duplicate names across teams."""
    conn.execute(sa.text("CREATE TABLE tools (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, team_id VARCHAR(36))"))
    conn.execute(sa.text("INSERT INTO tools VALUES ('1', 'search', 'team-a'), ('2', 'search', 'team-b'), ('3', 'fetch', NULL)"))


def _tools_indexes(conn) -> dict[str, dict]:
    """Return tools indexes keyed by name."""
    return {index["name"]: index for index in sa.inspect(conn).get_indexes("tools")}


def test_revision_chain(migration):
    """Migration follows the verified head."""
    assert migration.revision == REVISION
    assert migration.down_revision == DOWN_REVISION


def test_upgrade_creates_non_unique_index_and_keeps_duplicates(migration):
    """Upgrade adds a non-unique index, accepts existing duplicates, and is idempotent."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _legacy_tools_table(conn)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
        index = _tools_indexes(conn)[INDEX_NAME]
        assert index["column_names"] == ["name"]
        assert not index["unique"]
        # Same name in another scope still inserts after the upgrade.
        conn.execute(sa.text("INSERT INTO tools VALUES ('4', 'search', NULL)"))
        assert conn.execute(sa.text("SELECT COUNT(*) FROM tools WHERE name = 'search'")).scalar_one() == 3
    engine.dispose()


def test_downgrade_drops_index_and_is_idempotent(migration):
    """Downgrade removes only the new index and tolerates repeated runs."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _legacy_tools_table(conn)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.downgrade()
            migration.downgrade()
        assert INDEX_NAME not in _tools_indexes(conn)
        assert conn.execute(sa.text("SELECT COUNT(*) FROM tools")).scalar_one() == 3
    engine.dispose()


def test_upgrade_and_downgrade_skip_missing_table(migration):
    """Both directions are no-ops when the tools table does not exist."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.downgrade()
        assert not sa.inspect(conn).has_table("tools")
    engine.dispose()


def test_model_declares_matching_non_unique_index():
    """Fresh databases built from metadata get the same index as migrated ones."""
    indexes = {index.name: index for index in DbTool.__table__.indexes}
    index = indexes[INDEX_NAME]
    assert [column.name for column in index.columns] == ["name"]
    assert not index.unique


def test_name_lookup_uses_index_on_fresh_schema():
    """SQLite query planner picks the index for an equality lookup by name."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        plan = conn.execute(sa.text("EXPLAIN QUERY PLAN SELECT id FROM tools WHERE name = :name"), {"name": "search"}).all()
    engine.dispose()
    details = " ".join(str(row[-1]) for row in plan)
    assert INDEX_NAME in details
