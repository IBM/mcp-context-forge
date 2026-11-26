# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_configuration_import_roundtrip.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise import transaction, matching, and portable associations against SQLite.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.schemas import GatewayUpdate, PromptCreate, ResourceCreate, ToolCreate, ToolUpdate
from mcpgateway.services.export_service import ExportService
from mcpgateway.services.import_service import ConflictStrategy, ImportConflictError, ImportService, ImportValidationError
from mcpgateway.services.root_service import RootService
from mcpgateway.services.tool_service import _protect_tool_headers_for_storage, ToolError

from mcpgateway.utils.services_auth import encode_auth

ACTOR = "importer@example.com"


@pytest.fixture
def registry(tmp_path):
    """Create a private registry and authenticated actor's teams."""
    engine = create_engine(f"sqlite:///{tmp_path / 'registry.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EmailUser(email=ACTOR, password_hash="unused", full_name="Importer"))
        db.flush()
        db.add_all([EmailTeam(id="personal", name="Personal", slug="personal", created_by=ACTOR, is_personal=True), EmailTeam(id="target", name="Target", slug="target", created_by=ACTOR)])
        db.flush()
        db.add_all([EmailTeamMember(team_id=team, user_email=ACTOR, role="owner") for team in ("personal", "target")])
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def importer():
    """Isolate roots and statuses while using real registry services."""
    service = ImportService()
    service.root_service = RootService()
    return service


def envelope(**entities):
    """Build a supported configuration envelope."""
    return {"version": "2025-03-26", "exported_at": datetime.now(timezone.utc).isoformat(), "entities": entities}


def tool(name, **fields):
    """Build a REST tool entry."""
    return {"name": name, "url": "https://example.com/upstream", "integration_type": "REST", "request_type": "GET", **fields}


@pytest.mark.asyncio
async def test_selection_named_team_and_repeat_update(registry, importer):
    """Apply the same scoped selection to counters, writes, and repeat updates."""
    configuration = envelope(tools=[tool("sample", visibility="public", owner_email="foreign@example.com", team_id="foreign")], servers=[{"name": "omitted"}])
    result = await importer.import_configuration(registry, configuration, imported_by=ACTOR, team_name="Target", token_teams=["target"], selected_entities={"tools": []})
    assert result.to_dict()["progress"] == {"total": 1, "processed": 1, "created": 1, "updated": 0, "skipped": 0, "failed": 0}
    row = registry.scalars(select(Tool)).one()
    assert (row.visibility, row.team_id, row.owner_email) == ("public", "target", ACTOR)
    assert registry.scalar(select(Server.id)) is None
    configuration["entities"]["tools"][0]["description"] = "repeat"
    result = await importer.import_configuration(registry, configuration, imported_by=ACTOR, team_name="Target", token_teams=["target"], selected_entities={"tools": []})
    assert result.updated_entities == 1
    assert registry.scalars(select(Tool)).one().description == "repeat"
    empty = await importer.import_configuration(registry, configuration, imported_by=ACTOR, selected_entities={})
    assert empty.total_entities == empty.processed_entities == 0


@pytest.mark.asyncio
async def test_import_rejects_overwrite_of_derived_tool(registry, importer):
    """Reject overwrites during preview and writes. Preserve stored tool data."""
    derived = Tool(
        original_name="derived",
        custom_name="derived",
        integration_type="A2A",
        request_type="POST",
        url="https://agent.example.com",
        team_id="target",
        owner_email=ACTOR,
        visibility="team",
        input_schema={},
        annotations={"a2a_agent_id": "agent-id"},
    )
    registry.add(derived)
    registry.commit()
    configuration = envelope(
        tools=[
            tool("derived"),
            tool("manual", integration_type="A2A", request_type="POST"),
            tool("derived", integration_type="A2A", request_type="POST", url=derived.url, annotations={"a2a_agent_id": "other-agent"}),
            tool("derived", integration_type="A2A", request_type="POST"),
        ]
    )

    for dry_run in (True, False):
        result = await importer.import_configuration(registry, configuration, imported_by=ACTOR, team_name="Target", token_teams=["target"], dry_run=dry_run)
        assert (result.created_entities, result.updated_entities, result.failed_entities) == (0, 0, 4)

    registry.refresh(derived)
    assert derived.integration_type == "A2A"
    assert derived.annotations == {"a2a_agent_id": "agent-id"}
    assert derived.url == "https://agent.example.com"


@pytest.mark.asyncio
async def test_a2a_metadata_update_preserves_transport(registry, importer):
    """Preserve the derived tool's binding and credentials during metadata edits."""
    auth_value = encode_auth({"Authorization": "Bearer fixture-value"})
    derived = Tool(
        original_name="derived",
        url="https://agent.example.com",
        integration_type="A2A",
        request_type="POST",
        visibility="team",
        team_id="target",
        owner_email=ACTOR,
        input_schema={},
        annotations={"a2a_agent_id": "agent-id"},
        auth_type="bearer",
        auth_value=auth_value,
    )
    registry.add(derived)
    registry.commit()
    schema = ToolUpdate(integration_type="A2A", description="Direct edit")
    await importer.tool_service.update_tool(registry, derived.id, schema, user_email=ACTOR)
    assert derived.description == "Direct edit"
    with pytest.raises(ToolError, match="Cannot change A2A tool binding"):
        await importer.tool_service.update_tool(registry, derived.id, ToolUpdate(annotations={"a2a_agent_id": "other-agent"}), user_email=ACTOR)

    configuration = envelope(
        tools=[tool("derived", integration_type="A2A", request_type="POST", url=derived.url, annotations=derived.annotations, description="Imported edit", credentials_required=True)]
    )
    scope = {"imported_by": ACTOR, "team_name": "Target", "token_teams": ["target"]}
    preview = await importer.import_configuration(registry, configuration, dry_run=True, **scope)
    assert (preview.updated_entities, preview.failed_entities) == (1, 0)
    applied = await importer.import_configuration(registry, configuration, **scope)
    assert (applied.updated_entities, applied.failed_entities) == (1, 0)

    registry.refresh(derived)
    assert derived.description == "Imported edit"
    assert derived.url == "https://agent.example.com"
    assert derived.annotations == {"a2a_agent_id": "agent-id"}
    assert derived.auth_value == auth_value


@pytest.mark.asyncio
async def test_default_non_admin_import_matches_owned_server(registry, importer):
    """Create and update the caller's server beside a teammate's server."""
    teammate = "teammate@example.com"
    registry.add(EmailUser(email=teammate, password_hash="unused", full_name="Teammate"))
    registry.flush()
    registry.add(EmailTeamMember(team_id="target", user_email=teammate, role="member"))
    registry.commit()
    shared = envelope(servers=[{"name": "shared", "description": "teammate"}])
    assert (await importer.import_configuration(registry, shared, imported_by=teammate, team_name="Target", token_teams=["target"])).created_entities == 1
    scope = {"imported_by": ACTOR, "token_teams": ["personal", "target"]}
    config = envelope(servers=[{"name": "shared", "description": "initial"}])
    assert (await importer.import_configuration(registry, config, **scope, dry_run=True)).created_entities == 1
    assert (await importer.import_configuration(registry, config, **scope)).created_entities == 1
    config["entities"]["servers"][0]["description"] = "updated"
    assert (await importer.import_configuration(registry, config, **scope, dry_run=True)).updated_entities == 1
    assert (await importer.import_configuration(registry, config, **scope)).updated_entities == 1
    rows = {row.owner_email: (row.team_id, row.description) for row in registry.scalars(select(Server))}
    assert rows == {ACTOR: ("personal", "updated"), teammate: ("target", "teammate")}


@pytest.mark.asyncio
async def test_foreign_public_tool_remains_a_create_conflict(registry, importer):
    """Respect public tool uniqueness after filtering update candidates."""
    teammate = "teammate@example.com"
    registry.add(EmailUser(email=teammate, password_hash="unused", full_name="Teammate"))
    registry.flush()
    registry.add(EmailTeamMember(team_id="target", user_email=teammate, role="member"))
    registry.commit()
    config = envelope(tools=[tool("shared", visibility="public")])
    assert (await importer.import_configuration(registry, config, imported_by=teammate, team_name="Target", token_teams=["target"])).created_entities == 1
    for dry_run in (True, False):
        result = await importer.import_configuration(registry, config, imported_by=ACTOR, token_teams=["personal", "target"], dry_run=dry_run)
        assert result.items["tools"][0]["conflicts_with"] is True
        assert (result.created_entities, result.updated_entities, result.failed_entities) == (0, 0, 1)
    assert registry.scalars(select(Tool)).one().owner_email == teammate


@pytest.mark.asyncio
async def test_null_visibility_uses_team_default_and_preserves_updates(registry, importer):
    """Apply the same visibility default in preview and writes."""
    config = envelope(
        servers=[{"name": "server", "visibility": None}],
        gateways=[{"name": "gateway", "url": "https://example.com/mcp", "credentials_required": True, "visibility": None}],
    )
    scope = {"imported_by": ACTOR, "token_teams": ["personal"]}
    preview = await importer.preview_import(registry, config, **scope)
    live = await importer.import_configuration(registry, config, **scope)
    assert preview["outcomes"]["progress"] == live.to_dict()["progress"]
    assert live.created_entities == 2
    for model in (Gateway, Server):
        row = registry.scalars(select(model)).one()
        assert (row.visibility, row.team_id) == ("team", "personal")
        row.visibility = "private"
    registry.commit()
    updated = await importer.import_configuration(registry, config, **scope)
    assert updated.updated_entities == 2
    assert registry.scalar(select(Gateway.visibility)) == registry.scalar(select(Server.visibility)) == "private"


@pytest.mark.asyncio
async def test_team_visible_creates_require_resolved_destination(registry, importer, monkeypatch):
    """Reject missing teams consistently and keep teamless updates and roots available."""
    actor = "admin-without-team@example.com"
    registry.add(EmailUser(email=actor, password_hash="unused", full_name="Import admin", is_admin=True))
    registry.commit()
    scope = {"imported_by": actor, "unrestricted_admin": True}
    config = envelope(servers=[{"name": "server", "visibility": None}], resources=[{"name": "resource", "uri": "test://resource", "content": "fixture"}])
    preview = await importer.preview_import(registry, config, **scope)
    dry = await importer.import_configuration(registry, config, **scope, dry_run=True)
    live = await importer.import_configuration(registry, config, **scope)
    report = live.to_dict()
    assert preview["outcomes"]["progress"] == dry.to_dict()["progress"] == report["progress"]
    assert (live.created_entities, live.failed_entities) == (0, 2)
    assert preview["outcomes"]["errors"] == dry.errors == live.errors
    assert all("Specify team_name or set up a personal team" in error for error in live.errors)
    assert all(registry.scalar(select(model.id)) is None for model in (Server, Resource))

    narrowed = await importer.import_configuration(registry, config, imported_by=actor, token_teams=["target"])
    assert narrowed.failed_entities == 2
    assert all("PermissionError" in error for error in narrowed.errors)
    created = await importer.import_configuration(registry, config, **scope, team_name="Target")
    assert (created.created_entities, created.failed_entities) == (2, 0)
    config["entities"]["servers"][0]["description"] = "updated without destination team"
    updated = await importer.import_configuration(registry, config, **scope)
    assert (updated.updated_entities, updated.failed_entities) == (2, 0)
    server = registry.scalars(select(Server)).one()
    assert (server.team_id, server.visibility, server.description) == ("target", "team", "updated without destination team")

    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    root = envelope(roots=[{"name": "root", "uri": "https://example.com/root"}])
    assert (await importer.import_configuration(registry, root, **scope)).created_entities == 1


@pytest.mark.asyncio
async def test_import_rejects_unavailable_destination_teams(registry, importer):
    """Reject team names outside membership or scope and ambiguous admin targets."""
    registry.add_all([EmailTeam(id="outsider", name="Outsider", slug="outsider", created_by=ACTOR), EmailTeam(id="duplicate", name="Target", slug="duplicate-target", created_by=ACTOR)])
    registry.commit()
    config = envelope(servers=[{"name": "denied"}])
    for name, teams in (("Outsider", ["outsider"]), ("Target", ["personal"])):
        with pytest.raises(PermissionError):
            await importer.import_configuration(registry, config, imported_by=ACTOR, team_name=name, token_teams=teams)
    for name in ("Missing", "Target"):
        with pytest.raises(ImportValidationError, match="unavailable or ambiguous"):
            await importer.import_configuration(registry, config, imported_by=ACTOR, team_name=name, unrestricted_admin=True)
    assert registry.scalar(select(Server.id)) is None


@pytest.mark.asyncio
async def test_non_admin_import_cannot_update_foreign_rows_or_token_exchange_gateway(registry, importer):
    """Keep foreign rows and token exchange gateways unchanged across imports."""
    config = envelope(
        gateways=[{"name": "gateway", "url": "https://example.com/mcp", "credentials_required": True}],
        prompts=[{"name": "prompt", "template": "Original prompt"}],
        resources=[{"name": "resource", "uri": "test://resource", "content": "original"}],
        servers=[{"name": "server"}],
    )
    assert (await importer.import_configuration(registry, config, imported_by=ACTOR, team_name="Target", token_teams=["target"])).created_entities == 4
    teammate = "teammate@example.com"
    registry.add(EmailUser(email=teammate, password_hash="unused", full_name="Teammate"))
    registry.flush()
    registry.add(EmailTeamMember(team_id="target", user_email=teammate, role="member"))
    gateway = registry.scalars(select(Gateway)).one()
    gateway.auth_type = "oauth"
    gateway.oauth_config = {"grant_type": "token-exchange"}
    registry.commit()
    for entries in config["entities"].values():
        entries[0]["description"] = "denied change"
    denied = await importer.import_configuration(registry, config, imported_by=teammate, token_teams=["target"])
    assert (denied.created_entities, denied.updated_entities, denied.failed_entities) == (0, 0, 4)
    gateway_only = {"gateways": []}
    denied = await importer.import_configuration(registry, config, imported_by=ACTOR, token_teams=["target"], selected_entities=gateway_only)
    assert denied.failed_entities == 1
    for model in (Gateway, Prompt, Resource, Server):
        row = registry.scalars(select(model)).one()
        assert row.owner_email == ACTOR
        assert row.description != "denied change"


@pytest.mark.asyncio
async def test_fatal_conflict_restores_rows_and_roots(registry, importer, monkeypatch):
    """Undo writes even after nested service commits and keep staged roots private."""
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    base = await importer.import_configuration(registry, envelope(servers=[{"name": "existing"}]), imported_by=ACTOR)
    assert base.created_entities == 1
    with pytest.raises(ImportConflictError):
        await importer.import_configuration(
            registry,
            envelope(
                roots=[{"name": "root", "uri": "https://example.com/root"}],
                gateways=[{"name": "pending", "url": "https://example.com/mcp", "credentials_required": True}],
                tools=[tool("rolled-back")],
                servers=[{"name": "existing"}],
            ),
            imported_by=ACTOR,
            conflict_strategy=ConflictStrategy.FAIL,
        )
    assert registry.scalar(select(Tool.id)) is None
    assert registry.scalar(select(Gateway.id)) is None
    failed = next(status for status in importer.list_import_statuses(imported_by=ACTOR, token_teams=None) if status.status == "failed")
    assert failed.processed_entities == 4
    assert failed.created_entities == 0
    assert failed.credentials_required == []
    assert failed.items["gateways"][0]["outcome"] == "rolled_back"
    assert await importer.root_service.list_roots() == []
    assert registry.scalars(select(Server.name)).all() == ["existing"]


@pytest.mark.asyncio
async def test_resource_cache_invalidation_follows_outer_commit(registry, importer, monkeypatch):
    """Invalidate only after a separate session can read the committed resource."""
    resources_seen = []

    async def invalidate_resources():
        with Session(registry.get_bind()) as reader:
            resources_seen.append(reader.scalars(select(Resource.uri)).all())

    monkeypatch.setattr("mcpgateway.services.resource_service._get_registry_cache", lambda: SimpleNamespace(invalidate_resources=invalidate_resources))
    await importer.import_configuration(registry, envelope(servers=[{"name": "existing"}]), imported_by=ACTOR)
    uri = "test://deferred-cache"
    resource = {"name": "deferred-cache", "uri": uri, "content": "fixture"}
    with pytest.raises(ImportConflictError):
        await importer.import_configuration(registry, envelope(resources=[resource], servers=[{"name": "existing"}]), imported_by=ACTOR, conflict_strategy=ConflictStrategy.FAIL)
    assert registry.scalar(select(Resource.id)) is None
    assert not resources_seen

    result = await importer.import_configuration(registry, envelope(resources=[resource]), imported_by=ACTOR)
    assert result.created_entities == 1
    assert resources_seen == [[uri]]


@pytest.mark.asyncio
async def test_import_rechecks_server_owner_after_matching(registry, importer, monkeypatch):
    """Reject an update if the row owner changes after the import matches it."""
    scope = {"imported_by": ACTOR, "token_teams": ["personal"]}
    original = envelope(servers=[{"name": "existing", "description": "original"}])
    assert (await importer.import_configuration(registry, original, **scope)).created_entities == 1
    build_index = importer._destination_index

    def index_before_owner_changes(db, *args):
        index = build_index(db, *args)
        db.execute(update(Server).where(Server.name == "existing").values(owner_email="other@example.com").execution_options(synchronize_session=False))
        return index

    monkeypatch.setattr(importer, "_destination_index", index_before_owner_changes)
    changed = envelope(servers=[{"name": "existing", "description": "must not apply"}])
    result = await importer.import_configuration(registry, changed, **scope)
    assert result.errors == ["servers item existing: PermissionError"]
    assert result.updated_entities == 0
    row = registry.scalars(select(Server).execution_options(populate_existing=True)).one()
    assert (row.owner_email, row.description) == ("other@example.com", "original")


@pytest.mark.asyncio
async def test_dry_run_and_item_failure(registry, importer, caplog):
    """Report local outcomes without writes and retain successful items on completion."""
    config = envelope(tools=[tool("good"), tool("invalid", request_type="INVALID")])
    dry = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=True)
    assert (dry.created_entities, dry.failed_entities, dry.processed_entities) == (1, 1, 2)
    assert registry.scalar(select(Tool.id)) is None
    real = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert (real.created_entities, real.failed_entities, real.processed_entities) == (1, 1, 2)
    assert registry.scalars(select(Tool.original_name)).all() == ["good"]
    messages = [record.getMessage() for record in caplog.records if record.name == "mcpgateway.services.import_service" and record.levelname == "WARNING"]
    assert f"Import {real.import_id} item 2 (tools): ValidationError" in messages
    assert all("INVALID" not in message for message in messages)


