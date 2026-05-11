# -*- coding: utf-8 -*-
"""Acceptance tests for the cpex package contract.

These tests verify that the cpex package exposes the API surface and
behavioural contracts that the gateway depends on.  They act as a
canary for future cpex version bumps.
"""

import pytest


# ---------------------------------------------------------------------------
# 1. API surface tests
# ---------------------------------------------------------------------------

class TestAPISurface:
    """Verify all symbols the gateway imports from cpex exist and are usable."""

    def test_top_level_exports(self):
        from cpex.framework import (
            AgentHookType,
            AgentPostInvokePayload,
            AgentPostInvokeResult,
            AgentPreInvokePayload,
            AgentPreInvokeResult,
            ConfigLoader,
            ExternalPluginServer,
            get_attr,
            get_hook_registry,
            GlobalContext,
            HookRegistry,
            HttpAuthCheckPermissionPayload,
            HttpAuthCheckPermissionResult,
            HttpAuthCheckPermissionResultPayload,
            HttpAuthResolveUserPayload,
            HttpAuthResolveUserResult,
            HttpHeaderPayload,
            HttpHookType,
            HttpPostRequestPayload,
            HttpPostRequestResult,
            HttpPreRequestPayload,
            HttpPreRequestResult,
            MCPServerConfig,
            ObservabilityProvider,
            Plugin,
            PluginCondition,
            PluginConfig,
            PluginContext,
            PluginContextTable,
            PluginError,
            PluginErrorModel,
            PluginLoader,
            PluginManager,
            PluginMode,
            PluginPayload,
            PluginResult,
            PluginViolation,
            PluginViolationError,
            PromptHookType,
            PromptPosthookPayload,
            PromptPosthookResult,
            PromptPrehookPayload,
            PromptPrehookResult,
            ResourceHookType,
            ResourcePostFetchPayload,
            ResourcePostFetchResult,
            ResourcePreFetchPayload,
            ResourcePreFetchResult,
            ToolHookType,
            ToolPostInvokePayload,
            ToolPostInvokeResult,
            ToolPreInvokePayload,
            ToolPreInvokeResult,
        )

    def test_sub_module_imports(self):
        from cpex.framework.constants import GATEWAY_METADATA, TOOL_METADATA
        from cpex.framework.hooks.policies import HookPayloadPolicy
        from cpex.framework.models import OnError, PluginMode
        from cpex.framework.observability import current_trace_id
        from cpex.framework.settings import settings

    def test_tools_cli(self):
        from cpex.tools.cli import main
        assert callable(main)


# ---------------------------------------------------------------------------
# 2. Behavioural contract tests
# ---------------------------------------------------------------------------

class TestBehaviouralContracts:
    """Verify key behavioural properties the gateway relies on."""

    def test_plugin_manager_accepts_hook_policies(self):
        from cpex.framework import PluginManager
        from cpex.framework.hooks.policies import HookPayloadPolicy

        policies = {
            "tool_pre_invoke": HookPayloadPolicy(writable_fields=frozenset({"name"})),
        }
        # Should not raise
        pm = PluginManager.__new__(PluginManager)
        # Verify the parameter exists in the constructor signature
        import inspect
        sig = inspect.signature(PluginManager.__init__)
        assert "hook_policies" in sig.parameters

    def test_plugin_payload_is_frozen(self):
        from cpex.framework import PluginPayload
        assert PluginPayload.model_config.get("frozen") is True

    def test_plugin_mode_has_expected_members(self):
        from cpex.framework.models import PluginMode
        expected = {"SEQUENTIAL", "TRANSFORM", "AUDIT", "CONCURRENT", "FIRE_AND_FORGET", "DISABLED"}
        actual = {m.name for m in PluginMode}
        assert expected.issubset(actual), f"Missing: {expected - actual}"

    def test_on_error_has_ignore(self):
        from cpex.framework.models import OnError
        assert hasattr(OnError, "IGNORE")

    def test_hook_payload_policy_writable_fields(self):
        from cpex.framework.hooks.policies import HookPayloadPolicy
        policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
        assert "name" in policy.writable_fields
        assert "args" in policy.writable_fields

    def test_observability_provider_protocol(self):
        from cpex.framework import ObservabilityProvider
        import inspect
        # Should have create_span, record_event or similar methods
        members = [m for m in dir(ObservabilityProvider) if not m.startswith("_")]
        assert len(members) > 0


