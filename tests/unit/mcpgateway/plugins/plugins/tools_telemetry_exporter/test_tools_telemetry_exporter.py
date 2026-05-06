# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/tools_telemetry_exporter/test_tools_telemetry_exporter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ToolsTelemetryExporterPlugin.
"""

# Standard
import json
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
from cpex.framework import GlobalContext, HttpHeaderPayload, PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload, ToolPreInvokePayload
from plugins.tools_telemetry_exporter.telemetry_exporter import ToolsTelemetryExporterPlugin


def _create_plugin(config_dict=None) -> ToolsTelemetryExporterPlugin:
    """Create a telemetry exporter with optional config overrides."""
    plugin = ToolsTelemetryExporterPlugin(
        PluginConfig(
            name="telemetry_test",
            kind="plugins.tools_telemetry_exporter.telemetry_exporter.ToolsTelemetryExporterPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
            config=config_dict or {},
        )
    )
    plugin._export_telemetry = AsyncMock()  # type: ignore[method-assign]
    return plugin


def _create_context() -> PluginContext:
    """Create a standard plugin context for tests."""
    return PluginContext(
        global_context=GlobalContext(
            request_id="req-123",
            user="user@example.com",
            tenant_id="tenant-1",
            server_id="server-1",
            metadata={},
        )
    )


class TestToolsTelemetryExporterPlugin:
    """Targeted unit tests for telemetry exporter hardening."""

    @pytest.mark.asyncio
    async def test_pre_invoke_redacts_sensitive_headers(self):
        """Sensitive request headers should be masked before export."""
        plugin = _create_plugin()
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={"input": "hello"},
            headers=HttpHeaderPayload(
                {
                    "Authorization": "Bearer secret-token",
                    "Cookie": "jwt_token=abc123; theme=dark",
                    "X-API-Key": "top-secret",
                    "X-Vault-Tokens": "vault-token",
                    "Content-Type": "application/json",
                    "X-Request-Id": "req-123",
                }
            ),
        )

        await plugin.tool_pre_invoke(payload, _create_context())

        attrs = plugin._export_telemetry.await_args.kwargs["attributes"]
        exported_headers = json.loads(attrs["headers"])

        assert exported_headers["Authorization"] == "******"
        assert exported_headers["Cookie"] == "******"
        assert exported_headers["X-API-Key"] == "******"
        assert exported_headers["X-Vault-Tokens"] == "******"
        assert exported_headers["Content-Type"] == "application/json"
        assert exported_headers["X-Request-Id"] == "req-123"

    @pytest.mark.asyncio
    async def test_pre_invoke_redacts_broad_token_header_patterns(self):
        """Broad token/secret/key header names should also be masked."""
        plugin = _create_plugin()
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "X-Delegation-Token": "delegation-secret",
                    "Upstream-Authorization": "Bearer upstream-secret",
                    "X-Session-Key": "session-secret",
                }
            ),
        )

        await plugin.tool_pre_invoke(payload, _create_context())

        attrs = plugin._export_telemetry.await_args.kwargs["attributes"]
        exported_headers = json.loads(attrs["headers"])

        assert exported_headers["X-Delegation-Token"] == "******"
        assert exported_headers["Upstream-Authorization"] == "******"
        assert exported_headers["X-Session-Key"] == "******"

    @pytest.mark.asyncio
    async def test_post_invoke_does_not_export_result_by_default(self):
        """Full result export should be opt-in."""
        plugin = _create_plugin()
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "sensitive result"}], "isError": False},
        )

        await plugin.tool_post_invoke(payload, _create_context())

        attrs = plugin._export_telemetry.await_args.kwargs["attributes"]
        assert "tool.invocation.result" not in attrs
        assert attrs["tool.invocation.has_error"] is False

    @pytest.mark.asyncio
    async def test_post_invoke_exports_result_only_when_enabled(self):
        """When explicitly enabled, non-error result content should be exported."""
        plugin = _create_plugin({"export_full_payload": True})
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "safe result"}], "isError": False},
        )

        await plugin.tool_post_invoke(payload, _create_context())

        attrs = plugin._export_telemetry.await_args.kwargs["attributes"]
        assert "tool.invocation.result" in attrs
        assert "safe result" in attrs["tool.invocation.result"]

    @pytest.mark.asyncio
    async def test_post_invoke_respects_max_payload_bytes_size(self):
        """Large results should still be truncated when full export is enabled."""
        plugin = _create_plugin({"export_full_payload": True, "max_payload_bytes_size": 20})
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "123456789012345678901234567890"}], "isError": False},
        )

        await plugin.tool_post_invoke(payload, _create_context())

        attrs = plugin._export_telemetry.await_args.kwargs["attributes"]
        assert attrs["tool.invocation.result"].endswith("...<truncated>")