@pytest.mark.asyncio
async def test_dry_run_reports_policy_permission_and_preserves_omitted_policy(registry, importer, monkeypatch):
    """Use the same validation policy permission in preview and subsequent writes."""
    await importer.import_configuration(registry, envelope(tools=[tool("existing")]), imported_by=ACTOR)
    stored = registry.scalars(select(Tool)).one()
    stored.tool_validation_policy = "true"
    registry.commit()

    async def deny(*args, **kwargs):
        raise PermissionError("Policy changes are forbidden")

    monkeypatch.setattr("mcpgateway.services.import_service.check_policy_permission", deny)
    monkeypatch.setattr("mcpgateway.services.tool_service.check_policy_permission", deny)
    changed = envelope(tools=[tool("existing", tool_validation_policy=None)])
    for dry_run in (True, False):
        status = await importer.import_configuration(registry, changed, imported_by=ACTOR, dry_run=dry_run)
        assert status.failed_entities == 1
        assert "PermissionError" in status.errors[0]
    omitted = await importer.import_configuration(registry, envelope(tools=[tool("existing", description="changed")]), imported_by=ACTOR)
    assert omitted.updated_entities == 1
    assert registry.scalars(select(Tool)).one().tool_validation_policy == "true"


@pytest.mark.asyncio
async def test_public_tool_collision_outside_explicit_team_is_a_dry_run_conflict(registry, importer):
    """A named team cannot claim a public tool name used in another team."""
    config = envelope(tools=[tool("public-tool", visibility="public")])
    await importer.import_configuration(registry, config, imported_by=ACTOR)

    for dry_run in (True, False):
        with pytest.raises(ImportConflictError):
            await importer.import_configuration(registry, config, imported_by=ACTOR, team_name="Target", conflict_strategy=ConflictStrategy.FAIL, dry_run=dry_run)

    assert registry.scalars(select(Tool.team_id)).all() == ["personal"]


