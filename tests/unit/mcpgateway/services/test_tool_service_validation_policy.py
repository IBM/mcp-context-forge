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
from mcpgateway.services import tool_validation_policy as policy_module
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


@pytest.fixture(autouse=True)
def policy_permission(monkeypatch):
    """Grant the policy permission and capture audit entries; deny-path tests override the grant."""
    grant = AsyncMock()
    audit = Mock()
    monkeypatch.setattr(tool_service_module, "check_policy_permission", grant)
    monkeypatch.setattr(tool_service_module, "record_policy_change", audit)
    return grant, audit


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
    result.all.return_value = []
    db.execute = Mock(return_value=result)
    return db


# --- gateway policy lookup ----------------------------------------------------


def test_gateway_policy_lookup_reads_the_stored_column(tool_service, test_db):
    """The helpers return the gateway's policy text through a real session, one query for many gateways."""
    test_db.add(DbGateway(id="gw-policy", name="policy gw", slug="policy-gw", url="http://upstream.example.com", capabilities={}, tool_validation_policy="true"))
    test_db.add(DbGateway(id="gw-plain", name="plain gw", slug="plain-gw", url="http://upstream.example.com/2", capabilities={}))
    test_db.commit()
    try:
        assert tool_service._gateway_tool_validation_policy(test_db, "gw-policy") == "true"  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, "gw-plain") is None  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, "missing") is None  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policy(test_db, None) is None  # pylint: disable=protected-access
        assert tool_service._gateway_tool_validation_policies(test_db, ["gw-policy", "gw-plain", "missing", None, 7]) == {"gw-policy": "true"}  # pylint: disable=protected-access
    finally:
        test_db.query(DbGateway).filter(DbGateway.id.in_(["gw-policy", "gw-plain"])).delete(synchronize_session=False)
        test_db.commit()


def test_gateway_policy_lookup_ignores_non_text(tool_service):
    """A gateway id that is not text never reaches the database."""
    db = _mock_session()
    assert tool_service._gateway_tool_validation_policy(db, MagicMock()) is None  # pylint: disable=protected-access
    db.execute.assert_not_called()


# --- register_tool -------------------------------------------------------------


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
        await tool_service.register_tool(_mock_session(), _tool_create("plain", gateway_id="gw-1", tool_validation_policy="true"), created_by="admin@example.com")
    admit.assert_called_once_with(description="plain", tool_name="build", tool_policy="true", gateway_policy="false", context="register_tool")


@pytest.mark.asyncio
async def test_register_tool_with_a_policy_requires_the_permission(tool_service, policy_permission):
    """A caller without validation_policy.manage cannot create a tool that carries a policy."""
    grant, _ = policy_permission
    grant.side_effect = PermissionError("Setting a tool validation policy requires the validation_policy.manage permission")
    db = _mock_session()
    with pytest.raises(PermissionError, match="validation_policy.manage"):
        await tool_service.register_tool(db, _tool_create("plain", tool_validation_policy="true"), created_by="dev@example.com", team_id="team-1")
    grant.assert_awaited_once_with(db, "dev@example.com", resource_type="tools", team_id="team-1")
    db.add.assert_not_called()
    db.rollback.assert_called()


@pytest.mark.asyncio
async def test_register_tool_without_a_policy_needs_no_permission(tool_service, policy_permission, monkeypatch):
    """The gate only guards the policy field."""
    grant, _ = policy_permission
    monkeypatch.setattr(tool_service_module, "admit_tool", Mock(return_value=REASON))
    with pytest.raises(ToolValidationError):
        await tool_service.register_tool(_mock_session(), _tool_create("plain"), created_by="dev@example.com")
    grant.assert_not_awaited()


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


@pytest.fixture
def updating(tool_service, monkeypatch):
    """Prepare update_tool to run against a stored tool and return that tool."""
    tool = _existing_tool()
    monkeypatch.setattr(tool_service, "_notify_tool_updated", AsyncMock())
    monkeypatch.setattr(tool_service, "convert_tool_to_read", Mock(return_value="tool_read"))
    monkeypatch.setattr(tool_service_module, "get_for_update", Mock(return_value=tool))
    return tool


@pytest.mark.asyncio
async def test_update_tool_rechecks_a_changed_description(tool_service, updating, monkeypatch):
    """Updating the description runs the policy over the new text; a refusal saves the edit and disables the tool."""
    admit = Mock(return_value=REASON)
    monkeypatch.setattr(policy_module, "admit_tool", admit)
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(description="new description")) == "tool_read"
    admit.assert_called_once_with(description="new description", tool_name="build", tool_policy=None, gateway_policy=None, context="update_tool")
    assert (updating.description, updating.enabled, updating.validation_refusal) == ("new description", False, REASON)


