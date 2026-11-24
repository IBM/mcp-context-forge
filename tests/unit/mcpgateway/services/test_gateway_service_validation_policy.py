# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for applying the tool validation policy to gateway-discovered tools.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

# Third-Party
import pytest
from sqlalchemy import select

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import GatewayUpdate, ToolCreate
from mcpgateway.services import gateway_service as gateway_service_module
from mcpgateway.services.gateway_service import GatewayService

GATEWAY_REASON = "denied by the gateway-level validation policy"
GLOBAL_REASON = "denied by the global validation policy"


@pytest.fixture(autouse=True)
def strict_defaults(monkeypatch):
    """Run in-process, strict, with the shipped global pattern list."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["&&", "||", "$("])


@pytest.fixture(autouse=True)
def policy_permission(monkeypatch):
    """Grant the policy permission and capture audit entries; deny-path tests override the grant."""
    grant = AsyncMock()
    audit = Mock()
    monkeypatch.setattr(gateway_service_module, "check_policy_permission", grant)
    monkeypatch.setattr(gateway_service_module, "record_policy_change", audit)
    return grant, audit


@pytest.fixture
def gateway_service():
    """A GatewayService whose HTTP client never reaches the network."""
    service = GatewayService()
    service._http_client = AsyncMock()  # pylint: disable=protected-access
    return service


def _tool(name: str, description: str) -> ToolCreate:
    """Build a discovered tool the way the upstream fetch validates it."""
    return ToolCreate.model_validate({"name": name, "description": description, "inputSchema": {}})


def _gateway_stub(tools=()) -> MagicMock:
    """A gateway record as the sync sees it."""
    gateway = MagicMock()
    gateway.id = "gw-1"
    gateway.name = "gw"
    gateway.url = "http://upstream.example.com"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.tool_validation_policy = None
    gateway.tools = list(tools)
    return gateway


def _existing_row(name: str, *, enabled: bool, validation_refusal) -> MagicMock:
    """A stored tool row as the sync loads it; unrelated fields are mocks and count as changed."""
    row = MagicMock()
    row.original_name = name
    row.enabled = enabled
    row.validation_refusal = validation_refusal
    row.auth_value = None
    return row


def _stored_tool(name: str, description: str, *, gateway_id: str, enabled: bool = True, validation_refusal=None, policy=None) -> DbTool:
    """A persisted discovered tool for real-database tests."""
    return DbTool(
        id=f"tool-{name}",
        original_name=name,
        custom_name=name,
        custom_name_slug=name,
        name=f"{gateway_id}{settings.gateway_tool_name_separator}{name}",
        url="http://upstream.example.com/mcp",
        description=description,
        original_description=description,
        integration_type="MCP",
        request_type="SSE",
        input_schema={"type": "object"},
        gateway_id=gateway_id,
        visibility="public",
        enabled=enabled,
        reachable=enabled,
        validation_refusal=validation_refusal,
        tool_validation_policy=policy,
    )


# --- deciding -------------------------------------------------------------------


def test_global_policy_refuses_and_names_the_reason(gateway_service):
    """With no override, the global list decides and the reason names it."""
    refusals = gateway_service._validation_refusals([_tool("ok", "lists files"), _tool("build", "make && make test")], None, {}, context="unit")  # pylint: disable=protected-access
    assert refusals == {"build": GLOBAL_REASON}


def test_gateway_policy_replaces_global_for_its_tools(gateway_service):
    """A gateway policy that allows the text overrides the global list."""
    assert gateway_service._validation_refusals([_tool("build", "make && make test")], '!description.contains("$(")', {}, context="unit") == {}  # pylint: disable=protected-access


def test_stored_tool_policy_wins_over_gateway_policy(gateway_service):
    """A stored per-tool policy is honoured on refresh ahead of the gateway policy."""
    tools = [_tool("legacy_export", "pipe | example"), _tool("other", "pipe | example")]
    refusals = gateway_service._validation_refusals(tools, '!description.contains("|")', {"legacy_export": "true"}, context="unit")  # pylint: disable=protected-access
    assert refusals == {"other": GATEWAY_REASON}


# --- applying to rows -------------------------------------------------------------


def test_update_or_create_applies_refusals_to_existing_and_new_rows(gateway_service):
    """The sync marks an existing refused tool, clears a recovered one, and creates a refused newcomer disabled."""
    stale = _existing_row("drift", enabled=True, validation_refusal=None)
    recovered = _existing_row("keep", enabled=False, validation_refusal=GLOBAL_REASON)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [stale, recovered]
    gateway = _gateway_stub()
    gateway_service._create_db_tool = Mock(side_effect=lambda **kwargs: SimpleNamespace(original_name=kwargs["tool"].name, enabled=True, validation_refusal=None))  # pylint: disable=protected-access

    added = gateway_service._update_or_create_tools(  # pylint: disable=protected-access
        db,
        [_tool("drift", "x"), _tool("keep", "x"), _tool("new_bad", "x"), _tool("new_ok", "x")],
        gateway,
        "health_check",
        refusals={"drift": GLOBAL_REASON, "new_bad": GATEWAY_REASON},
    )

    assert (stale.enabled, stale.validation_refusal) == (False, GLOBAL_REASON)
    assert (recovered.enabled, recovered.validation_refusal) == (True, None)
    assert {tool.original_name: (tool.enabled, tool.validation_refusal) for tool in added} == {"new_bad": (False, GATEWAY_REASON), "new_ok": (True, None)}


def test_catalog_sync_keeps_refused_tools_and_hands_down_the_reasons(gateway_service, monkeypatch):
    """A refused tool stays in the fetched set, so it is not pruned as stale, and its reason reaches the row update."""
    gateway = _gateway_stub([SimpleNamespace(original_name="keep", tool_validation_policy=None, created_via="system")])
    update = Mock(return_value=[])
    monkeypatch.setattr(gateway_service, "_update_or_create_tools", update)
    monkeypatch.setattr(gateway_service, "_validate_tool_name_collisions", lambda *args, **kwargs: None)

    result = gateway_service._sync_gateway_catalog(  # pylint: disable=protected-access
        MagicMock(),
        gateway=gateway,
        tools=[_tool("keep", "still fine"), _tool("drift", "now has $(whoami) in it")],
        resources=[],
        prompts=[],
        created_via="health_check",
        include_resources=False,
        include_prompts=False,
    )
    assert result.new_tool_names == ["keep", "drift"]
    assert update.call_args.kwargs["refusals"] == {"drift": GLOBAL_REASON}


def test_reapply_policy_rechecks_stored_tools_from_their_saved_text(gateway_service):
    """A policy change is applied to every stored tool from the saved descriptions, honouring per-tool policies."""
    fine = SimpleNamespace(original_name="fine", description="lists files", original_description="lists files", tool_validation_policy=None, enabled=True, validation_refusal=None)
    sql = SimpleNamespace(original_name="sql", description="runs SQL", original_description="runs SQL", tool_validation_policy=None, enabled=True, validation_refusal=None)
    exempt = SimpleNamespace(original_name="exempt", description="runs SQL too", original_description="runs SQL too", tool_validation_policy="true", enabled=True, validation_refusal=None)
    recovered = SimpleNamespace(original_name="recovered", description="plain", original_description="plain", tool_validation_policy=None, enabled=False, validation_refusal=GATEWAY_REASON)
    gateway = _gateway_stub([fine, sql, exempt, recovered])
    gateway.tool_validation_policy = '!description.contains("SQL")'

    gateway_service._reapply_policy_to_stored_tools(gateway)  # pylint: disable=protected-access

    assert (fine.enabled, fine.validation_refusal) == (True, None)
    assert (sql.enabled, sql.validation_refusal) == (False, GATEWAY_REASON)
    assert (exempt.enabled, exempt.validation_refusal) == (True, None)
    assert (recovered.enabled, recovered.validation_refusal) == (True, None)


# --- permission gate ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_gateway_with_a_policy_requires_the_permission(gateway_service, policy_permission, monkeypatch):
    """A caller without validation_policy.manage cannot register a gateway that carries a policy; the upstream is never contacted."""
    grant, _ = policy_permission
    grant.side_effect = PermissionError("Setting a tool validation policy requires the validation_policy.manage permission")
    prepare = AsyncMock()
    monkeypatch.setattr(gateway_service, "_prepare_gateway_registration", prepare)
    db = MagicMock()
    with pytest.raises(PermissionError, match="validation_policy.manage"):
        await gateway_service.register_gateway(db, SimpleNamespace(name="gw", tool_validation_policy="true"), created_by="dev@example.com", team_id="team-1")
    grant.assert_awaited_once_with(db, "dev@example.com", resource_type="gateways", team_id="team-1")
    prepare.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_gateway_policy_change_requires_the_permission(gateway_service, test_db, policy_permission):
    """A caller without validation_policy.manage cannot change a gateway's policy; nothing is saved."""
    grant, audit = policy_permission
    grant.side_effect = PermissionError("Setting a tool validation policy requires the validation_policy.manage permission")
    test_db.add(DbGateway(id="gw-deny", name="deny gw", slug="deny-gw", url="http://upstream.example.com/deny", capabilities={}, enabled=True, reachable=True, team_id="team-1"))
    test_db.commit()
    try:
        with pytest.raises(PermissionError, match="validation_policy.manage"):
            await gateway_service.update_gateway(test_db, "gw-deny", GatewayUpdate(tool_validation_policy="true"), modified_by="dev@example.com")
        grant.assert_awaited_once_with(test_db, "dev@example.com", resource_type="gateways", team_id="team-1")
        test_db.rollback()
        assert test_db.get(DbGateway, "gw-deny").tool_validation_policy is None
        audit.assert_not_called()
    finally:
        test_db.rollback()
        test_db.query(DbGateway).filter(DbGateway.id == "gw-deny").delete(synchronize_session=False)
        test_db.commit()