@pytest.mark.asyncio
async def test_public_tool_visibility_change_reports_collision_in_dry_run(registry, importer):
    """Preview a visibility change with the same public-name restriction as update."""
    await importer.import_configuration(registry, envelope(tools=[tool("sample")]), imported_by=ACTOR, team_name="Target")
    public = envelope(tools=[tool("sample", visibility="public")])
    await importer.import_configuration(registry, public, imported_by=ACTOR, team_name="Personal")

    for dry_run in (True, False):
        status = await importer.import_configuration(registry, public, imported_by=ACTOR, team_name="Target", dry_run=dry_run)
        assert (status.updated_entities, status.failed_entities) == (0, 1)
    assert registry.scalar(select(Tool.visibility).where(Tool.team_id == "target")) == "team"


@pytest.mark.asyncio
async def test_preview_visibility_change_for_tool_created_earlier_in_file(registry, importer):
    """Use planned tool identity when previewing a repeated file entry."""
    config = envelope(tools=[tool("sample"), tool("sample", visibility="public")])
    for dry_run in (True, False):
        status = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=dry_run)
        assert (status.created_entities, status.updated_entities, status.failed_entities) == (1, 1, 0)
    assert registry.scalars(select(Tool.visibility)).all() == ["public"]


@pytest.mark.asyncio
async def test_public_federated_visibility_change_checks_invocation_name(registry, importer, monkeypatch):
    """Match gateway-prefixed tool names when previewing a visibility change."""

    async def initialize(url, *args, **kwargs):
        return {}, [ToolCreate(name="shared", url=url, integration_type="REST", request_type="GET")], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    team_url = "https://team.example.com/mcp"
    for team, visibility, url in (("Target", "team", team_url), ("Personal", "public", "https://public.example.com/mcp")):
        config = envelope(gateways=[{"name": "same-name", "url": url, "visibility": visibility, "transport": "STREAMABLEHTTP"}])
        result = await importer.import_configuration(registry, config, imported_by=ACTOR, team_name=team)
        assert result.created_entities == 1

    public = envelope(tools=[tool("shared", visibility="public", gateway_name="same-name", gateway_url=team_url)])
    for dry_run in (True, False):
        status = await importer.import_configuration(registry, public, imported_by=ACTOR, team_name="Target", dry_run=dry_run)
        assert (status.updated_entities, status.failed_entities) == (0, 1)
        assert "conflict" in status.errors[0]