@pytest.mark.asyncio
async def test_update_tool_rechecks_when_policy_is_cleared(tool_service, updating, monkeypatch):
    """Clearing a per-tool policy re-evaluates the stored description under the inherited policy."""
    admit = Mock(return_value=None)
    monkeypatch.setattr(policy_module, "admit_tool", admit)
    updating.tool_validation_policy = "true"
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy=None))
    assert updating.tool_validation_policy is None
    admit.assert_called_once_with(description="old description", tool_name="build", tool_policy=None, gateway_policy=None, context="update_tool")


@pytest.mark.asyncio
async def test_update_tool_lifts_a_stored_refusal_when_the_check_passes(tool_service, updating, monkeypatch):
    """Granting a tool-level policy to a refused tool clears the refusal and re-enables it."""
    monkeypatch.setattr(policy_module, "admit_tool", Mock(return_value=None))
    updating.enabled = False
    updating.validation_refusal = "denied by the gateway-level validation policy"
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy="true"))
    assert updating.validation_refusal is None
    assert updating.enabled is True


@pytest.mark.asyncio
async def test_update_tool_checks_the_upstream_text_behind_a_customised_description(tool_service, updating, monkeypatch):
    """A policy change is judged on the upstream text too, so the result matches what the next refresh would do."""
    admit = Mock(side_effect=lambda description, **_: REASON if description == "upstream && dirty" else None)
    monkeypatch.setattr(policy_module, "admit_tool", admit)
    updating.description = "clean custom text"
    updating.original_description = "upstream && dirty"
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy='!description.contains("$(")'))
    assert [call.kwargs["description"] for call in admit.call_args_list] == ["clean custom text", "upstream && dirty"]
    assert (updating.enabled, updating.validation_refusal) == (False, REASON)


@pytest.mark.asyncio
async def test_update_tool_saves_a_policy_change_that_refuses_the_tool_and_disables_it(tool_service, updating, monkeypatch):
    """Withdrawing an exemption saves; the tool is disabled with the inherited reason instead of the edit being rejected."""
    reason = "denied by the gateway-level validation policy"
    monkeypatch.setattr(policy_module, "admit_tool", Mock(return_value=reason))
    updating.tool_validation_policy = 'tool_name == "build"'
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy=None)) == "tool_read"
    assert updating.tool_validation_policy is None
    assert (updating.enabled, updating.validation_refusal) == (False, reason)


@pytest.mark.asyncio
async def test_update_tool_never_rejects_an_edit_for_the_policy(tool_service, updating, monkeypatch):
    """A refusal during an edit is recorded on the row, so the edit itself goes through even for a form that resubmits every field."""
    reason = "denied by the gateway-level validation policy"
    monkeypatch.setattr(policy_module, "admit_tool", Mock(return_value=reason))
    updating.tool_validation_policy = 'tool_name == "build"'
    assert await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(description="old description", tool_validation_policy=None)) == "tool_read"
    assert (updating.tool_validation_policy, updating.enabled, updating.validation_refusal) == (None, False, reason)


@pytest.mark.asyncio
async def test_update_tool_policy_change_requires_the_permission(tool_service, updating, policy_permission):
    """A caller without validation_policy.manage cannot change a tool's policy; nothing is saved."""
    grant, audit = policy_permission
    grant.side_effect = PermissionError("Setting a tool validation policy requires the validation_policy.manage permission")
    updating.team_id = "team-1"
    db = _mock_session()
    with pytest.raises(PermissionError, match="validation_policy.manage"):
        await tool_service.update_tool(db, "tool-1", ToolUpdate(tool_validation_policy="true"), modified_by="dev@example.com")
    grant.assert_awaited_once_with(db, "dev@example.com", resource_type="tools", team_id="team-1")
    assert updating.tool_validation_policy is None
    db.commit.assert_not_called()
    audit.assert_not_called()


@pytest.mark.asyncio
async def test_update_tool_resubmitting_the_stored_policy_needs_no_permission(tool_service, updating, policy_permission, monkeypatch):
    """A form that sends the stored policy back unchanged is not a policy change."""
    grant, audit = policy_permission
    admit = Mock(return_value=None)
    monkeypatch.setattr(policy_module, "admit_tool", admit)
    updating.tool_validation_policy = "true"
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy=" true "), modified_by="dev@example.com")
    grant.assert_not_awaited()
    audit.assert_not_called()
    admit.assert_not_called()
    assert updating.tool_validation_policy == "true"


