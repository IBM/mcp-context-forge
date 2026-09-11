# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_resource_namespacing.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Persistence and lifecycle regressions for resource namespacing.
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, Gateway, Resource, resource_has_name_override
from mcpgateway.schemas import ResourceCreate
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.create_slug import slugify


@pytest.fixture
def naming_db():
    """Use real ORM events and an isolated database for resource lifecycle tests."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("separator", ["-", "--", "_", "."])
@pytest.mark.parametrize("source", ["Daily Report", "---", "a-" * 127 + "a"])
def test_migration_listener_and_rename_agree(naming_db, monkeypatch, separator, source):
    """Back-fill, registration, and bulk gateway rename compose the same bytes."""
    monkeypatch.setattr(settings, "gateway_tool_name_separator", separator)
    migration = importlib.import_module("mcpgateway.alembic.versions.c7e91a2b4d60_add_resource_namespacing")
    base = slugify(source)
    prefix = "long" * 70
    expected = (prefix + separator + base if base else prefix)[:255]
    gateway = Gateway(name=prefix, slug=prefix, url="https://example.com/mcp", capabilities={})
    resource = Resource(uri="test://shared", name=source)
    gateway.resources = [resource]
    local = Resource(uri="test://local", name="My Report")
    naming_db.add_all([gateway, local])
    naming_db.flush()
    assert resource.name == expected
    assert resource.custom_name_slug == base
    assert local.name == "My Report"

    # Exercise migration against legacy data independently of ORM insert events.
    connection = naming_db.connection()
    connection.execute(sa.update(Resource).where(Resource.id == resource.id).values(name=source, original_name=None, custom_name_slug=None))
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        migration.upgrade()
    naming_db.expire(resource)
    assert resource.name == expected
    assert resource.original_name == source
    assert resource.custom_name_slug == base

    gateway.name = "Short"
    naming_db.flush()
    naming_db.expire(resource)
    assert resource.name == ("short" + separator + base if base else "short")[:255]
    assert resource.custom_name_slug == base
    local.description = "Changed"
    naming_db.flush()
    assert local.name == "My Report"


def test_refresh_preserves_override_and_is_idempotent(naming_db):
    """URI identity permits renames without repeated resource updates."""
    gateway = Gateway(name="Upstream", slug="upstream", url="https://example.com/mcp", capabilities={})
    naming_db.add(gateway)
    naming_db.flush()
    service = GatewayService()
    upstream = ResourceCreate(uri="test://shared", name="Daily Report", content="")
    resources = service._update_or_create_resources(naming_db, [upstream], gateway, "federation")
    naming_db.add_all(resources)
    naming_db.flush()
    resource = resources[0]
    assert resource.name == "upstream-daily-report"
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("UPDATE resources"):
            statements.append(statement)

    sa.event.listen(naming_db.bind, "before_cursor_execute", capture)
    for _ in range(2):
        assert service._update_or_create_resources(naming_db, [upstream], gateway, "federation") == []
        naming_db.flush()
    assert statements == []
    upstream.name = "Weekly Report"
    service._update_or_create_resources(naming_db, [upstream], gateway, "federation")
    naming_db.flush()
    assert resource.name == "upstream-weekly-report"
    assert len(statements) == 1
    resource.custom_name_slug = "chosen"
    naming_db.flush()
    upstream.name = "Monthly Report"
    service._update_or_create_resources(naming_db, [upstream], gateway, "federation")
    naming_db.flush()
    assert resource.original_name == "Monthly Report"
    assert resource.name == "upstream-chosen"
    count = len(statements)
    service._update_or_create_resources(naming_db, [upstream], gateway, "federation")
    naming_db.flush()
    assert len(statements) == count


def test_duplicate_names_and_uris_preserve_resource_identity(naming_db):
    """Names never become a uniqueness key, within or across gateways."""
    gateways = [Gateway(name=name, slug=name, url=f"https://{name}.example.com/mcp", capabilities={}) for name in ("first", "second")]
    for gateway in gateways:
        gateway.resources = [Resource(uri="test://same", name="Report"), Resource(uri="test://other", name="Report")]
    naming_db.add_all(gateways)
    naming_db.flush()
    rows = naming_db.scalars(sa.select(Resource)).all()
    assert len(rows) == 4
    assert sorted(row.name for row in rows) == ["first-report", "first-report", "second-report", "second-report"]


def test_empty_gateway_slug_preserves_names(naming_db):
    """An empty gateway slug never writes a separator-led resource name."""
    gateway = Gateway(name="Upstream", slug="upstream", url="https://example.com/mcp", capabilities={}, resources=[Resource(uri="test://same", name="Report")])
    naming_db.add(gateway)
    naming_db.flush()
    resource = gateway.resources[0]
    previous = resource.name
    gateway.name = "---"
    naming_db.flush()
    naming_db.expire(resource)
    assert resource.name == previous
    resource.description = "Changed"
    naming_db.flush()
    assert resource.name == previous


def test_override_comparison_survives_separator_change(monkeypatch):
    """A configuration change does not turn a default base into an override."""
    resource = Resource(name="gateway-daily-report", original_name="Daily Report", custom_name_slug="daily-report")
    monkeypatch.setattr(settings, "gateway_tool_name_separator", "_")
    assert not resource_has_name_override(resource)
    resource.custom_name_slug = "chosen"
    assert resource_has_name_override(resource)
    resource.custom_name_slug = ""
    assert resource_has_name_override(resource)


def test_resource_migration_upgrade_downgrade(monkeypatch):
    """Legacy names survive repeat upgrade; downgrade uses stored values only."""
    migration = importlib.import_module("mcpgateway.alembic.versions.c7e91a2b4d60_add_resource_namespacing")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE gateways (id TEXT PRIMARY KEY, name TEXT)"))
        connection.execute(sa.text("CREATE TABLE resources (id TEXT PRIMARY KEY, name VARCHAR(255) NOT NULL, gateway_id TEXT)"))
        connection.execute(sa.text("INSERT INTO gateways VALUES ('gw', 'Modern Server')"))
        connection.execute(sa.text("INSERT INTO resources VALUES ('remote', 'Daily Report', 'gw'), ('local', 'My Report', NULL)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            first = connection.execute(sa.text("SELECT * FROM resources ORDER BY id")).all()
            migration.upgrade()
            assert connection.execute(sa.text("SELECT * FROM resources ORDER BY id")).all() == first
            assert connection.execute(sa.text("SELECT name FROM resources WHERE id = 'remote'")).scalar_one() == "modern-server-daily-report"
            connection.execute(sa.text("UPDATE resources SET name = 'operator-choice' WHERE id = 'remote'"))
            monkeypatch.setattr(settings, "gateway_tool_name_separator", ".")
            migration.downgrade()
            migration.downgrade()
        assert connection.execute(sa.text("SELECT name FROM resources ORDER BY id")).scalars().all() == ["My Report", "Daily Report"]
        assert {column["name"] for column in sa.inspect(connection).get_columns("resources")} == {"id", "name", "gateway_id"}
    engine.dispose()