@pytest.mark.asyncio
async def test_partial_tool_resolution_retains_binding(registry, importer):
    """Keep the complete bound set when an unrelated reference cannot resolve."""
    config = envelope(tools=[tool("first", id="source-first"), tool("second", id="source-second")], servers=[{"name": "virtual", "instructions": "start", "tool_ids": ["source-first"]}])
    first = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert first.created_entities == 3
    virtual = registry.scalars(select(Server)).one()
    assert [binding.original_name for binding in virtual.tools] == ["first"]
    second_id = registry.scalar(select(Tool.id).where(Tool.original_name == "second"))
    result = await importer.import_configuration(registry, envelope(servers=[{"name": "virtual", "tool_ids": [second_id, "missing"], "description": "updated"}]), imported_by=ACTOR)
    assert result.updated_entities == 1
    assert result.warnings == ["Unresolved tool references for server virtual: reference 2"]
    assert [binding.original_name for binding in registry.scalars(select(Server)).one().tools] == ["first"]
    assert registry.scalars(select(Server)).one().instructions == "start"


@pytest.mark.asyncio
async def test_import_ignores_credentials_and_clears_saved_auth_on_origin_change(registry, importer, caplog):
    """Keep destination credentials only when their origin stays the same."""
    caplog.set_level("INFO")
    configuration = envelope(tools=[tool("secured", auth_type="bearer", auth_value="credential-payload", headers={"Authorization": "example-credential", "Accept": "application/json"})])
    first = await importer.import_configuration(registry, configuration, imported_by=ACTOR)
    assert first.credentials_required == [{"type": "tools", "identifier": "secured"}]
    stored = registry.scalars(select(Tool)).one()
    assert stored.auth_value is None and stored.headers == {"Accept": "application/json"}
    stored.auth_type = "bearer"
    saved_auth = encode_auth({"Authorization": "Bearer example-test-token"})
    stored.auth_value = saved_auth
    registry.commit()
    same_origin = await importer.import_configuration(registry, configuration, imported_by=ACTOR)
    assert same_origin.updated_entities == 1 and not same_origin.credentials_required
    assert registry.scalars(select(Tool)).one().auth_value == saved_auth
    configuration["entities"]["tools"][0]["url"] = "https://example.org/upstream"
    replacement = await importer.import_configuration(registry, configuration, imported_by=ACTOR)
    assert replacement.updated_entities == 1 and replacement.credentials_required
    assert registry.scalars(select(Tool)).one().auth_value is None
    assert "headers.Authorization" in caplog.text
    assert "example-credential" not in caplog.text and "credential-payload" not in caplog.text
    with pytest.raises(ImportValidationError, match="rekey_secret"):
        await importer.import_configuration(registry, configuration, rekey_secret="obsolete")   # pragma: allowlist secret


@pytest.mark.asyncio
async def test_import_clears_saved_sigv4_config_when_tool_origin_changes(registry, importer):
    """Keep SigV4 configuration on the original origin only."""
    await importer.import_configuration(registry, envelope(tools=[tool("signed")]), imported_by=ACTOR)
    stored = registry.scalars(select(Tool)).one()
    stored.auth_type = "sigv4"
    stored.sigv4_config = {"region": "us-east-1", "service": "execute-api"}
    registry.commit()

    replacement = await importer.import_configuration(registry, envelope(tools=[tool("signed", url="https://example.org/upstream")]), imported_by=ACTOR)

    assert replacement.updated_entities == 1
    assert replacement.credentials_required == [{"type": "tools", "identifier": "signed"}]
    assert stored.auth_type is None
    assert stored.sigv4_config is None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_enabled", [False, True])
async def test_gateway_401_import_and_recovery(registry, importer, monkeypatch, async_enabled):
    """Persist a credential-blocked gateway without probing it in maintenance."""
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", async_enabled)
    gateway_service = importer.gateway_service
    calls = []

    async def initialize(url, *args, **kwargs):
        calls.append((url, args, kwargs))
        auth = args[0] if args else kwargs.get("authentication")
        if not auth:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError("upstream auth required", request=request, response=httpx.Response(401, request=request))
        return {}, [], [], [], [], None

    monkeypatch.setattr(gateway_service, "_initialize_gateway", initialize)
    config = envelope(gateways=[{"name": "protected", "url": "https://example.com/mcp", "transport": "STREAMABLEHTTP"}], tools=[tool("valid")])
    status = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert status.created_entities == 2 and status.credentials_required == [{"type": "gateways", "identifier": "protected"}]
    row = registry.scalars(select(Gateway)).one()
    assert row.status == "pending" and not row.reachable and len(calls) == 1
    await gateway_service._check_single_gateway_health(row)
    assert len(calls) == 1
    row_id = row.id
    await gateway_service.update_gateway(registry, row_id, GatewayUpdate(auth_type="bearer", auth_token="example-test-token"), user_email=ACTOR)
    row = registry.get(Gateway, row_id)
    if async_enabled:
        row.lifecycle_claimed_by = gateway_service._instance_id
        registry.commit()
        await gateway_service._process_gateway_lifecycle_once(registry, row_id)
        registry.refresh(row)
    assert row.status == "active" and row.reachable and row.auth_value