# ---------------------------------------------------------------------------
# 3. Serialization contract tests
# ---------------------------------------------------------------------------

class TestSerializationContracts:
    """Verify payload models round-trip correctly."""

    def test_tool_pre_invoke_roundtrip(self):
        from cpex.framework.hooks.tools import ToolPreInvokePayload
        payload = ToolPreInvokePayload(name="test_tool", args={"key": "value"})
        data = payload.model_dump()
        restored = ToolPreInvokePayload.model_validate(data)
        assert restored.name == "test_tool"
        assert restored.args == {"key": "value"}

    def test_prompt_prehook_roundtrip(self):
        from cpex.framework.hooks.prompts import PromptPrehookPayload
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"arg1": "val1"})
        data = payload.model_dump()
        restored = PromptPrehookPayload.model_validate(data)
        assert restored.prompt_id == "test_prompt"

    def test_global_context_roundtrip(self):
        from cpex.framework import GlobalContext
        ctx = GlobalContext(request_id="req-1", metadata={"gateway": {"version": "1.0"}})
        data = ctx.model_dump()
        restored = GlobalContext.model_validate(data)
        assert restored.metadata["gateway"]["version"] == "1.0"

    def test_plugin_config_roundtrip(self):
        from cpex.framework import PluginConfig, PluginMode
        config = PluginConfig(
            name="test",
            kind="test.Plugin",
            version="1.0",
            hooks=["tool_pre_invoke"],
            mode=PluginMode.SEQUENTIAL,
        )
        data = config.model_dump()
        restored = PluginConfig.model_validate(data)
        assert restored.name == "test"
        assert restored.mode == PluginMode.SEQUENTIAL


# ---------------------------------------------------------------------------
# 4. Settings compatibility tests
# ---------------------------------------------------------------------------

class TestUserContextImportParity:
    """Verify UserContext imported via gateway re-export is the same class as cpex's."""

    def test_isinstance_check_works_across_import_paths(self):
        from cpex.framework import UserContext as CpexUserContext
        from mcpgateway.transports.context import UserContext as GatewayUserContext

        assert CpexUserContext is GatewayUserContext

    def test_user_context_has_required_fields(self):
        from mcpgateway.transports.context import UserContext

        ctx = UserContext(user_id="test@example.com", teams=["team-a"])
        assert ctx.user_id == "test@example.com"
        assert ctx.teams == ["team-a"]
        assert isinstance(ctx, UserContext)


class TestModeSemantics:
    """Verify that cpex PluginMode enum values match gateway expectations."""

    def test_sequential_mode_exists(self):
        from cpex.framework.models import PluginMode
        assert hasattr(PluginMode, "SEQUENTIAL")
        assert PluginMode.SEQUENTIAL.value == "sequential"

    def test_transform_mode_exists(self):
        from cpex.framework.models import PluginMode
        assert hasattr(PluginMode, "TRANSFORM")
        assert PluginMode.TRANSFORM.value == "transform"

    def test_audit_mode_exists(self):
        from cpex.framework.models import PluginMode
        assert hasattr(PluginMode, "AUDIT")
        assert PluginMode.AUDIT.value == "audit"

    def test_disabled_mode_exists(self):
        from cpex.framework.models import PluginMode
        assert hasattr(PluginMode, "DISABLED")
        assert PluginMode.DISABLED.value == "disabled"


class TestSettingsCompatibility:
    """Verify cpex reads PLUGINS_* env vars correctly."""

    def test_settings_reads_plugins_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_ENABLED", "false")
        from cpex.framework.settings import PluginsSettings
        s = PluginsSettings()
        assert s.enabled is False

    def test_settings_reads_plugin_timeout(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_ENABLED", "true")
        monkeypatch.setenv("PLUGINS_PLUGIN_TIMEOUT", "60")
        from cpex.framework.settings import PluginsSettings
        s = PluginsSettings()
        assert s.plugin_timeout == 60
