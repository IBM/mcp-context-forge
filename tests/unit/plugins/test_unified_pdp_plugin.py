"""Tests for the UnifiedPDPPlugin class (unified_pdp.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.unified_pdp.unified_pdp import UnifiedPDPPlugin
from plugins.unified_pdp.pdp_models import AccessDecision, Decision, EngineDecision, EngineType
from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
from mcpgateway.plugins.framework.hooks.resources import ResourcePreFetchPayload


# ---------------------------------------------------------------------------
# Helpers — minimal fakes for the framework types
# ---------------------------------------------------------------------------

def _make_plugin_config(engines=None):
    """Build a minimal PluginConfig mock."""
    cfg = MagicMock()
    cfg.config = {
        "engines": engines or [
            {"name": "native", "enabled": True, "priority": 1, "settings": {"rules": [
                {"subject_role": "*", "action": "*", "resource": "*", "effect": "allow"}
            ]}}
        ],
        "combination_mode": "all_must_allow",
        "default_decision": "deny",
        "cache": {"enabled": False, "ttl_seconds": 60, "max_entries": 100},
        "performance": {"timeout_ms": 1000, "parallel_evaluation": False},
    }
    return cfg


def _make_context(user=None):
    """Build a minimal PluginContext mock."""
    ctx = MagicMock()
    ctx.global_context.user = user if user is not None else {"email": "alice@example.com", "roles": ["developer"], "team_id": "eng"}
    ctx.global_context.server_id = "test-server"
    ctx.global_context.request_id = "req-123"
    ctx.global_context.tenant_id = "tenant-1"
    return ctx


def _allow_decision(cached=False):
    return AccessDecision(
        decision=Decision.ALLOW,
        reason="allowed",
        engine_decisions=[EngineDecision(engine=EngineType.NATIVE, decision=Decision.ALLOW, reason="ok")],
        cached=cached,
    )


def _deny_decision():
    return AccessDecision(
        decision=Decision.DENY,
        reason="access denied by policy",
        engine_decisions=[EngineDecision(engine=EngineType.NATIVE, decision=Decision.DENY, reason="no matching rule")],
        cached=False,
    )


# ---------------------------------------------------------------------------
# TestUnifiedPDPPlugin
# ---------------------------------------------------------------------------

class TestUnifiedPDPPlugin:
    """Tests for the plugin class hook methods."""

    def _plugin(self):
        """Instantiate the plugin with a mocked PDP."""
        plugin = UnifiedPDPPlugin(_make_plugin_config())
        plugin._pdp = MagicMock()
        return plugin

    # --- tool_pre_invoke: ALLOW path ---

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_allow(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ToolPreInvokePayload(name="db-query", args={"sql": "SELECT 1"}, headers={})
        result = await plugin.tool_pre_invoke(payload, _make_context())

        assert result.continue_processing is not False
        assert result.violation is None
        plugin._pdp.check_access.assert_awaited_once()

    # --- tool_pre_invoke: DENY path ---

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_deny(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_deny_decision())

        payload = ToolPreInvokePayload(name="db-query", args={}, headers={})
        result = await plugin.tool_pre_invoke(payload, _make_context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PDP_DENY"
        assert "db-query" in result.violation.details["tool"]

    # --- tool_pre_invoke: action string format ---

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_passes_correct_action(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ToolPreInvokePayload(name="my-tool", args={}, headers={})
        await plugin.tool_pre_invoke(payload, _make_context())

        call_args = plugin._pdp.check_access.call_args
        action = call_args[0][1]  # second positional arg
        assert action == "tools.invoke.my-tool"

    # --- resource_pre_fetch: ALLOW path ---

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_allow(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ResourcePreFetchPayload(uri="file:///data.csv")
        result = await plugin.resource_pre_fetch(payload, _make_context())

        assert result.continue_processing is not False
        assert result.violation is None

    # --- resource_pre_fetch: DENY path ---

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_deny(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_deny_decision())

        payload = ResourcePreFetchPayload(uri="file:///secret.csv")
        result = await plugin.resource_pre_fetch(payload, _make_context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PDP_DENY"
        assert "file:///secret.csv" in result.violation.details["resource_uri"]

    # --- resource_pre_fetch: action is always resources.fetch ---

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_action_string(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ResourcePreFetchPayload(uri="http://api/data")
        await plugin.resource_pre_fetch(payload, _make_context())

        call_args = plugin._pdp.check_access.call_args
        action = call_args[0][1]
        assert action == "resources.fetch"

    # --- Subject extraction: dict user ---

    @pytest.mark.asyncio
    async def test_subject_extracted_from_dict_user(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        user = {"email": "bob@x.com", "roles": ["admin"], "team_id": "ops", "mfa_verified": True}
        payload = ToolPreInvokePayload(name="t", args={}, headers={})
        await plugin.tool_pre_invoke(payload, _make_context(user=user))

        subject = plugin._pdp.check_access.call_args[0][0]
        assert subject.email == "bob@x.com"
        assert "admin" in subject.roles
        assert subject.mfa_verified is True

    # --- Subject extraction: plain string user ---

    @pytest.mark.asyncio
    async def test_subject_extracted_from_string_user(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ToolPreInvokePayload(name="t", args={}, headers={})
        await plugin.tool_pre_invoke(payload, _make_context(user="simple-user-id"))

        subject = plugin._pdp.check_access.call_args[0][0]
        assert subject.email == "simple-user-id"
        assert subject.roles == []

    # --- Subject extraction: None user falls back to anonymous ---

    @pytest.mark.asyncio
    async def test_subject_anonymous_when_user_is_none(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        ctx = MagicMock()
        ctx.global_context.user = None
        ctx.global_context.server_id = "test-server"
        ctx.global_context.request_id = "req-123"
        ctx.global_context.tenant_id = "tenant-1"
        payload = ToolPreInvokePayload(name="t", args={}, headers={})
        await plugin.tool_pre_invoke(payload, ctx)

        subject = plugin._pdp.check_access.call_args[0][0]
        assert subject.email == "anonymous@internal"

    # --- Resource extraction: tool hook sets type=tool ---

    @pytest.mark.asyncio
    async def test_resource_type_is_tool_on_tool_hook(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ToolPreInvokePayload(name="my-tool", args={}, headers={})
        await plugin.tool_pre_invoke(payload, _make_context())

        resource = plugin._pdp.check_access.call_args[0][2]
        assert resource.type == "tool"
        assert resource.id == "my-tool"

    # --- Resource extraction: resource hook sets type=resource ---

    @pytest.mark.asyncio
    async def test_resource_type_is_resource_on_resource_hook(self):
        plugin = self._plugin()
        plugin._pdp.check_access = AsyncMock(return_value=_allow_decision())

        payload = ResourcePreFetchPayload(uri="file:///x.txt")
        await plugin.resource_pre_fetch(payload, _make_context())

        resource = plugin._pdp.check_access.call_args[0][2]
        assert resource.type == "resource"
        assert resource.id == "file:///x.txt"

    # --- _build_pdp constructs correctly ---

    def test_build_pdp_returns_policy_decision_point(self):
        raw = {
            "engines": [{"name": "native", "enabled": True, "priority": 1, "settings": {}}],
            "combination_mode": "any_allow",
            "default_decision": "allow",
            "cache": {"enabled": True, "ttl_seconds": 120, "max_entries": 500},
            "performance": {"timeout_ms": 2000, "parallel_evaluation": True},
        }
        from plugins.unified_pdp.pdp import PolicyDecisionPoint
        pdp = UnifiedPDPPlugin._build_pdp(raw)
        assert isinstance(pdp, PolicyDecisionPoint)

    # --- _build_pdp handles empty config ---

    def test_build_pdp_empty_config_does_not_crash(self):
        pdp = UnifiedPDPPlugin._build_pdp({})
        from plugins.unified_pdp.pdp import PolicyDecisionPoint
        assert isinstance(pdp, PolicyDecisionPoint)

    # --- shutdown calls PDP close ---

    @pytest.mark.asyncio
    async def test_shutdown_calls_pdp_close(self):
        plugin = self._plugin()
        plugin._pdp.close = AsyncMock()

        await plugin.shutdown()

        plugin._pdp.close.assert_awaited_once()