@pytest.mark.asyncio
async def test_full_and_selective_exports_apply_same_credential_policy(registry, importer):
    """Remove all configured query credentials and retain portable tool headers."""
    config = envelope(
        gateways=[{"name": name, "url": f"https://{name}.example.com/mcp", "credentials_required": True} for name in ("query-auth", "client-certificate", "client-key")],
        tools=[tool("operational"), tool("authenticated")],
    )
    assert (await importer.import_configuration(registry, config, imported_by=ACTOR)).created_entities == 5
    gateways = {row.name: row for row in registry.scalars(select(Gateway))}
    query_gateway = gateways["query-auth"]
    query_gateway.url += "?first_configured=placeholder-one&second_configured=placeholder-two&code=placeholder-code&Signature=placeholder-signature&region=eu"
    query_gateway.auth_query_params = {"first_configured": "placeholder-one", "second_configured": "placeholder-two", "code": "placeholder-code"}
    gateways["client-certificate"].client_cert = "placeholder-certificate"
    gateways["client-key"].client_key = "placeholder-key"
    for gateway in gateways.values():
        gateway.status = "active"
        gateway.status_message = None
    tools = {row.name: row for row in registry.scalars(select(Tool))}
    tools["operational"].headers = _protect_tool_headers_for_storage({"Content-Type": "application/json", "Upgrade": "websocket", "X-Region": "eu", "X-Count": 5})
    tools["authenticated"].headers = _protect_tool_headers_for_storage(
        {"Authorization": "Bearer placeholder-header", "X-Amz-Security-Token": "placeholder-aws", "X-Vault-Token": "placeholder-vault", "X-Region": "eu"}
    )
    registry.commit()

    exporter = ExportService()
    with Session(registry.get_bind(), expire_on_commit=False) as reader:
        full = await exporter.export_configuration(reader, include_types=["gateways", "tools"])
        selective = await exporter.export_selective(reader, {"gateways": [row.id for row in gateways.values()], "tools": [row.id for row in tools.values()]})
    expected_headers = {"operational": {"Content-Type": "application/json", "X-Region": "eu"}, "authenticated": {"X-Region": "eu"}}
    for data in (full, selective):
        entities = data["entities"]
        assert {row["name"] for row in entities["gateways"] if row["credentials_required"]} == set(gateways)
        [query_entry] = [row for row in entities["gateways"] if row["name"] == "query-auth"]
        assert query_entry["url"] == "https://query-auth.example.com/mcp?region=eu"
        assert {row["name"]: row["headers"] for row in entities["tools"]} == expected_headers
        assert [row["name"] for row in entities["tools"] if row.get("credentials_required")] == ["authenticated"]
        assert "placeholder-" not in str(entities)


@pytest.mark.asyncio
async def test_import_strips_provider_credentials_and_rejects_malformed_operational_headers(registry, importer):
    """Distinguish invalid header data from missing credentials."""
    names = (
        "X-GitHub-Token",
        "X-Vault-Token",
        "Private-Token",
        "X-Webhook-Secret",
        "X-Auth",
        "X-Custom-Auth",
        "X-Amz-Security-Token",
        "X-Goog-Api-Key",
        "Ocp-Apim-Subscription-Key",
    )
    config = envelope(
        tools=[
            tool("valid", url="https://example.com/api?sig=test-value&X-Goog-Signature=test-value&code=region-code", headers={**dict.fromkeys(names, "test-value"), "X-Region": "eu"}),
            tool("invalid", headers={"X-Count": 5}),
        ]
    )
    for dry_run in (True, False):
        result = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=dry_run)
        assert (result.created_entities, result.failed_entities) == (1, 1)
        assert "InvalidPortableHeaders" in result.errors[0]
        assert result.credentials_required == [{"type": "tools", "identifier": "valid"}]
    stored = registry.scalars(select(Tool)).one()
    assert stored.headers == {"X-Region": "eu"}
    assert stored.url == "https://example.com/api?code=region-code"


@pytest.mark.asyncio
async def test_full_and_selected_portable_references(registry, importer, tmp_path):
    """Export real tool bindings and exclude auth fields in both file forms."""
    await importer.import_configuration(
        registry,
        envelope(
            tools=[
                tool(
                    "local",
                    id="local-source",
                    url="https://example.com/upstream?region=eu&token=example-file-token",
                    headers={"Content-Type": "application/json", "ApiToken": "example-file-token", "X-Region": "eu"},
                )
            ],
            servers=[{"name": "bound", "tool_ids": ["local-source"]}],
        ),
        imported_by=ACTOR,
    )
    row = registry.scalars(select(Tool)).one()
    row.auth_type = "bearer"
    row.auth_value = encode_auth({"Authorization": "Bearer example-test-token"})
    server = registry.scalars(select(Server)).one()
    registry.commit()
    exporter = ExportService()
    full = await exporter.export_configuration(registry, include_types=["tools", "servers"])
    selective = await exporter.export_selective(registry, {"tools": [row.id], "servers": [server.id]})
    for sequence, data in enumerate((full, selective)):
        assert data["contextforge_version"]
        exported = data["entities"]["tools"][0]
        assert exported["id"] == row.id
        assert "auth_value" not in exported
        assert exported["headers"] == {"Content-Type": "application/json", "X-Region": "eu"}
        assert exported["url"] == "https://example.com/upstream?region=eu"
        assert data["entities"]["servers"][0]["tool_refs"] == [{"id": row.id, "original_name": "local"}]
        dest_engine = create_engine(f"sqlite:///{tmp_path / f'destination-{sequence}.db'}")
        Base.metadata.create_all(dest_engine)
        with Session(dest_engine) as destination:
            destination.add(EmailUser(email=ACTOR, password_hash="unused", full_name="Importer"))
            destination.flush()
            destination.add(EmailTeam(id="new-personal", name="Personal", slug="personal", created_by=ACTOR, is_personal=True))
            destination.flush()
            destination.add(EmailTeamMember(team_id="new-personal", user_email=ACTOR, role="owner"))
            destination.commit()
            status = await importer.import_configuration(destination, data, imported_by=ACTOR)
            assert status.created_entities == 2 and not status.warnings
            restored_tool = destination.scalars(select(Tool)).one()
            assert restored_tool.id != row.id
            assert restored_tool.url == "https://example.com/upstream?region=eu"
            assert destination.scalars(select(Server)).one().tools == [restored_tool]
        dest_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("selective", [False, True])
