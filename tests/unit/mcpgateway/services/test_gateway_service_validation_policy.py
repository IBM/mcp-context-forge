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
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.tool_validation_policy import apply_refusal

GATEWAY_REASON = "denied by the gateway-level validation policy"
GLOBAL_REASON = "denied by the global validation policy"


@pytest.fixture(autouse=True)
def strict_defaults(monkeypatch):
    """Run in-process, strict, with the shipped global pattern list."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["&&", "||", "$("])


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


# --- deciding -------------------------------------------------------------------


def test_global_policy_refuses_and_names_the_reason(gateway_service):
    """A tool the global policy denies is reported by name with the bare reason."""
    refusals = gateway_service._validation_refusals([_tool("ok", "lists files"), _tool("build", "make && make test")], None, {}, context="unit")  # pylint: disable=protected-access
    assert refusals == {"build": GLOBAL_REASON}


def test_gateway_policy_replaces_global_for_its_tools(gateway_service):
    """A gateway override admits what the global rule would refuse."""
    assert gateway_service._validation_refusals([_tool("build", "make && make test")], '!description.contains("$(")', {}, context="unit") == {}  # pylint: disable=protected-access


def test_stored_tool_policy_wins_over_gateway_policy(gateway_service):
    """An operator's per-tool policy is honoured on refresh even though upstream knows nothing of it."""
    tools = [_tool("legacy_export", "pipe | example"), _tool("other", "pipe | example")]
    refusals = gateway_service._validation_refusals(tools, '!description.contains("|")', {"legacy_export": "true"}, context="unit")  # pylint: disable=protected-access
    assert refusals == {"other": GATEWAY_REASON}


def _existing_row(name: str, *, enabled: bool, validation_refusal) -> MagicMock:
    """A stored tool row as the sync loads it; unrelated fields are mocks and count as changed."""
    row = MagicMock()
    row.original_name = name
    row.enabled = enabled
    row.validation_refusal = validation_refusal
    row.auth_value = None
    return row


# --- applying to rows -------------------------------------------------------------


def test_refusal_disables_the_row_and_records_why():
    """A refused tool is switched off with the reason stored beside it."""
    tool = SimpleNamespace(enabled=True, validation_refusal=None)
    apply_refusal(tool, GATEWAY_REASON)
    assert (tool.enabled, tool.validation_refusal) == (False, GATEWAY_REASON)


def test_clearing_a_refusal_re_enables_the_row():
    """A tool the policy refused earlier and now allows comes back on."""
    tool = SimpleNamespace(enabled=False, validation_refusal=GATEWAY_REASON)
    apply_refusal(tool, None)
    assert (tool.enabled, tool.validation_refusal) == (True, None)


def test_operator_disabled_tool_is_left_alone():
    """A tool switched off by hand, never refused, is not touched by an allow decision."""
    tool = SimpleNamespace(enabled=False, validation_refusal=None)
    apply_refusal(tool, None)
    assert (tool.enabled, tool.validation_refusal) == (False, None)


def test_update_or_create_applies_refusals_to_existing_and_new_rows(gateway_service):
    """The sync marks an existing refused tool, clears a recovered one, and creates a refused newcomer disabled."""
    stale = _existing_row("drift", enabled=True, validation_refusal=None)
    recovered = _existing_row("keep", enabled=False, validation_refusal=GLOBAL_REASON)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [stale, recovered]
    gateway = _gateway_stub()
    monkeypatch_create = Mock(side_effect=lambda **kwargs: SimpleNamespace(original_name=kwargs["tool"].name, enabled=True, validation_refusal=None))
    gateway_service._create_db_tool = monkeypatch_create  # pylint: disable=protected-access

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


# --- reactivation --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivating_a_gateway_keeps_refused_tools_disabled(gateway_service, test_db, monkeypatch):
    """Even when discovery fails during reactivation, the bulk enable skips tools the policy refused."""
    test_db.add(DbGateway(id="gw-react", name="react gw", slug="react-gw", url="http://upstream.example.com/react", capabilities={}, enabled=False, reachable=False))
    for name, refusal in (("fine", None), ("bad", GATEWAY_REASON)):
        test_db.add(
            DbTool(
                id=f"tool-{name}",
                original_name=name,
                custom_name=name,
                custom_name_slug=name,
                name=f"react-gw{settings.gateway_tool_name_separator}{name}",
                url="http://upstream.example.com/react",
                integration_type="MCP",
                request_type="SSE",
                input_schema={"type": "object"},
                gateway_id="gw-react",
                visibility="public",
                enabled=False,
                reachable=False,
                validation_refusal=refusal,
            )
        )
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
