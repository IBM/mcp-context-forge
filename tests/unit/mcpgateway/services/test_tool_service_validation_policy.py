# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for applying the tool validation policy in the tool service.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock
from urllib.parse import urlparse

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services import tool_service as tool_service_module
from mcpgateway.services.tool_service import ToolService, ToolValidationError

REASON = "denied by the global validation policy"
REFUSAL = f"Tool 'build' {REASON}"


@pytest.fixture(autouse=True)
def strict_defaults(monkeypatch):
    """Run in-process, strict, with the shipped global pattern list plus a marker.

    The marker lets a test reach the policy hook: the content security scanner
    rejects shell operators such as ``&&`` on the API paths before the policy runs.
    """
    monkeypatch.setattr(settings, "cel_execution", "inprocess")
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["&&", "||", "$(", "denymarker"])


@pytest.fixture
def tool_service(monkeypatch):
    """A ToolService that never resolves hostnames."""

    async def validate_without_pinning(value: str, _field_name: str = "URL"):
        parsed = urlparse(value)
        return {"validated_url": value, "hostname": parsed.hostname, "original_authority": parsed.netloc, "resolved_ip": None}

    monkeypatch.setattr("mcpgateway.services.tool_service.SecurityValidator.validate_url_for_connection_pinning", validate_without_pinning)
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", False)
    return ToolService()


def _tool_create(description: str, **extra) -> ToolCreate:
    """Build a REST tool with the given description."""
    return ToolCreate(name="build", url="http://example.com/tools/build", description=description, integration_type="REST", request_type="POST", **extra)


def _mock_session() -> MagicMock:
    """A session whose queries find nothing and whose writes are recorded."""
    db = MagicMock()
    result = Mock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    db.execute = Mock(return_value=result)
    return db


# --- gateway policy lookup ----------------------------------------------------


def test_gateway_policy_lookup_reads_the_stored_column(tool_service, test_db):
    """The helper returns the gateway's policy text through a real session."""
    test_db.add(DbGateway(id="gw-policy", name="policy gw", slug="policy-gw", url="http://upstream.example.com", capabilities={}, tool_validation_policy="true"))
    test_db.add(DbGateway(id="gw-plain", name="plain gw", slug="plain-gw", url="http://upstream.example.com/2", capabilities={}))
    test_db.commit()
    try:
        assert tool_service._gateway_tool_validation_policy(test_db, "gw-policy") == "true"  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, "gw-plain") is None  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, "missing") is None  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, None) is None  # pylint: disable=protected-access
    finally:
        test_db.query(DbGateway).filter(DbGateway.id.in_(["gw-policy", "gw-plain"])).delete(synchronize_session=False)
        test_db.commit()


def test_gateway_policy_lookup_ignores_non_text(tool_service):
    """A mocked query result that is not text never becomes a policy."""
    assert tool_service._gateway_tool_validation_policy(_mock_session(), MagicMock()) is None  # pylint: disable=protected-access


# --- register_tool -------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_tool_refuses_when_global_policy_denies(tool_service):
    """A description the global policy denies is refused before anything is written."""
    db = _mock_session()
    with pytest.raises(ToolValidationError, match="global validation policy"):
        await tool_service.register_tool(db, _tool_create("please denymarker this"))
    db.add.assert_not_called()
    db.rollback.assert_called()


@pytest.mark.asyncio
async def test_register_tool_passes_tool_and_gateway_policies(tool_service, monkeypatch):
    """The hook hands the schema's policy and the gateway's stored policy to the resolver."""
    admit = Mock(return_value=REASON)
    monkeypatch.setattr(tool_service_module, "admit_tool", admit)
    monkeypatch.setattr(tool_service, "_gateway_tool_validation_policy", Mock(return_value="false"))
    with pytest.raises(ToolValidationError, match=REFUSAL):
        await tool_service.register_tool(_mock_session(), _tool_create("plain", gateway_id="gw-1", tool_validation_policy="true"))
    admit.assert_called_once_with(description="plain", tool_name="build", tool_policy="true", gateway_policy="false", context="register_tool")


# --- update_tool ---------------------------------------------------------------


def _existing_tool() -> MagicMock:
    """A stored tool as update_tool loads it."""
    tool = MagicMock()
    tool.id = "tool-1"
    tool.original_name = "build"
    tool.custom_name = "build"
    tool.name = "build"
    tool.description = "old description"
    tool.original_description = "old description"
    tool.gateway_id = None
    tool.tool_validation_policy = None
    tool.validation_refusal = None
    tool.enabled = True
    tool.visibility = "public"
    tool.team_id = None
    tool.owner_email = None
    return tool


@pytest.mark.asyncio
async def test_update_tool_rechecks_a_changed_description(tool_service, monkeypatch):
    """Updating the description runs the policy over the new text; a refusal saves the edit and disables the tool."""
    admit = Mock(return_value=REASON)
    monkeypatch.setattr(tool_service_module, "admit_tool", admit)
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(description="new description")) == "tool_read"
    admit.assert_called_once_with(description="new description", tool_name="build", tool_policy=None, gateway_policy=None, context="update_tool")
    assert (tool.description, tool.enabled, tool.validation_refusal) == ("new description", False, REASON)