@pytest.mark.parametrize("visibility", ["private", "disabled"])
async def test_filtered_export_preserves_existing_tool_bindings(registry, importer, selective, visibility):
    """Keep all bindings when an export contains only part of a server's tool list."""
    await importer.import_configuration(
        registry,
        envelope(tools=[tool("visible", id="file-visible"), tool("filtered", id="file-filtered")], servers=[{"name": "bound", "tool_ids": ["file-visible", "file-filtered"]}]),
        imported_by=ACTOR,
    )
    hidden = registry.scalar(select(Tool).where(Tool.original_name == "filtered"))
    if visibility == "private":
        other = EmailUser(email="other@example.com", password_hash="unused", full_name="Other owner")
        registry.add(other)
        registry.flush()
        hidden.visibility = "private"
        hidden.owner_email = other.email
    else:
        hidden.enabled = False
    server = registry.scalars(select(Server)).one()
    registry.commit()

    exporter = ExportService()
    if selective:
        exported = await exporter.export_selective(registry, {"servers": [server.id]}, user_email=ACTOR)
    else:
        exported = await exporter.export_configuration(registry, include_types=["servers"], user_email=ACTOR)
    [data] = exported["entities"]["servers"]
    assert data["tool_refs_complete"] is False
    assert "tool_ids" not in data
    assert [ref["original_name"] for ref in data["tool_refs"]] == ["visible"]
    visible_ids = [ref["id"] for ref in data["tool_refs"]]
    preview = await importer.preview_import(registry, exported, imported_by=ACTOR)
    assert preview["items"]["servers"][0]["dependencies"]["tools"] == visible_ids
    assert preview["dependencies"]["bound"]["requires"]["tools"] == visible_ids

    result = await importer.import_configuration(registry, exported, imported_by=ACTOR)
    assert result.updated_entities == 1
    assert any("omitted some tool bindings" in warning for warning in result.warnings)
    assert {bound.original_name for bound in registry.scalars(select(Server)).one().tools} == {"visible", "filtered"}

    await importer.import_configuration(registry, envelope(servers=[{"name": "bound", "tool_refs": []}]), imported_by=ACTOR)
    assert registry.scalars(select(Server)).one().tools == []


@pytest.mark.asyncio
async def test_root_notifications_and_other_entity_strategies(registry, importer, monkeypatch):
    """Exercise root updates, skip, and rename together with resources and prompts."""
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    notices = []

    async def notify(event):
        notices.append(event["type"])

    monkeypatch.setattr(importer.root_service, "notify_import_root", notify)
    configuration = envelope(
        roots=[{"name": "root", "uri": "https://example.com/root"}],
        resources=[{"name": "local-resource", "uri": "https://example.com/report.json", "content": "{}"}],
        prompts=[{"name": "local-prompt", "template": "Write a summary"}],
    )
    created = await importer.import_configuration(registry, configuration, imported_by=ACTOR)
    assert (created.created_entities, created.failed_entities) == (3, 0)
    skipped = await importer.import_configuration(registry, configuration, imported_by=ACTOR, conflict_strategy=ConflictStrategy.SKIP)
    assert skipped.skipped_entities == 3
    configuration["entities"]["roots"][0]["name"] = "renamed"
    configuration["entities"]["resources"][0]["description"] = "resource change"
    configuration["entities"]["prompts"][0]["template"] = "Write a short summary"
    updated = await importer.import_configuration(registry, configuration, imported_by=ACTOR)
    assert (updated.updated_entities, updated.failed_entities) == (3, 0)
    assert registry.scalars(select(Resource.description)).one() == "resource change"
    assert registry.scalars(select(Prompt.template)).one() == "Write a short summary"
    assert [root.name for root in await importer.root_service.list_roots()] == ["renamed"]
    renamed = await importer.import_configuration(registry, configuration, imported_by=ACTOR, conflict_strategy=ConflictStrategy.RENAME)
    assert (renamed.created_entities, renamed.failed_entities) == (2, 1)
    assert notices == ["root_added", "root_updated"]


@pytest.mark.asyncio
async def test_notification_failures_preserve_committed_import(registry, importer, monkeypatch):
    """Report delivery failures without losing the root and tool committed by import."""
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])

    def fail_dataplane_notification():
        raise RuntimeError("data plane unavailable")

    async def fail_root_notification(_event):
        raise RuntimeError("root subscriber unavailable")

    monkeypatch.setattr("mcpgateway.services.tool_service.notify_dataplane", fail_dataplane_notification)
    monkeypatch.setattr(importer.root_service, "notify_import_root", fail_root_notification)
    config = envelope(roots=[{"name": "published", "uri": "https://example.com/root"}], tools=[tool("committed")])

    result = await importer.import_configuration(registry, config, imported_by=ACTOR)

    assert result.status == "completed"
    assert (result.created_entities, result.failed_entities) == (2, 0)
    assert "Registry notification or cache update failed after commit" in result.warnings
    assert "Root change notification failed after commit" in result.warnings
    assert [root.name for root in await importer.root_service.list_roots()] == ["published"]
    with Session(registry.get_bind()) as reader:
        assert reader.scalars(select(Tool.original_name)).all() == ["committed"]