# --- policy change while the upstream is unreachable ------------------------------------


@pytest.mark.asyncio
async def test_update_gateway_policy_change_rechecks_stored_tools_without_the_upstream(gateway_service, test_db, policy_permission, monkeypatch):
    """Tightening the gateway policy disables stored tools it refuses even when the upstream cannot be reached, and the change is audited."""
    grant, audit = policy_permission
    test_db.add(DbGateway(id="gw-offline", name="offline gw", slug="offline-gw", url="http://upstream.example.com/offline", capabilities={}, enabled=True, reachable=True))
    test_db.add(_stored_tool("fine", "lists files", gateway_id="gw-offline"))
    test_db.add(_stored_tool("sql", "runs SQL", gateway_id="gw-offline"))
    test_db.commit()
    monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(side_effect=RuntimeError("upstream offline")))
    monkeypatch.setattr(gateway_service, "_notify_gateway_updated", AsyncMock())
    try:
        await gateway_service.update_gateway(test_db, "gw-offline", GatewayUpdate(tool_validation_policy='!description.contains("SQL")'), modified_by="admin@example.com")
        states = {tool.original_name: (tool.enabled, tool.validation_refusal) for tool in test_db.execute(select(DbTool).where(DbTool.gateway_id == "gw-offline")).scalars()}
        assert states == {"fine": (True, None), "sql": (False, GATEWAY_REASON)}
        assert test_db.get(DbGateway, "gw-offline").tool_validation_policy == '!description.contains("SQL")'
        grant.assert_awaited_once_with(test_db, "admin@example.com", resource_type="gateways", team_id=None)
        audit.assert_called_once_with(
            resource_type="gateway", resource_id="gw-offline", resource_name="offline gw", team_id=None, user_email="admin@example.com", old=None, new='!description.contains("SQL")'
        )
    finally:
        test_db.rollback()
        test_db.query(DbTool).filter(DbTool.gateway_id == "gw-offline").delete(synchronize_session=False)
        test_db.query(DbGateway).filter(DbGateway.id == "gw-offline").delete(synchronize_session=False)
        test_db.commit()


