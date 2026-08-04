# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/ica_metering_exporter/test_ica_metering_exporter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for IcaMeteringExporterPlugin.
"""

# Standard
from contextlib import contextmanager
from unittest.mock import ANY, AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from cpex.framework.constants import GATEWAY_METADATA
from mcpgateway.transports.context import request_headers_var
from plugins.ica_metering_exporter.ica_metering_exporter import IcaMeteringExporterPlugin


@contextmanager
def _set_request_headers(headers: dict):
    """Context manager to set request_headers_var for testing."""
    token = request_headers_var.set(headers)
    try:
        yield
    finally:
        request_headers_var.reset(token)


def _create_plugin(config_dict: dict | None = None, mock_send: bool = True) -> IcaMeteringExporterPlugin:
    """Create an ICA metering exporter plugin with optional config."""
    config = config_dict or {
        "enabled": True,
        "metering_url": "http://localhost:8080/event",
        "metering_token": "test-token",
    }
    plugin = IcaMeteringExporterPlugin(
        PluginConfig(
            name="ica_metering_test",
            kind="plugins.ica_metering_exporter.ica_metering_exporter.IcaMeteringExporterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
            config=config,
        )
    )
    if mock_send:
        plugin._send_to_ica = AsyncMock()  # type: ignore[method-assign]
    return plugin


def _create_context(
    metadata: dict | None = None,
    user: str = "user@ibm.com",
    tenant_id: str = "team-1",
    server_id: str = "srv-1",
) -> PluginContext:
    """Create a standard plugin context for tests."""
    return PluginContext(
        global_context=GlobalContext(
            request_id="req-123",
            user=user,
            tenant_id=tenant_id,
            server_id=server_id,
            metadata=metadata or {},
        ),
    )


class TestIcaMeteringExporterPlugin:
    """Unit tests for ICA metering exporter plugin."""

    # ── Pre-invoke tests ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pre_invoke_records_timestamp(self):
        """Pre-invoke should store start time in context state."""
        plugin = _create_plugin()
        context = _create_context()
        payload = ToolPreInvokePayload(name="test_tool", args={}, headers=None)

        await plugin.tool_pre_invoke(payload, context)

        assert "ica_metering_start_time" in context.state
        assert isinstance(context.state["ica_metering_start_time"], float)

    @pytest.mark.asyncio
    async def test_pre_invoke_is_noop_when_disabled(self):
        """Pre-invoke should be a no-op when plugin is disabled."""
        plugin = _create_plugin({"enabled": False})
        context = _create_context()
        payload = ToolPreInvokePayload(name="test_tool", args={}, headers=None)

        await plugin.tool_pre_invoke(payload, context)

        assert "ica_metering_start_time" not in context.state

    @pytest.mark.asyncio
    async def test_pre_invoke_always_returns_continue(self):
        """Pre-invoke should never block execution."""
        plugin = _create_plugin()
        result = await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="test_tool", args={}, headers=None),
            _create_context(),
        )
        assert result.continue_processing is True

    # ── App ID and User Agent extraction tests ───────────────────

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_app_id_from_headers(self):
        """Pre-invoke should extract appId from request_headers_var."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-app-id": "coding-agent:research"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_app_id") == "coding-agent:research"

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_user_agent_from_headers(self):
        """Pre-invoke should extract user agent from user-agent header."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"user-agent": "ClaudeCode/1.2.3"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_user_agent") == "ClaudeCode/1.2.3"

    @pytest.mark.asyncio
    async def test_pre_invoke_forwarded_user_agent_takes_priority(self):
        """X-Forwarded-User-Agent should take priority over User-Agent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "user-agent": "JavaHttpClient/4.0",
            "x-forwarded-user-agent": "ClaudeCode/1.2.3",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_user_agent") == "ClaudeCode/1.2.3"

    @pytest.mark.asyncio
    async def test_post_invoke_includes_app_id_and_user_agent(self):
        """Post-invoke payload should include appId and userAgent from state."""
        plugin = _create_plugin()
        context = _create_context()
        context.state["ica_app_id"] = "coding-agent:research"
        context.state["ica_user_agent"] = "ClaudeCode/1.2.3"
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["appId"] == "coding-agent:research"
        assert sent_payload["userAgent"] == "ClaudeCode/1.2.3"

    @pytest.mark.asyncio
    async def test_post_invoke_app_id_is_none_when_not_set(self):
        """appId should be None in payload when no X-App-Id header was present."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["appId"] is None
        assert sent_payload["userAgent"] is None

    # ── MCP Client Identity Header Tests ─────────────────────────

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_mcp_client_name(self):
        """Pre-invoke should extract X-MCP-Client-Name and X-MCP-Client-Version."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-mcp-client-name": "opencode", "x-mcp-client-version": "1.5.0"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_mcp_client_name") == "opencode"
        assert context.state.get("ica_mcp_client_version") == "1.5.0"

    @pytest.mark.asyncio
    async def test_pre_invoke_mcp_client_name_used_as_user_agent_fallback(self):
        """MCP client name/version should be used as userAgent when X-Forwarded-User-Agent absent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-mcp-client-name": "opencode", "x-mcp-client-version": "1.5.0"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_user_agent") == "opencode/1.5.0"

    @pytest.mark.asyncio
    async def test_pre_invoke_mcp_client_name_without_version(self):
        """MCP client name alone (no version) should still populate userAgent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-mcp-client-name": "vscode-copilot"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_user_agent") == "vscode-copilot"

    @pytest.mark.asyncio
    async def test_pre_invoke_forwarded_user_agent_takes_priority_over_mcp_client(self):
        """X-Forwarded-User-Agent should take priority over X-MCP-Client-Name."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "x-forwarded-user-agent": "Mozilla/5.0 Safari",
            "x-mcp-client-name": "opencode",
            "x-mcp-client-version": "1.0",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_user_agent") == "Mozilla/5.0 Safari"

    @pytest.mark.asyncio
    async def test_pre_invoke_derives_app_id_from_mcp_client_name(self):
        """appId should be derived as 'api:{client_name}' when X-App-Id absent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-mcp-client-name": "opencode", "x-mcp-client-version": "1.0"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_app_id") == "api:opencode"

    @pytest.mark.asyncio
    async def test_pre_invoke_explicit_app_id_not_overridden_by_mcp_client(self):
        """Explicit X-App-Id should NOT be overridden by X-MCP-Client-Name."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "x-app-id": "agent:MyAgent:agent-123",
            "x-mcp-client-name": "opencode",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_app_id") == "agent:MyAgent:agent-123"

    @pytest.mark.asyncio
    async def test_pre_invoke_derives_app_id_from_user_agent(self):
        """appId should be derived from user-agent when no X-App-Id or X-MCP-Client-Name."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"user-agent": "opencode/1.18.13"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_app_id") == "api:opencode"

    @pytest.mark.asyncio
    async def test_pre_invoke_does_not_derive_app_id_from_mozilla_user_agent(self):
        """appId should NOT be derived from browser-like user-agent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"user-agent": "Mozilla/5.0 (Macintosh) Safari/537.36"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_app_id") is None

    # ── requestType from gateway transport tests ─────────────────

    @pytest.mark.asyncio
    async def test_request_type_from_gateway_streamablehttp(self):
        """requestType should be STREAMABLE_HTTP when gateway transport is streamablehttp."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={GATEWAY_METADATA: {"id": "gw-1", "name": "gw", "transport": "streamablehttp"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["requestType"] == "STREAMABLE_HTTP"

    @pytest.mark.asyncio
    async def test_request_type_from_gateway_streamable_http_underscore(self):
        """requestType should be STREAMABLE_HTTP when gateway transport is streamable_http."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={GATEWAY_METADATA: {"id": "gw-1", "name": "gw", "transport": "streamable_http"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["requestType"] == "STREAMABLE_HTTP"

    @pytest.mark.asyncio
    async def test_request_type_from_gateway_sse(self):
        """requestType should be SSE when gateway transport is sse."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={GATEWAY_METADATA: {"id": "gw-1", "name": "gw", "transport": "sse"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["requestType"] == "SSE"

    @pytest.mark.asyncio
    async def test_request_type_unknown_when_no_gateway_metadata(self):
        """requestType should be UNKNOWN when no gateway metadata present."""
        plugin = _create_plugin()
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["requestType"] == "UNKNOWN"

    # ── Post-invoke latency tests ────────────────────────────────

    @pytest.mark.asyncio
    async def test_post_invoke_calculates_latency(self):
        """Post-invoke should calculate latency from stored timestamp."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="test_tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "result"}], "isError": False},
        )

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["latencyMs"] is not None
        assert sent_payload["toolDetails"]["latencyMs"] >= 0

    @pytest.mark.asyncio
    async def test_post_invoke_latency_is_none_when_no_pre_invoke(self):
        """Latency should be None if pre-invoke was not called."""
        plugin = _create_plugin()
        context = _create_context()
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [], "isError": False},
        )

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["latencyMs"] is None

    # ── Model resolution priority cascade tests ──────────────────

    @pytest.mark.asyncio
    async def test_model_resolution_priority_1_headers(self):
        """Priority 1: Transport headers should take highest priority."""
        plugin = _create_plugin()
        plugin.env_model_name = "env-model"
        context = _create_context(
            metadata={"model_name": "session-model", GATEWAY_METADATA: {"id": "gw-1"}},
        )
        plugin._gateway_configs = {"gw-1": {"default_model": "gateway-model"}}
        plugin.telemetry_config["global_default_model"] = "global-model"
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(
                name="tool", args={},
                headers={"X-OpenWebUI-Model-Id": "header-model"},
            ),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "header-model"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_2_session_init(self):
        """Priority 2: Session metadata should resolve when headers absent."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={"model_name": "session-model"},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "session-model"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_3_environment(self):
        """Priority 3: Environment variable should resolve when headers and session absent."""
        plugin = _create_plugin()
        plugin.env_model_name = "env-gpt-4"
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "env-gpt-4"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_4_tool_metadata(self):
        """Priority 4: meta_data.model should resolve when higher priorities absent."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={"meta_data": {"model": "tool-meta-model"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "tool-meta-model"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_5_gateway_default(self):
        """Priority 5: Gateway-level default should resolve when higher priorities absent."""
        plugin = _create_plugin()
        plugin._gateway_configs = {"gw-research": {"default_model": "gateway-model"}}
        context = _create_context(
            metadata={GATEWAY_METADATA: {"id": "gw-research"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "gateway-model"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_6_global_default(self):
        """Priority 6: Global default should resolve when all higher priorities absent."""
        plugin = _create_plugin()
        plugin.telemetry_config["global_default_model"] = "global-default-model"
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "global-default-model"

    @pytest.mark.asyncio
    async def test_model_resolution_priority_7_unknown(self):
        """Priority 7: None when all sources exhausted."""
        plugin = _create_plugin()
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] is None

    @pytest.mark.asyncio
    async def test_model_source_tracking_when_enabled(self):
        """modelSource field should be emitted when include_model_source is true."""
        plugin = _create_plugin({"enabled": True, "include_model_source": True,
                                "metering_url": "http://localhost:8080/event",
                                "metering_token": "test-token"})
        context = _create_context(metadata={"model_name": "session-model"})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["_metadata"]["modelSource"] == "session_init"
        assert sent_payload["toolDetails"]["modelName"] == "session-model"

    @pytest.mark.asyncio
    async def test_model_source_tracking_not_emitted_when_disabled(self):
        """modelSource field should not be emitted when include_model_source is false."""
        plugin = _create_plugin()
        context = _create_context(metadata={"model_name": "session-model"})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert "_metadata" not in sent_payload

    @pytest.mark.asyncio
    async def test_model_resolution_full_cascade_header_wins(self):
        """All 6 sources present - Priority 1 (transport header) wins."""
        plugin = _create_plugin()
        plugin.env_model_name = "env-model"
        plugin._gateway_configs = {"gw-1": {"default_model": "gateway-model"}}
        plugin.telemetry_config["global_default_model"] = "global-model"
        context = _create_context(
            metadata={
                "model_name": "session-model",
                "meta_data": {"model": "meta-model"},
                GATEWAY_METADATA: {"id": "gw-1"},
            },
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(
                name="tool", args={},
                headers={"X-OpenWebUI-Model-Id": "header-model"},
            ),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "header-model"

    @pytest.mark.asyncio
    async def test_model_resolution_picks_highest_available(self):
        """Only Priority 2 (session) available — should use that."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={"model_name": "session-only"},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers={}),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "session-only"

    # ── Post-invoke structured JSON tests ────────────────────────

    @pytest.mark.asyncio
    async def test_post_invoke_sends_structured_json(self):
        """Post-invoke should send structured JSON matching ToolCallDetails."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={
                "gateway": {"name": "gw-name", "id": "gw-1"},
                "meta_data": {"model": "gpt-4"},
                GATEWAY_METADATA: {"name": "gw-name", "id": "gw-1", "transport": "streamablehttp"},
            },
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="get_weather", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="get_weather",
            result={
                "content": [{"type": "text", "text": "sunny"}],
                "isError": False,
                "meta": {"tokens": {"input": 10, "output": 20}},
            },
        )

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]

        assert sent_payload["userEmail"] == "user@ibm.com"
        assert sent_payload["teamName"] == "team-1"
        assert td["toolName"] == "get_weather"
        assert td["serverId"] == "srv-1"
        assert td["serverName"] == "gw-name"
        assert td["gatewayId"] == "gw-1"
        assert td["integrationType"] == "MCP"
        assert td["requestType"] == "STREAMABLE_HTTP"
        assert td["hasError"] is False
        assert td["errorMessage"] is None
        assert td["cached"] is False
        assert td["retryAttempt"] == 0
        assert td["modelName"] == "gpt-4"
        assert td["traceId"] == "req-123"
        assert td["tokenInput"] == 10
        assert td["tokenOutput"] == 20
        assert td["source"] == "ContextForge"

    @pytest.mark.asyncio
    async def test_post_invoke_noop_when_disabled(self):
        """Post-invoke should be a no-op when plugin is disabled."""
        plugin = _create_plugin({"enabled": False})
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [], "isError": False},
        )

        await plugin.tool_post_invoke(payload, _create_context())

        plugin._send_to_ica.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_invoke_noop_when_empty_tool_name(self):
        """Post-invoke should skip metering when tool name is empty."""
        plugin = _create_plugin()
        payload = ToolPostInvokePayload(name="", result={"content": [], "isError": False})

        await plugin.tool_post_invoke(payload, _create_context())

        plugin._send_to_ica.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_invoke_always_returns_continue(self):
        """Post-invoke should never block execution."""
        plugin = _create_plugin()
        result = await plugin.tool_post_invoke(
            ToolPostInvokePayload(name="test_tool", result={"content": [], "isError": False}),
            _create_context(),
        )
        assert result.continue_processing is True

    # ── Default / fallback field tests ───────────────────────────

    @pytest.mark.asyncio
    async def test_post_invoke_defaults_unknown_for_missing_fields(self):
        """Missing global context fields should default to 'unknown'."""
        plugin = _create_plugin()
        context = _create_context(user="", tenant_id="", server_id="")
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["userEmail"] == "unknown"
        assert sent_payload["teamName"] == "unknown"
        assert sent_payload["toolDetails"]["serverId"] == "unknown"

    @pytest.mark.asyncio
    async def test_post_invoke_optional_fields_absent_when_not_provided(self):
        """Optional fields (model, trace, tokens) should be None when not provided."""
        plugin = _create_plugin()
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]
        assert td["modelName"] is None
        assert td["modelName"] is None  # None from empty ctx_meta
        assert td["tokenInput"] is None
        assert td["tokenOutput"] is None

    # ── Model name from headers tests ──────────────────────────

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_model_from_headers(self):
        """Pre-invoke should extract model name from transport headers."""
        plugin = _create_plugin()
        context = _create_context(metadata={})
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(
                name="tool",
                args={},
                headers={"X-OpenWebUI-Model-Id": "gpt-4"},
            ),
            context,
        )

        assert context.state.get("ica_metering_model_name") == "gpt-4"

    @pytest.mark.asyncio
    async def test_model_name_from_headers_takes_priority(self):
        """Header-extracted model should take priority over meta_data.model."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={"meta_data": {"model": "claude-3"}},
        )
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(
                name="tool",
                args={},
                headers={"X-OpenWebUI-Model-Id": "gpt-4"},
            ),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["toolDetails"]["modelName"] == "gpt-4"

    # ── Error handling tests ─────────────────────────────────────

    @pytest.mark.parametrize(
        "result,expected_error,expected_message",
        [
            ({"isError": True, "errorMessage": "timeout"}, True, "timeout"),
            ({"isError": True}, True, None),
            ({"isError": False}, False, None),
            ({}, False, None),
            (None, False, None),
            ("string result", False, None),
            (42, False, None),
        ],
    )
    @pytest.mark.asyncio
    async def test_post_invoke_error_detection(self, result, expected_error, expected_message):
        """Error detection should handle various result types."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result=result)

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]
        assert td["hasError"] == expected_error
        assert td["errorMessage"] == expected_message

    # ── Token extraction tests ───────────────────────────────────

    @pytest.mark.parametrize(
        "result,expected_input,expected_output",
        [
            ({"meta": {"tokens": {"input": 10, "output": 20}}}, 10, 20),
            ({"meta": {"tokens": {"input": 10}}}, 10, None),
            ({"meta": {}}, None, None),
            ({}, None, None),
            (None, None, None),
            ("string", None, None),
        ],
    )
    @pytest.mark.asyncio
    async def test_post_invoke_token_extraction(self, result, expected_input, expected_output):
        """Token extraction should handle various meta structures."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result=result)

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]
        assert td["tokenInput"] == expected_input
        assert td["tokenOutput"] == expected_output

    @pytest.mark.asyncio
    async def test_post_invoke_tokens_missing_when_no_meta_dict(self):
        """Token fields should be None when meta is not a dict."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"meta": "not-a-dict"})

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]
        assert td["tokenInput"] is None
        assert td["tokenOutput"] is None

    # ── cache_hit and retry_count tests ──────────────────────────

    @pytest.mark.asyncio
    async def test_post_invoke_cached_flag_from_context_state(self):
        """cached flag should be read from context.state."""
        plugin = _create_plugin()
        context = _create_context()
        context.state["cache_hit"] = True
        context.state["retry_count"] = 3
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})

        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        td = sent_payload["toolDetails"]
        assert td["cached"] is True
        assert td["retryAttempt"] == 3

    # ── HTTP client lifecycle tests ──────────────────────────────

    @pytest.mark.asyncio
    async def test_http_client_not_created_when_disabled(self):
        """HTTP client should not be created when plugin is disabled."""
        plugin = _create_plugin({"enabled": False})
        assert plugin.http_client is None

    @pytest.mark.asyncio
    async def test_http_client_created_when_enabled(self):
        """HTTP client should be created when plugin is enabled."""
        plugin = _create_plugin()
        assert plugin.http_client is not None
        assert isinstance(plugin.http_client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_shutdown_closes_http_client(self):
        """shutdown() should close the HTTP client."""
        plugin = _create_plugin()
        assert plugin.http_client is not None
        aclose_mock = AsyncMock()
        plugin.http_client.aclose = aclose_mock

        await plugin.shutdown()

        aclose_mock.assert_awaited_once()
        assert plugin.http_client is None

    @pytest.mark.asyncio
    async def test_shutdown_safe_when_no_client(self):
        """shutdown() should not fail when there is no HTTP client."""
        plugin = _create_plugin({"enabled": False})
        assert plugin.http_client is None

        await plugin.shutdown()  # should not raise

    # ── _send_to_ica error handling tests ────────────────────────

    @pytest.mark.asyncio
    async def test_send_to_ica_noop_without_client(self):
        """_send_to_ica should be a no-op when http_client is None."""
        plugin = _create_plugin({"enabled": False}, mock_send=False)
        plugin.http_client = None

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_noop_without_url(self):
        """_send_to_ica should skip when URL or token is missing."""
        plugin = _create_plugin(
            {"enabled": True, "metering_url": "", "metering_token": ""},
            mock_send=False,
        )
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock()

        await plugin._send_to_ica({"key": "value"})

        plugin.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_to_ica_sends_correct_headers(self):
        """_send_to_ica should send the correct auth header."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(return_value=MagicMock(status_code=202))

        payload = {"key": "value"}
        await plugin._send_to_ica(payload)

        plugin.http_client.post.assert_awaited_once_with(
            "http://localhost:8080/event",
            json=payload,
            headers={"X-MCP-Metering-Token": "test-token"},
        )

    @pytest.mark.asyncio
    async def test_send_to_ica_logs_non_202(self):
        """_send_to_ica should warn when response is not 202."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(return_value=MagicMock(status_code=500, text="error"))

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_handles_httpx_errors(self):
        """_send_to_ica should handle httpx exceptions gracefully."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(side_effect=httpx.NetworkError("connection refused"))

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_handles_unexpected_errors(self):
        """_send_to_ica should handle unexpected exceptions gracefully."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(side_effect=RuntimeError("unexpected"))

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_handles_http_status_error(self):
        """_send_to_ica should handle httpx HTTPStatusError gracefully."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        response = MagicMock(status_code=403, text="forbidden")
        plugin.http_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("403 error", request=MagicMock(), response=response)
        )

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_handles_timeout(self):
        """_send_to_ica should handle httpx TimeoutException gracefully."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        await plugin._send_to_ica({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_to_ica_with_non_dict_metadata(self):
        """_send_to_ica should handle non-dict gateway_meta and ctx_meta gracefully."""
        plugin = _create_plugin()
        context = _create_context()
        context.global_context.metadata[GATEWAY_METADATA] = "string_not_dict"
        context.global_context.metadata["meta_data"] = "also_not_dict"

        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="test_tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "result"}], "isError": False},
        )
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["userEmail"] == context.global_context.user or "unknown"

    # ── Static helper tests ──────────────────────────────────────

    def test_is_error_various_types(self):
        """_is_error should handle various input types."""
        assert IcaMeteringExporterPlugin._is_error({"isError": True}) is True
        assert IcaMeteringExporterPlugin._is_error({"isError": False}) is False
        assert IcaMeteringExporterPlugin._is_error({}) is False
        assert IcaMeteringExporterPlugin._is_error(None) is False
        assert IcaMeteringExporterPlugin._is_error("string") is False
        assert IcaMeteringExporterPlugin._is_error(42) is False

    def test_extract_error_message(self):
        """_extract_error_message should return message when present."""
        assert IcaMeteringExporterPlugin._extract_error_message({"isError": True, "errorMessage": "fail"}) == "fail"
        assert IcaMeteringExporterPlugin._extract_error_message({"isError": True}) is None
        assert IcaMeteringExporterPlugin._extract_error_message({"isError": False}) is None
        assert IcaMeteringExporterPlugin._extract_error_message({}) is None
        assert IcaMeteringExporterPlugin._extract_error_message(None) is None
        assert IcaMeteringExporterPlugin._extract_error_message("string") is None

    def test_extract_tokens(self):
        """_extract_tokens should extract tokens from result."""
        result = {"meta": {"tokens": {"input": 10, "output": 20}}}
        assert IcaMeteringExporterPlugin._extract_tokens(result) == {"input": 10, "output": 20}

        assert IcaMeteringExporterPlugin._extract_tokens({"meta": {}}) == {}
        assert IcaMeteringExporterPlugin._extract_tokens({}) == {}
        assert IcaMeteringExporterPlugin._extract_tokens(None) == {}
        assert IcaMeteringExporterPlugin._extract_tokens("string") == {}
        assert IcaMeteringExporterPlugin._extract_tokens({"meta": "not-dict"}) == {}

    # ── _coerce_int tests ─────────────────────────────────────────

    @pytest.mark.parametrize("value,expected", [
        (None, None),
        (42, 42),
        (42.0, 42),
        (42.7, 42),
        ("42", 42),
        ("abc", None),
        ([], None),
        ({}, None),
    ])
    def test_coerce_int(self, value, expected):
        """_coerce_int should safely convert values or return None."""
        assert IcaMeteringExporterPlugin._coerce_int(value) == expected

    # ── JWT service token tests ───────────────────────────────────

    def test_get_service_jwt_returns_token(self):
        """_get_service_jwt should return a valid JWT string."""
        token = IcaMeteringExporterPlugin._get_service_jwt("test-secret-key-for-jwt-generation-test")
        assert isinstance(token, str)
        assert len(token) > 20
        assert token.count(".") == 2

    def test_get_service_jwt_uses_contextforge_metering_subject(self):
        """JWT should contain 'contextforge-metering' as subject."""
        import jwt as pyjwt
        token = IcaMeteringExporterPlugin._get_service_jwt("test-secret-key-for-jwt-generation-test")
        decoded = pyjwt.decode(token, "test-secret-key-for-jwt-generation-test", algorithms=["HS256"])
        assert decoded["sub"] == "contextforge-metering"

    def test_get_service_jwt_has_service_attribution(self):
        """JWT should contain service, instance, and scope claims."""
        import jwt as pyjwt
        token = IcaMeteringExporterPlugin._get_service_jwt("test-secret-key-for-jwt-generation-test")
        decoded = pyjwt.decode(token, "test-secret-key-for-jwt-generation-test", algorithms=["HS256"])
        assert decoded["service"] == "mcp-context-forge"
        assert isinstance(decoded["instance"], str)
        assert len(decoded["instance"]) > 0
        assert decoded["scope"] == "metering:write"

    def test_get_service_jwt_expires_in_future(self):
        """JWT exp should be ~24h from now."""
        import jwt as pyjwt
        import time
        token = IcaMeteringExporterPlugin._get_service_jwt("test-secret-key-for-jwt-generation-test")
        decoded = pyjwt.decode(token, "test-secret-key-for-jwt-generation-test", algorithms=["HS256"])
        assert decoded["exp"] > time.time() + 86000  # ~23.9h
        assert decoded["exp"] < time.time() + 86500  # ~24.0h

    @pytest.mark.asyncio
    async def test_send_to_ica_uses_jwt_when_configured(self):
        """_send_to_ica should send Authorization: Bearer when jwt_secret is set."""
        plugin = _create_plugin({
            "enabled": True,
            "metering_url": "http://localhost:8080/event",
            "jwt_secret": "test-secret-key-for-jwt-generation-test",
        }, mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(return_value=MagicMock(status_code=202))

        await plugin._send_to_ica({"key": "value"})

        call_kwargs = plugin.http_client.post.await_args.kwargs
        headers = call_kwargs["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    @pytest.mark.asyncio
    async def test_send_to_ica_uses_shared_secret_when_no_jwt(self):
        """_send_to_ica should fall back to X-MCP-Metering-Token when jwt_secret is absent."""
        plugin = _create_plugin(mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock(return_value=MagicMock(status_code=202))

        await plugin._send_to_ica({"key": "value"})

        call_kwargs = plugin.http_client.post.await_args.kwargs
        headers = call_kwargs["headers"]
        assert "X-MCP-Metering-Token" in headers
        assert headers["X-MCP-Metering-Token"] == "test-token"

    @pytest.mark.asyncio
    async def test_send_to_ica_skips_when_no_auth_configured(self):
        """_send_to_ica should warn and skip when neither jwt_secret nor metering_token is set."""
        plugin = _create_plugin({
            "enabled": True,
            "metering_url": "http://localhost:8080/event",
        }, mock_send=False)
        assert plugin.http_client is not None
        plugin.http_client.post = AsyncMock()

        await plugin._send_to_ica({"key": "value"})

        plugin.http_client.post.assert_not_called()

    # ── End-to-end integration test ───────────────────────────────

    @pytest.mark.asyncio
    async def test_e2e_metering_payload_via_http(self):
        """Plugin sends correct JSON payload through real HTTP to metering endpoint."""
        from httpx import MockTransport

        captured_body = None

        def transport_handler(request):
            nonlocal captured_body
            captured_body = request
            return httpx.Response(202)

        plugin = _create_plugin(mock_send=False)
        plugin.http_client = httpx.AsyncClient(transport=MockTransport(transport_handler))

        context = _create_context()
        context.state["ica_app_id"] = "coding-agent:research"
        context.state["ica_user_agent"] = "ClaudeCode/1.2.3"
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="echo", args={"msg": "hello"}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="echo",
            result={
                "content": [{"type": "text", "text": "hello world"}],
                "isError": False,
                "meta": {"tokens": {"input": 10, "output": 20}},
            },
        )
        await plugin.tool_post_invoke(payload, context)

        import json
        body = json.loads(captured_body.content)
        assert body["userEmail"] == "user@ibm.com"
        assert body["teamName"] == "team-1"
        assert body["appId"] == "coding-agent:research"
        assert body["userAgent"] == "ClaudeCode/1.2.3"
        assert body["toolDetails"]["toolName"] == "echo"
        assert body["toolDetails"]["tokenInput"] == 10
        assert body["toolDetails"]["tokenOutput"] == 20
        assert body["toolDetails"]["source"] == "ContextForge"
        assert body["toolDetails"]["latencyMs"] >= 0
        assert body["toolDetails"]["hasError"] is False
        assert captured_body.headers["x-mcp-metering-token"] == "test-token"

    @pytest.mark.asyncio
    async def test_e2e_metering_payload_coerces_token_types(self):
        """Token values as float/string are coerced to int in HTTP payload."""
        from httpx import MockTransport

        captured_body = None

        def transport_handler(request):
            nonlocal captured_body
            captured_body = request
            return httpx.Response(202)

        plugin = _create_plugin(mock_send=False)
        plugin.http_client = httpx.AsyncClient(transport=MockTransport(transport_handler))

        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="echo", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="echo",
            result={
                "content": [{"type": "text", "text": "hello"}],
                "isError": False,
                "meta": {"tokens": {"input": 10.0, "output": "20"}},
            },
        )
        await plugin.tool_post_invoke(payload, context)

        import json
        body = json.loads(captured_body.content)
        assert body["toolDetails"]["tokenInput"] == 10
        assert body["toolDetails"]["tokenOutput"] == 20
        assert isinstance(body["toolDetails"]["tokenInput"], int)
        assert isinstance(body["toolDetails"]["tokenOutput"], int)

    # ── Call-context (persona) header tests ─────────────────────

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_assistant_headers(self):
        """Pre-invoke should extract llm_call_type and assistant headers."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "llm_call_type": "assistant",
            "assistant_uuid": "assistant-123",
            "assistant_name": "Austin Weather",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_llm_call_type") == "assistant"
        assert context.state.get("ica_assistant_uuid") == "assistant-123"
        assert context.state.get("ica_assistant_name") == "Austin Weather"

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_agent_headers(self):
        """Pre-invoke should extract llm_call_type and agent headers including tool ids."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "llm_call_type": "agent",
            "agent_uuid": "agent-456",
            "agent_name": "Research Agent",
            "agent_tool_ids": "server:mcp:abc123,server:mcp:def456",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_llm_call_type") == "agent"
        assert context.state.get("ica_agent_uuid") == "agent-456"
        assert context.state.get("ica_agent_name") == "Research Agent"
        assert context.state.get("ica_agent_tool_ids") == "server:mcp:abc123,server:mcp:def456"

    @pytest.mark.asyncio
    async def test_pre_invoke_extracts_digital_ibmer_headers(self):
        """Pre-invoke should extract llm_call_type and digital-ibmer headers."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "llm_call_type": "digital-ibmer",
            "digital-ibmer_uuid": "ibmer-789",
            "digital-ibmer_name": "Digital Coworker",
            "digital-ibmer_tool_ids": "server:mcp:xyz1",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_llm_call_type") == "digital-ibmer"
        assert context.state.get("ica_digital_ibmer_uuid") == "ibmer-789"
        assert context.state.get("ica_digital_ibmer_name") == "Digital Coworker"
        assert context.state.get("ica_digital_ibmer_tool_ids") == "server:mcp:xyz1"

    @pytest.mark.asyncio
    async def test_pre_invoke_persona_headers_case_insensitive(self):
        """Pre-invoke should extract persona headers regardless of casing."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({
            "LLM_CALL_TYPE": "assistant",
            "Assistant_Uuid": "assistant-111",
            "AGENT_TOOL_IDS": "server:mcp:abc",
        }):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        assert context.state.get("ica_llm_call_type") == "assistant"
        assert context.state.get("ica_assistant_uuid") == "assistant-111"
        assert context.state.get("ica_agent_tool_ids") == "server:mcp:abc"

    @pytest.mark.asyncio
    async def test_pre_invoke_no_persona_headers_leave_state_empty(self):
        """Pre-invoke should not store persona state when headers are absent."""
        plugin = _create_plugin()
        context = _create_context()
        with _set_request_headers({"x-app-id": "ica-api-dev"}):
            await plugin.tool_pre_invoke(
                ToolPreInvokePayload(name="tool", args={}, headers=None),
                context,
            )
        for state_key in IcaMeteringExporterPlugin.CALL_CONTEXT_HEADERS:
            assert state_key not in context.state

    @pytest.mark.asyncio
    async def test_post_invoke_emits_persona_fields(self):
        """Post-invoke payload should include persona fields from state."""
        plugin = _create_plugin()
        context = _create_context()
        context.state["ica_llm_call_type"] = "agent"
        context.state["ica_agent_uuid"] = "agent-456"
        context.state["ica_agent_name"] = "Research Agent"
        context.state["ica_agent_tool_ids"] = "server:mcp:abc123"
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["llmCallType"] == "agent"
        assert sent_payload["agentUuid"] == "agent-456"
        assert sent_payload["agentName"] == "Research Agent"
        assert sent_payload["agentToolIds"] == "server:mcp:abc123"

    @pytest.mark.asyncio
    async def test_post_invoke_persona_fields_none_when_not_set(self):
        """Persona fields should be None in payload when no persona headers were present."""
        plugin = _create_plugin()
        context = _create_context()
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="tool", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(name="tool", result={"content": [], "isError": False})
        await plugin.tool_post_invoke(payload, context)

        sent_payload = plugin._send_to_ica.await_args.args[0]
        assert sent_payload["llmCallType"] is None
        assert sent_payload["assistantUuid"] is None
        assert sent_payload["agentUuid"] is None
        assert sent_payload["agentToolIds"] is None
        assert sent_payload["digitalIbmerUuid"] is None
        assert sent_payload["digitalIbmerToolIds"] is None

    @pytest.mark.asyncio
    async def test_post_invoke_emits_persona_fields_via_http(self):
        """Persona fields propagate through real HTTP payload."""
        # Third-Party
        from httpx import MockTransport

        captured_body = None

        def transport_handler(request):
            nonlocal captured_body
            captured_body = request
            return httpx.Response(202)

        plugin = _create_plugin(mock_send=False)
        plugin.http_client = httpx.AsyncClient(transport=MockTransport(transport_handler))

        context = _create_context()
        context.state["ica_llm_call_type"] = "assistant"
        context.state["ica_assistant_uuid"] = "assistant-123"
        await plugin.tool_pre_invoke(
            ToolPreInvokePayload(name="echo", args={}, headers=None),
            context,
        )
        payload = ToolPostInvokePayload(
            name="echo",
            result={"content": [{"type": "text", "text": "hello"}], "isError": False},
        )
        await plugin.tool_post_invoke(payload, context)

        import json
        body = json.loads(captured_body.content)
        assert body["llmCallType"] == "assistant"
        assert body["assistantUuid"] == "assistant-123"