@pytest.mark.asyncio
async def test_federated_reference_resolves_only_the_intended_gateway(registry, importer, monkeypatch):
    """Match a portable reference through discovery rather than a repeated tool name."""

    async def initialize(url, *args, **kwargs):
        remote_tool = ToolCreate(name="shared", url=url, integration_type="REST", request_type="GET")
        resources = [ResourceCreate(name="report", uri="https://example.com/report.txt", content="")]
        prompts = [PromptCreate(name="summarize", template="Write a summary")]
        return {}, [remote_tool], resources, prompts, [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    for name, url in (("left", "https://left.example.com/mcp"), ("right", "https://right.example.com/mcp")):
        gateway_file = envelope(gateways=[{"name": name, "url": url, "id": name, "transport": "STREAMABLEHTTP"}])
        result = await importer.import_configuration(registry, gateway_file, imported_by=ACTOR, selected_entities={"gateways": []})
        assert (result.total_entities, result.created_entities) == (1, 1)
    assert len(registry.scalars(select(Resource)).all()) == 2
    assert len(registry.scalars(select(Prompt)).all()) == 2
    reference = {"id": "old-tool-id", "original_name": "shared", "gateway_id": "old-gateway-id", "gateway_name": "right", "gateway_url": "https://right.example.com/mcp"}
    server = envelope(servers=[{"name": "bound", "tool_refs": [reference]}])
    preview = await importer.preview_import(registry, server, imported_by=ACTOR)
    assert not preview["outcomes"]["warnings"]
    result = await importer.import_configuration(registry, server, imported_by=ACTOR)
    assert result.created_entities == 1
    bound = registry.scalars(select(Server)).one()
    assert [binding.gateway.name for binding in bound.tools] == ["right"]
    reference["gateway_name"] = "missing"
    result = await importer.import_configuration(registry, server, imported_by=ACTOR)
    assert result.updated_entities == 1 and result.warnings
    assert [binding.gateway.name for binding in registry.scalars(select(Server)).one().tools] == ["right"]


@pytest.mark.asyncio
async def test_gateway_origin_change_does_not_reuse_credentials(registry, importer, monkeypatch):
    """Save the new gateway URL and block connection preparation until reconfigured."""
    calls = []

    async def initialize(url, *args, **kwargs):
        calls.append(url)
        return {}, [], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    config = envelope(gateways=[{"name": "redirected", "url": "https://first.example.com/mcp", "transport": "STREAMABLEHTTP"}])
    initial = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert initial.created_entities == 1
    row = registry.scalars(select(Gateway)).one()
    row.auth_type = "bearer"
    row.auth_value = {"Authorization": "Bearer example-test-token"}
    row.add_headers = {"ApiToken": "example-static-token"}
    registry.commit()
    config["entities"]["gateways"][0]["url"] = "https://second.example.com/mcp"
    result = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert (result.updated_entities, result.failed_entities) == (1, 0)
    assert result.credentials_required == [{"type": "gateways", "identifier": "redirected"}]
    row = registry.scalars(select(Gateway)).one()
    assert row.url == "https://second.example.com/mcp"
    assert row.auth_type is None and row.auth_value is None and row.status == "pending"
    assert row.add_headers is None
    await importer.gateway_service._check_single_gateway_health(row)
    assert calls == ["https://first.example.com/mcp"]


@pytest.mark.asyncio
async def test_preview_matches_selection_and_reports_failed_analysis(registry, importer, monkeypatch):
    """Use the same local analysis without presenting a failed check as no conflict."""
    configuration = envelope(tools=[tool("valid")], servers=[{"name": "unselected"}])
    first = await importer.preview_import(registry, configuration, imported_by=ACTOR, selected_entities={"tools": []})
    assert first["summary"] == {"total_items": 1, "by_type": {"tools": 1, "servers": 0}}
    assert first["items"]["tools"][0]["outcome"] == "created"

    def failed_lookup(*args, **kwargs):
        raise RuntimeError("database lookup unavailable")

    monkeypatch.setattr(importer, "_destination_index", failed_lookup)
    with pytest.raises(RuntimeError, match="database lookup unavailable"):
        await importer.preview_import(registry, configuration, imported_by=ACTOR)


@pytest.mark.asyncio
async def test_legacy_in_file_gateway_name_resolves_new_discovery(registry, importer, monkeypatch):
    """Resolve discovery from a selected gateway that has no file ID."""

    async def initialize(url, *args, **kwargs):
        return {}, [ToolCreate(name="legacy-tool", url=url, integration_type="REST", request_type="GET")], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    config = envelope(
        gateways=[{"name": "legacy-gateway", "url": "https://legacy.example.com/mcp", "transport": "STREAMABLEHTTP"}],
        servers=[{"name": "legacy-server", "tool_refs": [{"original_name": "legacy-tool", "gateway_name": "legacy-gateway"}]}],
    )
    result = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert result.created_entities == 2 and not result.warnings
    assert registry.scalars(select(Server)).one().tools[0].gateway.name == "legacy-gateway"


@pytest.mark.asyncio
async def test_new_gateway_federated_tool_preview_requires_discovery(registry, importer, monkeypatch):
    """Keep undiscovered tools unresolved in preview and bind them after discovery."""
    url = "https://discovery.example.com/mcp"
    discovery_calls = []

    async def initialize(url, *args, **kwargs):
        discovery_calls.append(url)
        return {}, [ToolCreate(name="echo", url=url, integration_type="REST", request_type="GET")], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    reference = {"id": "source-tool", "original_name": "echo", "gateway_id": "source-gateway"}
    config = envelope(
        gateways=[{"id": "source-gateway", "name": "discovery", "url": url, "transport": "STREAMABLEHTTP"}],
        tools=[tool("echo", id="source-tool", gateway_id="source-gateway")],
        servers=[{"name": "server", "tool_refs": [reference]}],
    )
    preview = await importer.preview_import(registry, config, imported_by=ACTOR)
    dry = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=True)
    assert preview["outcomes"]["progress"] == dry.to_dict()["progress"] == {"total": 3, "processed": 3, "created": 2, "updated": 0, "skipped": 0, "failed": 0, "unknown": 1}
    assert preview["items"]["tools"][0]["outcome"] == "unknown"
    assert preview["items"]["tools"][0]["conflicts_with"] is None
    assert any("Unresolved tool references" in warning for warning in dry.warnings)
    assert not discovery_calls
    assert all(registry.scalar(select(model.id)) is None for model in (Gateway, Tool, Server))
    result = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert discovery_calls == [url]
    assert (result.created_entities, result.updated_entities, result.failed_entities, result.unknown_entities) == (2, 1, 0, 0)
    assert registry.scalars(select(Server)).one().tools[0].original_name == "echo"


@pytest.mark.asyncio
async def test_credential_blocked_gateway_skips_dependents_until_discovery(registry, importer, monkeypatch):
    """Protect bindings while credentials block discovery and resolve them after recovery."""
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)
    url = "https://example.com/mcp"
    uri = "https://example.com/report.txt"
    discovery_calls = []

    async def initialize(url, *args, **kwargs):
        discovery_calls.append(url)
        discovered_tool = ToolCreate(name="echo", url=url, integration_type="REST", request_type="GET")
        return {}, [discovered_tool], [ResourceCreate(name="report", uri=uri, content="fixture")], [PromptCreate(name="lookup", template="Fixture")], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    initial = envelope(tools=[tool("unrelated", id="prior")], servers=[{"name": "server", "tool_ids": ["prior"]}])
    await importer.import_configuration(registry, initial, imported_by=ACTOR)
    unrelated_id = registry.scalar(select(Tool.id))
    gateway_ref = {"gateway_id": "source-gateway"}
    config = envelope(
        gateways=[{"id": "source-gateway", "name": "blocked", "url": url, "transport": "STREAMABLEHTTP", "credentials_required": True}],
        tools=[tool("echo", id=unrelated_id, **gateway_ref)],
        resources=[{"name": "report", "uri": uri, **gateway_ref}],
        prompts=[{"name": "lookup", "template": "Fixture", **gateway_ref}],
        servers=[{"name": "server", "tool_ids": [unrelated_id]}],
    )
    fresh = await importer.preview_import(registry, config, imported_by=ACTOR)
    assert fresh["outcomes"]["progress"]["unknown"] == 3
    assert registry.scalar(select(Gateway.id)) is None
    pending = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert (pending.created_entities, pending.skipped_entities, pending.failed_entities) == (1, 3, 0)
    assert pending.credentials_required == [{"type": "gateways", "identifier": "blocked"}]
    for kind in ("tools", "resources", "prompts"):
        assert pending.items[kind][0]["outcome"] == "skipped"
        assert any(warning.startswith(f"{kind} item") and "gateway has credentials" in warning for warning in pending.warnings)
    assert any("Unresolved tool references" in warning for warning in pending.warnings)
    assert [binding.id for binding in registry.scalars(select(Server)).one().tools] == [unrelated_id]
    preview = await importer.preview_import(registry, config, imported_by=ACTOR)
    assert preview["outcomes"]["progress"]["skipped"] == 3
    assert preview["outcomes"]["progress"]["failed"] == 0
    invalid = envelope(gateways=config["entities"]["gateways"], resources=[{"name": "invalid", "uri": "", **gateway_ref}])
    preview = await importer.preview_import(registry, invalid, imported_by=ACTOR)
    assert preview["items"]["resources"][0]["outcome"] == "failed"
    assert not discovery_calls

    gateway_id = registry.scalar(select(Gateway.id))
    await importer.gateway_service.update_gateway(registry, gateway_id, GatewayUpdate(auth_type="bearer", auth_token="example-test-token"), user_email=ACTOR)
    result = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert (result.updated_entities, result.skipped_entities, result.failed_entities) == (5, 0, 0)
    assert not result.warnings
    [binding] = registry.scalars(select(Server)).one().tools
    assert (binding.original_name, binding.gateway_id) == ("echo", gateway_id)