@pytest.mark.asyncio
async def test_update_tool_records_a_policy_change_in_the_audit_trail(tool_service, updating, policy_permission, monkeypatch):
    """A real policy change writes one audit entry with the old and new expressions."""
    _, audit = policy_permission
    monkeypatch.setattr(policy_module, "admit_tool", Mock(return_value=None))
    updating.tool_validation_policy = "true"
    await tool_service.update_tool(_mock_session(), "tool-1", ToolUpdate(tool_validation_policy='tool_name == "build"'), modified_by="admin@example.com")
    audit.assert_called_once_with(resource_type="tool", resource_id="tool-1", resource_name="build", team_id=None, user_email="admin@example.com", old="true", new='tool_name == "build"')


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
async def test_update_tool_skips_policy_when_neither_field_changes(tool_service, updating, monkeypatch):
    """An update that touches neither the description nor the policy does not re-evaluate."""
    admit = Mock(return_value=REASON)
    monkeypatch.setattr(policy_module, "admit_tool", admit)
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


def test_bulk_rows_with_a_policy_fail_without_the_permission(tool_service):
    """A row that sets a policy fails unless the caller holds the permission; plain rows are unaffected."""
    with_policy = _tool_create("plain", tool_validation_policy="true")
    denied = tool_service._process_single_tool_for_bulk(tool=with_policy, **_bulk_kwargs())  # pylint: disable=protected-access
    assert denied == {"status": "fail", "error": "Tool 'build' sets a tool validation policy, which requires the validation_policy.manage permission"}
    assert tool_service._process_single_tool_for_bulk(tool=with_policy, may_set_policy=True, **_bulk_kwargs())["status"] == "add"  # pylint: disable=protected-access
    assert tool_service._process_single_tool_for_bulk(tool=_tool_create("plain"), **_bulk_kwargs())["status"] == "add"  # pylint: disable=protected-access


def test_bulk_chunk_looks_up_gateway_policies_once(tool_service, monkeypatch):
    """One query serves every tool in the chunk, and each row receives its own gateway's policy."""
    lookup = Mock(return_value={"gw-a": "true"})
    monkeypatch.setattr(tool_service, "_gateway_tool_validation_policies", lookup)
    row = Mock(return_value={"status": "skip"})
    monkeypatch.setattr(tool_service, "_process_single_tool_for_bulk", row)
    chunk = [_tool_create("one", gateway_id="gw-a"), _tool_create("two", gateway_id="gw-a"), _tool_create("three", gateway_id="gw-b")]
    kwargs = _bulk_kwargs()
    kwargs.pop("existing_tools_map")
    tool_service._process_tool_chunk(MagicMock(), chunk=chunk, existing_tools_map={}, may_set_policy=True, **kwargs)  # pylint: disable=protected-access
    assert lookup.call_count == 1
    assert set(lookup.call_args.args[1]) == {"gw-a", "gw-b"}
    assert [call.kwargs["gateway_policy"] for call in row.call_args_list] == ["true", "true", None]
    assert all(call.kwargs["may_set_policy"] is True for call in row.call_args_list)


@pytest.mark.asyncio
async def test_bulk_checks_the_permission_once_per_call(tool_service, policy_permission, monkeypatch):
    """The permission is checked once for the whole import, only when some row sets a policy."""
    grant, _ = policy_permission
    chunk = Mock(return_value={"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []})
    monkeypatch.setattr(tool_service, "_process_tool_chunk", chunk)
    monkeypatch.setattr(tool_service, "_load_authorized_tool_conflicts", AsyncMock(return_value=({}, frozenset())))
    db = _mock_session()
    await tool_service.register_tools_bulk(db, [_tool_create("plain")], user_email="dev@example.com")
    grant.assert_not_awaited()
    assert chunk.call_args.kwargs["may_set_policy"] is False

    grant.side_effect = PermissionError("missing permission")
    await tool_service.register_tools_bulk(
        db, [_tool_create("plain", tool_validation_policy="true"), _tool_create("other", tool_validation_policy="true")], user_email="dev@example.com", team_id="team-1"
    )
    grant.assert_awaited_once_with(db, "dev@example.com", resource_type="tools", team_id="team-1")
    assert chunk.call_args.kwargs["may_set_policy"] is False

    grant.side_effect = None
    await tool_service.register_tools_bulk(db, [_tool_create("plain", tool_validation_policy="true")], user_email="admin@example.com")
    assert chunk.call_args.kwargs["may_set_policy"] is True