# --- reactivation --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivating_a_gateway_keeps_refused_tools_disabled(gateway_service, test_db, monkeypatch):
    """Even when discovery fails during reactivation, the bulk enable skips tools the policy refused."""
    test_db.add(DbGateway(id="gw-react", name="react gw", slug="react-gw", url="http://upstream.example.com/react", capabilities={}, enabled=False, reachable=False))
    for name, refusal in (("fine", None), ("bad", GATEWAY_REASON)):
        test_db.add(_stored_tool(name, "x", gateway_id="gw-react", enabled=False, validation_refusal=refusal))
    test_db.commit()
    monkeypatch.setattr(gateway_service, "_initialize_gateway", AsyncMock(side_effect=RuntimeError("upstream offline")))
    monkeypatch.setattr(gateway_service, "_notify_gateway_activated", AsyncMock())
    monkeypatch.setattr(gateway_service, "_notify_gateway_deactivated", AsyncMock())
    try:
        await gateway_service.set_gateway_state(test_db, "gw-react", activate=True)
        states = {tool.original_name: tool.enabled for tool in test_db.execute(select(DbTool).where(DbTool.gateway_id == "gw-react")).scalars()}
        assert states == {"fine": True, "bad": False}
    finally:
        test_db.rollback()
        test_db.query(DbTool).filter(DbTool.gateway_id == "gw-react").delete(synchronize_session=False)
        test_db.query(DbGateway).filter(DbGateway.id == "gw-react").delete(synchronize_session=False)
        test_db.commit()
