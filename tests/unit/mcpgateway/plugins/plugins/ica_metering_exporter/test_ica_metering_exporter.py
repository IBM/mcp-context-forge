# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/ica_metering_exporter/test_ica_metering_exporter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for IcaMeteringExporterPlugin.
"""

# Standard
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
from plugins.ica_metering_exporter.ica_metering_exporter import IcaMeteringExporterPlugin


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

    # ── Post-invoke structured JSON tests ────────────────────────

    @pytest.mark.asyncio
    async def test_post_invoke_sends_structured_json(self):
        """Post-invoke should send structured JSON matching ToolCallDetails."""
        plugin = _create_plugin()
        context = _create_context(
            metadata={
                "gateway": {"name": "gw-name", "id": "gw-1"},
                "meta_data": {"model": "gpt-4"},
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
        assert td["requestType"] == "SSE"
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