@pytest.mark.asyncio
async def test_update_tool_rechecks_when_policy_is_cleared(tool_service, monkeypatch):
    """Clearing a per-tool policy re-evaluates the stored description under the inherited policy."""
    admit = Mock(return_value=None)
    monkeypatch.setattr(tool_service_module, "admit_tool", admit)
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    tool.tool_validation_policy = "true"
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy=None))
    assert tool.tool_validation_policy is None
    admit.assert_called_once_with(description="old description", tool_name="build", tool_policy=None, gateway_policy=None, context="update_tool")


@pytest.mark.asyncio
async def test_update_tool_lifts_a_stored_refusal_when_the_check_passes(tool_service, monkeypatch):
    """Granting a tool-level policy to a refused tool clears the refusal and re-enables it."""
    monkeypatch.setattr(tool_service_module, "admit_tool", Mock(return_value=None))
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    tool.enabled = False
    tool.validation_refusal = "denied by the gateway-level validation policy"
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy="true"))
    assert tool.validation_refusal is None
    assert tool.enabled is True


@pytest.mark.asyncio
async def test_update_tool_checks_the_upstream_text_behind_a_customised_description(tool_service, monkeypatch):
    """A policy change is judged on the upstream text too, so the result matches what the next refresh would do."""
    admit = Mock(side_effect=lambda description, **_: REASON if description == "upstream && dirty" else None)
    monkeypatch.setattr(tool_service_module, "admit_tool", admit)
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    tool.description = "clean custom text"
    tool.original_description = "upstream && dirty"
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy='!description.contains("$(")'))
    assert [call.kwargs["description"] for call in admit.call_args_list] == ["clean custom text", "upstream && dirty"]
    assert (tool.enabled, tool.validation_refusal) == (False, REASON)


@pytest.mark.asyncio
async def test_update_tool_saves_a_policy_change_that_refuses_the_tool_and_disables_it(tool_service, monkeypatch):
    """Withdrawing an exemption saves; the tool is disabled with the inherited reason instead of the edit being rejected."""
    reason = "denied by the gateway-level validation policy"
    monkeypatch.setattr(tool_service_module, "admit_tool", Mock(return_value=reason))
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    tool.tool_validation_policy = 'tool_name == "build"'
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy=None)) == "tool_read"
    assert tool.tool_validation_policy is None
    assert (tool.enabled, tool.validation_refusal) == (False, reason)


@pytest.mark.asyncio
async def test_update_tool_never_rejects_an_edit_for_the_policy(tool_service, monkeypatch):
    """A refusal during an edit is recorded on the row, so the edit itself goes through even for a form that resubmits every field."""
    reason = "denied by the gateway-level validation policy"
    monkeypatch.setattr(tool_service_module, "admit_tool", Mock(return_value=reason))
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    tool = _existing_tool()
    tool.tool_validation_policy = 'tool_name == "build"'
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(description="old description", tool_validation_policy=None)) == "tool_read"
    assert (tool.tool_validation_policy, tool.enabled, tool.validation_refusal) == (None, False, reason)


# --- set_tool_state --------------------------------------------------------------


@pytest.mark.asyncio
async def test_refused_tool_cannot_be_enabled_by_hand(tool_service, monkeypatch):
    """The toggle refuses to enable a tool the policy disabled and names the policy as the fix."""
    tool = _existing_tool()
    tool.enabled = False
    tool.validation_refusal = REASON
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    db = _mock_session()
    with pytest.raises(ToolValidationError, match=f"Tool 'build' cannot be enabled: {REASON}. Change the validation policy, then refresh the gateway."):
        await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)
    assert tool.enabled is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_refused_tool_can_still_be_disabled_by_hand(tool_service, monkeypatch):
    """Deactivating a refused tool is a no-op that does not raise."""
    tool = _existing_tool()
    tool.enabled = False
    tool.reachable = False
    tool.validation_refusal = REASON
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    assert await tool_service.set_tool_state(_mock_session(), "tool-1", activate=False, reachable=False) == "tool_read"


@pytest.mark.asyncio
async def test_update_tool_skips_policy_when_neither_field_changes(tool_service, monkeypatch):
    """An update that touches neither the description nor the policy does not re-evaluate."""
    admit = Mock(return_value=REFUSAL)
    monkeypatch.setattr(tool_service_module, "admit_tool", admit)
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=_existing_tool()))
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(title="New title"))
    admit.assert_not_called()


# --- bulk registration ---------------------------------------------------------


def _bulk_kwargs() -> dict:
    """Arguments the bulk chunk passes for every tool."""
    return {
        "existing_tools_map": {},
        "conflict_strategy": "skip",
        "visibility": "public",
        "team_id": None,
        "owner_email": "owner@example.com",
        "created_by": "owner@example.com",
        "created_from_ip": None,
        "created_via": "import",
        "created_user_agent": None,
        "import_batch_id": None,
        "federation_source": None,
    }


def test_bulk_refuses_a_denied_tool_as_a_failed_row(tool_service):
    """Bulk import records the refusal against the row instead of raising."""
    result = tool_service._process_single_tool_for_bulk(tool=_tool_create("please denymarker this"), **_bulk_kwargs())  # pylint: disable=protected-access
    assert result == {"status": "fail", "error": REFUSAL}
    assert REFUSAL == "Tool 'build' denied by the global validation policy"


def test_bulk_uses_the_gateway_policy_it_is_given(tool_service):
    """The chunk looks up the gateway policy once and the row honours it."""
    result = tool_service._process_single_tool_for_bulk(tool=_tool_create("please denymarker this"), gateway_policy='!description.contains("$(")', **_bulk_kwargs())  # pylint: disable=protected-access
    assert result["status"] == "add"
