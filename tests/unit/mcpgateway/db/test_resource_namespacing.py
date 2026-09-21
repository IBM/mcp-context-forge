# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_resource_namespacing.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Persistence and lifecycle regressions for resource namespacing.
"""

# Standard
import importlib
from unittest.mock import AsyncMock, patch

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, Gateway, Resource, resource_has_name_override
from mcpgateway.schemas import ResourceCreate, ResourceUpdate
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.resource_service import ResourceService
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

    event.listen(naming_db.bind, "before_cursor_execute", capture)
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


def test_refresh_reuses_gateway_name_for_dirty_resources(naming_db):
    """Description-only refreshes do not resolve the gateway once per resource."""
    gateway = Gateway(name="Upstream", slug="upstream", url="https://example.com/mcp", capabilities={})
    gateway.resources = [Resource(uri=f"test://report/{index}", name=f"Report {index}") for index in range(30)]
    naming_db.add(gateway)
    naming_db.flush()
    naming_db.expire_all()
    assert gateway.name == "Upstream"
    resources = naming_db.scalars(sa.select(Resource)).all()
    assert all("gateway" not in sa.inspect(resource).dict for resource in resources)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(naming_db.bind, "before_cursor_execute", capture)
    upstream = [ResourceCreate(uri=resource.uri, name=resource.original_name, description="Changed", content="") for resource in resources]
    GatewayService()._update_or_create_resources(naming_db, upstream, gateway, "federation")
    naming_db.flush()
    assert all(resource.description == "Changed" for resource in resources)
    assert not any("FROM gateways" in statement for statement in statements)
    assert all(resource.name.startswith("upstream-report-") for resource in resources)


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


def test_resource_migration_batches_updates():
    """Backfill bounds batch size and reruns without another UPDATE."""
    migration = importlib.import_module("mcpgateway.alembic.versions.c7e91a2b4d60_add_resource_namespacing")
    engine = sa.create_engine("sqlite://")
    batches = []

    def capture(_connection, _cursor, statement, parameters, _context, executemany):
        if statement.startswith("UPDATE resources"):
            batches.append(len(parameters) if executemany else 1)

    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE gateways (id TEXT PRIMARY KEY, name TEXT)"))
        connection.execute(sa.text("CREATE TABLE resources (id TEXT PRIMARY KEY, name VARCHAR(255) NOT NULL, gateway_id TEXT)"))
        connection.execute(sa.text("INSERT INTO gateways VALUES ('gw', 'Upstream')"))
        connection.execute(
            sa.text("INSERT INTO resources VALUES (:id, :name, 'gw')"),
            [{"id": str(index), "name": f"Report {index}"} for index in range(1001)],
        )
        event.listen(connection, "before_cursor_execute", capture)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert batches == [500, 500, 1]
            migration.upgrade()
            assert batches == [500, 500, 1]
        assert connection.execute(sa.text("SELECT count(*) FROM resources WHERE original_name IS NULL")).scalar_one() == 0
        assert connection.execute(sa.text("SELECT name FROM resources WHERE id = '1000'")).scalar_one() == "upstream-report-1000"
    engine.dispose()


@pytest.mark.parametrize("field", ["custom_name", "customName"])
@pytest.mark.parametrize("value", [None, "Weekly Report", "---", "a" * 255])
def test_explicit_resource_name_schema(field, value):
    """Both API spellings accept valid names and nullable omission semantics."""
    update = ResourceUpdate.model_validate({field: value})
    assert update.custom_name == value
    assert ResourceUpdate().custom_name is None


@pytest.mark.parametrize("value", ["", "a" * 256, "<script>", "bad/name"])
def test_explicit_resource_name_schema_rejects_invalid(value):
    """Explicit names do not bypass the existing resource validator."""
    with pytest.raises(ValidationError):
        ResourceUpdate(custom_name=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("federated", [False, True])
@pytest.mark.parametrize(
    "payload,expected_base",
    [
        ({"custom_name": "Weekly Report"}, "weekly-report"),
        ({"name": "Ignored", "custom_name": "Weekly Report"}, "weekly-report"),
        ({"name": "Weekly Report", "custom_name": None}, "weekly-report"),
        ({"name": "Weekly Report"}, "weekly-report"),
        ({"custom_name": "upstream-report"}, "upstream-report"),
        ({"custom_name": "---"}, ""),
    ],
)
async def test_explicit_resource_rename_persists(naming_db, federated, payload, expected_base):
    """Explicit intent wins over legacy names and persists through ORM listeners."""
    gateway = Gateway(name="Upstream", slug="upstream", url="https://example.com/mcp", capabilities={})
    resource = Resource(uri="test://rename", name="Report", visibility="public")
    naming_db.add(gateway)
    if federated:
        gateway.resources = [resource]
    else:
        naming_db.add(resource)
    naming_db.commit()
    service = ResourceService()
    with (
        patch("mcpgateway.services.resource_service.audit_trail.log_action"),
        patch.object(service, "_notify_resource_updated", new_callable=AsyncMock),
    ):
        await service.update_resource(naming_db, resource.id, ResourceUpdate(**payload))
        naming_db.expire(resource)
        expected = (f"upstream-{expected_base}" if expected_base else "upstream") if federated else (payload.get("custom_name") or payload["name"])
        assert resource.name == expected
        assert resource.custom_name_slug == expected_base
        assert resource.original_name == "Report"
        await service.update_resource(naming_db, resource.id, ResourceUpdate(description="Unchanged base"))
        naming_db.expire(resource)
        assert resource.name == expected
        assert resource.custom_name_slug == expected_base


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway_name", [None, "Upstream", "---"])
@pytest.mark.parametrize("submitted", ["Weekly Report", "unchanged", "---"])
async def test_bulk_resource_rename_preserves_identity(naming_db, gateway_name, submitted):
    """Bulk imports persist operator renames without overwriting upstream identity."""
    gateway = Gateway(name=gateway_name or "Upstream", slug="upstream", url="https://example.com/mcp", capabilities={})
    resource = Resource(uri="test://bulk", name="Report", visibility="public")
    naming_db.add(gateway)
    if gateway_name is not None:
        gateway.resources = [resource]
    else:
        naming_db.add(resource)
    naming_db.commit()
    old_name = resource.name
    name = old_name if submitted == "unchanged" else submitted
    upstream = ResourceCreate(uri=resource.uri, name=name, gateway_id=resource.gateway_id, content="")
    service = ResourceService()
    with patch("mcpgateway.services.resource_service.audit_trail.log_action"):
        result = await service.register_resources_bulk(naming_db, [upstream], conflict_strategy="update")
    assert result["updated"] == 1
    assert result["failed"] == 0
    naming_db.expire(resource)
    base = "report" if submitted == "unchanged" else slugify(name)
    assert resource.original_name == "Report"
    assert resource.custom_name_slug == base
    if gateway_name == "---":
        assert resource.name == old_name
    elif gateway_name is None:
        assert resource.name == name
        gateway.resources.append(resource)
        naming_db.flush()
    else:
        assert resource.name == (f"upstream-{base}" if base else "upstream")
    # An imported override survives refresh; an unchanged base follows upstream.
    upstream.name = "Monthly Report"
    GatewayService()._update_or_create_resources(naming_db, [upstream], gateway, "federation")
    naming_db.flush()
    naming_db.expire(resource)
    assert resource.original_name == "Monthly Report"
    assert resource.custom_name_slug == ("monthly-report" if submitted == "unchanged" else base)
    if gateway_name == "---":
        assert resource.name == old_name
