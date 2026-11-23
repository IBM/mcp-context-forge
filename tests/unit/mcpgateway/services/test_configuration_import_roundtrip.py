# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_configuration_import_roundtrip.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise import transaction, matching, and portable associations against SQLite.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.schemas import GatewayUpdate, PromptCreate, ResourceCreate, ToolCreate
from mcpgateway.services.export_service import ExportService
from mcpgateway.services.import_service import ConflictStrategy, ImportConflictError, ImportService, ImportValidationError
from mcpgateway.services.root_service import RootService

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
async def test_fatal_conflict_restores_rows_and_roots(registry, importer, monkeypatch):
    """Undo writes even after nested service commits and keep staged roots private."""
    monkeypatch.setattr(settings, "root_allowed_schemes", ["https"])
    base = await importer.import_configuration(registry, envelope(servers=[{"name": "existing"}]), imported_by=ACTOR)
    assert base.created_entities == 1
    with pytest.raises(ImportConflictError):
        await importer.import_configuration(
            registry,
            envelope(roots=[{"name": "root", "uri": "https://example.com/root"}], tools=[tool("rolled-back")], servers=[{"name": "existing"}]),
            imported_by=ACTOR,
            conflict_strategy=ConflictStrategy.FAIL,
        )
    assert registry.scalar(select(Tool.id)) is None
    assert await importer.root_service.list_roots() == []
    assert registry.scalars(select(Server.name)).all() == ["existing"]


@pytest.mark.asyncio
async def test_dry_run_and_item_failure(registry, importer):
    """Report local outcomes without writes and retain successful items on completion."""
    config = envelope(tools=[tool("good"), tool("invalid", request_type="INVALID")])
    dry = await importer.import_configuration(registry, config, imported_by=ACTOR, dry_run=True)
    assert (dry.created_entities, dry.failed_entities, dry.processed_entities) == (1, 1, 2)
    assert registry.scalar(select(Tool.id)) is None
    real = await importer.import_configuration(registry, config, imported_by=ACTOR)
    assert (real.created_entities, real.failed_entities, real.processed_entities) == (1, 1, 2)
    assert registry.scalars(select(Tool.original_name)).all() == ["good"]


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
        await importer.import_configuration(registry, configuration, rekey_secret="obsolete")


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