@pytest.mark.asyncio
async def test_unknown_federated_tool_does_not_bind_unrelated_destination_id(registry, importer):
    """Keep a legacy reference unresolved when the file tool needs discovery."""
    await importer.import_configuration(registry, envelope(tools=[tool("unrelated")]), imported_by=ACTOR)
    tool_id = registry.scalar(select(Tool.id))
    url = "https://discovery.example.com/mcp"
    config = envelope(
        gateways=[{"id": "source-gateway", "name": "discovery", "url": url, "transport": "STREAMABLEHTTP"}],
        tools=[tool("echo", id=tool_id, url=url, integration_type="MCP", request_type="STREAMABLEHTTP", gateway_id="source-gateway")],
        servers=[{"name": "server", "tool_ids": [tool_id]}],
    )
    status = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=True)
    assert status.unknown_entities == 1
    assert any("Unresolved tool references" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_new_gateway_preview_still_reports_local_federated_errors(registry, importer):
    """Reject a mismatched gateway reference and malformed tool update locally."""
    config = envelope(
        gateways=[{"id": "source-gateway", "name": "discovery", "url": "https://discovery.example.com/mcp", "transport": "STREAMABLEHTTP"}],
        tools=[
            tool("wrong-gateway", gateway_id="source-gateway", gateway_name="other"),
            tool("bad-request-type", gateway_id="source-gateway", request_type="INVALID"),
        ],
    )
    result = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=True)
    assert (result.created_entities, result.failed_entities, result.unknown_entities) == (1, 2, 0)


@pytest.mark.asyncio
async def test_duplicate_gateway_fail_and_dry_run_conflict(registry, importer, monkeypatch):
    """Use the service's duplicate-endpoint comparator without making preview network calls."""

    async def initialize(*_args, **_kwargs):
        return {}, [], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    first = {"name": "first", "url": "https://dup.example.com/mcp", "transport": "STREAMABLEHTTP"}
    second = {**first, "name": "second"}
    repeated = await importer.import_configuration(registry, envelope(gateways=[first, first]), imported_by=ACTOR, dry_run=True)
    assert (repeated.created_entities, repeated.updated_entities, repeated.failed_entities) == (1, 1, 0)
    for dry_run in (True, False):
        with pytest.raises(ImportConflictError):
            await importer.import_configuration(registry, envelope(gateways=[first, second]), conflict_strategy=ConflictStrategy.FAIL, imported_by=ACTOR, dry_run=dry_run)
        assert registry.scalars(select(Gateway)).all() == []


@pytest.mark.asyncio
async def test_tool_binding_rechecks_gateway_visibility_after_analysis(registry, importer, monkeypatch):
    """Apply the gateway's visibility at write time even when the tool stays public."""

    async def initialize(url, *args, **kwargs):
        return {}, [ToolCreate(name="upstream-tool", url=url, integration_type="REST", request_type="GET")], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    config = envelope(gateways=[{"name": "upstream", "url": "https://upstream.example.com/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"}])
    await importer.import_configuration(registry, config, imported_by=ACTOR)
    gateway = registry.scalars(select(Gateway)).one()
    tool_id = registry.scalars(select(Tool.id)).one()
    original = importer._destination_index

    def make_gateway_private(db, selected, token_teams, actor):
        index = original(db, selected, token_teams, actor)
        db.execute(update(Gateway).where(Gateway.id == gateway.id).values(visibility="private", owner_email="other@example.com").execution_options(synchronize_session=False))
        return index

    monkeypatch.setattr(importer, "_destination_index", make_gateway_private)
    result = await importer.import_configuration(registry, envelope(servers=[{"name": "virtual", "tool_ids": [tool_id]}]), imported_by=ACTOR, token_teams=["personal"])
    assert result.created_entities == 1 and result.warnings
    assert registry.scalars(select(Server)).one().tools == []


@pytest.mark.asyncio
async def test_dry_run_loads_destination_tool_candidates_once(registry, importer):
    """Keep destination list query count independent of the number of file tools."""
    counts = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().startswith("SELECT") and "FROM tools" in statement:
            counts[-1] += 1

    engine = registry.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for size in (1, 16):
            counts.append(0)
            data = envelope(tools=[tool(f"sample-{index}") for index in range(size)])
            status = await importer.import_configuration(registry, data, imported_by=ACTOR, dry_run=True)
            assert status.created_entities == size
        assert counts == [1, 1]
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.asyncio
async def test_repeat_import_discovers_tools_with_async_lifecycle_enabled(registry, importer, monkeypatch):
    """Resolve same-file references after an import updates the gateway's discovered catalog."""
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

    async def initialize(url, *args, **kwargs):
        name = "latest" if url.endswith("/latest") else "early"
        return {}, [ToolCreate(name=name, url=url, integration_type="REST", request_type="GET")], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    gateway = {"id": "file-gw", "name": "repeat", "url": "https://example.com/early", "transport": "STREAMABLEHTTP"}
    first = await importer.import_configuration(registry, envelope(gateways=[gateway]), imported_by=ACTOR)
    assert first.created_entities == 1
    gateway["url"] = "https://example.com/latest"
    cfg = envelope(gateways=[gateway], servers=[{"name": "late-bound", "tool_refs": [{"original_name": "latest", "gateway_id": "file-gw"}]}])
    result = await importer.import_configuration(registry, cfg, imported_by=ACTOR)
    assert (result.created_entities, result.updated_entities, result.failed_entities) == (1, 1, 0)
    assert [bound.original_name for bound in registry.scalars(select(Server)).one().tools] == ["latest"]


@pytest.mark.asyncio
async def test_unexpected_gateway_catalog_failure_rolls_back_import(registry, importer, monkeypatch):
    """Abort the import if gateway catalog reconciliation raises unexpectedly."""
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)

    async def initialize(url, *args, **kwargs):
        return {}, [], [], [], [], None

    monkeypatch.setattr(importer.gateway_service, "_initialize_gateway", initialize)
    gateway = {"name": "reconcile", "url": "https://example.com/old", "transport": "STREAMABLEHTTP"}
    initial = await importer.import_configuration(registry, envelope(gateways=[gateway]), imported_by=ACTOR)
    assert initial.created_entities == 1

    def fail_reconcile(*args, **kwargs):
        kwargs["gateway"].status_message = "partial catalog change"
        raise RuntimeError("catalog failed")

    monkeypatch.setattr(importer.gateway_service, "_reconcile_gateway_catalog", fail_reconcile)
    gateway["url"] = "https://example.com/new"
    with pytest.raises(RuntimeError, match="catalog failed"):
        await importer.import_configuration(registry, envelope(gateways=[gateway]), imported_by=ACTOR)

    stored = registry.scalars(select(Gateway)).one()
    assert stored.url == "https://example.com/old"
    assert stored.status_message != "partial catalog change"
