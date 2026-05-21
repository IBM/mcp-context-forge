# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/header_filter/test_header_filter_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Adrian Popa

Unit tests for Header Filter Plugin functionality.
"""

# Third-Party
import pytest

# First-Party
from cpex.framework import (
    AgentPreInvokePayload,
    GlobalContext,
    HttpHeaderPayload,
    PluginConfig,
    PluginContext,
    PluginMode,
    ToolHookType,
    ToolPreInvokePayload,
)

# Import the Header Filter plugin
from plugins.header_filter.header_filter_plugin import HeaderFilter, HeaderFilterConfig


class TestHeaderFilterPluginFunctionality:
    """Unit tests for Header Filter plugin functionality."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a test plugin configuration."""
        return PluginConfig(
            name="TestHeaderFilter",
            description="Test Header Filter Plugin",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test", "header_filter"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie", "X-API-Key"],
                "log_filtered_headers": True,
                "allow_passthrough_headers": [],
            },
        )

    @pytest.fixture
    def plugin_context(self) -> PluginContext:
        """Create a test plugin context."""
        global_context = GlobalContext(request_id="test-1")
        return PluginContext(global_context=global_context)

    # ── tool_pre_invoke tests ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_headers_returns_empty_result(self, plugin_config, plugin_context):
        """Test that missing headers returns empty result."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(name="test_tool", args={}, headers=None)

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_authorization_header_is_filtered(self, plugin_config, plugin_context):
        """Test that Authorization header is filtered."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Content-Type": "application/json", "Authorization": "Bearer secret_token"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_cookie_header_is_filtered(self, plugin_config, plugin_context):
        """Test that Cookie header is filtered."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Content-Type": "application/json", "Cookie": "session=abc123"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Cookie" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_multiple_sensitive_headers_filtered(self, plugin_config, plugin_context):
        """Test that multiple sensitive headers are filtered."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer token",
                    "Cookie": "session=xyz",
                    "X-API-Key": "secret_key",
                    "User-Agent": "TestClient/1.0",
                }
            ),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root
        assert "Cookie" not in result.modified_payload.headers.root
        assert "X-API-Key" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root
        assert "User-Agent" in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_case_insensitive_filtering(self, plugin_config, plugin_context):
        """Test that header filtering is case-insensitive."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "content-type": "application/json",
                    "authorization": "Bearer token",
                    "COOKIE": "session=xyz",
                    "X-Api-Key": "secret",
                }
            ),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "authorization" not in result.modified_payload.headers.root
        assert "COOKIE" not in result.modified_payload.headers.root
        assert "X-Api-Key" not in result.modified_payload.headers.root
        assert "content-type" in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_passthrough_headers_not_filtered(self, plugin_context):
        """Test that passthrough headers are not filtered even if in filter list."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie"],
                "allow_passthrough_headers": ["Authorization"],
            },
        )
        plugin = HeaderFilter(config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Authorization": "Bearer token", "Cookie": "session=xyz"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert "Cookie" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_no_filtered_headers_returns_empty_result(self, plugin_config, plugin_context):
        """Test that when no headers are filtered, empty result is returned."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Content-Type": "application/json", "User-Agent": "TestClient/1.0"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_empty_headers_dict_returns_empty_result(self, plugin_config, plugin_context):
        """Test that empty headers dict returns empty result."""
        plugin = HeaderFilter(plugin_config)
        payload = ToolPreInvokePayload(name="test_tool", args={}, headers=HttpHeaderPayload({}))

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_original_payload_not_mutated(self, plugin_config, plugin_context):
        """Test that the original payload is not mutated (frozen model compliance)."""
        plugin = HeaderFilter(plugin_config)
        original_headers = {"Content-Type": "application/json", "Authorization": "Bearer token"}
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(original_headers.copy()),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Original payload should still have Authorization
        assert "Authorization" in payload.headers.root
        # Modified payload should not
        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root

    # ── agent_pre_invoke tests ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_agent_no_headers_returns_empty_result(self, plugin_config, plugin_context):
        """Test agent_pre_invoke with no headers."""
        plugin = HeaderFilter(plugin_config)
        payload = AgentPreInvokePayload(agent_id="test-agent", messages=[], headers=None)

        result = await plugin.agent_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    @pytest.mark.asyncio
    async def test_agent_headers_filtered(self, plugin_config, plugin_context):
        """Test agent_pre_invoke filters sensitive headers."""
        plugin = HeaderFilter(plugin_config)
        payload = AgentPreInvokePayload(
            agent_id="test-agent",
            messages=[],
            headers=HttpHeaderPayload(
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer secret",
                    "Cookie": "session=abc",
                }
            ),
        )

        result = await plugin.agent_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root
        assert "Cookie" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_agent_passthrough_headers(self, plugin_context):
        """Test agent_pre_invoke respects passthrough headers."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie"],
                "allow_passthrough_headers": ["Authorization"],
            },
        )
        plugin = HeaderFilter(config)
        payload = AgentPreInvokePayload(
            agent_id="test-agent",
            messages=[],
            headers=HttpHeaderPayload({"Authorization": "Bearer token", "Cookie": "session=xyz"}),
        )

        result = await plugin.agent_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert "Cookie" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_agent_no_filtered_headers_returns_empty_result(self, plugin_config, plugin_context):
        """Test agent_pre_invoke returns empty result when no headers filtered."""
        plugin = HeaderFilter(plugin_config)
        payload = AgentPreInvokePayload(
            agent_id="test-agent",
            messages=[],
            headers=HttpHeaderPayload({"Content-Type": "application/json"}),
        )

        result = await plugin.agent_pre_invoke(payload, plugin_context)

        assert result.modified_payload is None
        assert result.continue_processing

    # ── Config and initialization tests ───────────────────────────────

    @pytest.mark.asyncio
    async def test_default_config_when_config_is_none(self, plugin_context):
        """Test that plugin uses default config when config dict is None."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config=None,
        )
        plugin = HeaderFilter(config)

        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Authorization": "Bearer token", "Content-Type": "application/json"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Default config should filter Authorization
        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_default_config_when_config_causes_validation_error(self, plugin_context):
        """Test that plugin falls back to defaults when config causes a validation error."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={"filter_headers": "not-a-list", "log_filtered_headers": "not-a-bool"},
        )
        plugin = HeaderFilter(config)

        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Authorization": "Bearer token", "Content-Type": "application/json"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Default config fallback should filter Authorization
        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root

    def test_header_filter_config_defaults(self):
        """Test HeaderFilterConfig has sensible defaults."""
        cfg = HeaderFilterConfig()

        assert "Authorization" in cfg.filter_headers
        assert "Cookie" in cfg.filter_headers
        assert "Set-Cookie" in cfg.filter_headers
        assert "X-Vault-Tokens" in cfg.filter_headers
        assert "X-API-Key" in cfg.filter_headers
        assert "X-Auth-Token" in cfg.filter_headers
        assert "Proxy-Authorization" in cfg.filter_headers
        assert "WWW-Authenticate" in cfg.filter_headers
        assert cfg.log_filtered_headers is True
        assert len(cfg.allow_passthrough_headers) == 0

    # ── _filter_headers internal method tests ─────────────────────────

    def test_filter_headers_method_returns_correct_tuple(self, plugin_config):
        """Test that _filter_headers method returns correct tuple."""
        plugin = HeaderFilter(plugin_config)
        headers = {"Content-Type": "application/json", "Authorization": "Bearer token", "Cookie": "session=xyz"}

        filtered, removed = plugin._filter_headers(headers, "test:context")

        assert "Content-Type" in filtered
        assert "Authorization" not in filtered
        assert "Cookie" not in filtered
        assert "Authorization" in removed
        assert "Cookie" in removed
        assert len(removed) == 2

    def test_filter_headers_empty_dict(self, plugin_config):
        """Test _filter_headers with empty input dict."""
        plugin = HeaderFilter(plugin_config)

        filtered, removed = plugin._filter_headers({}, "test:context")

        assert filtered == {}
        assert removed == []

    def test_filter_headers_all_removed(self, plugin_config):
        """Test _filter_headers when all headers are sensitive."""
        plugin = HeaderFilter(plugin_config)
        headers = {"Authorization": "Bearer token", "Cookie": "session=xyz", "X-API-Key": "key"}

        filtered, removed = plugin._filter_headers(headers, "test:context")

        assert filtered == {}
        assert len(removed) == 3

    def test_filter_headers_none_removed(self, plugin_config):
        """Test _filter_headers when no headers are sensitive."""
        plugin = HeaderFilter(plugin_config)
        headers = {"Content-Type": "application/json", "Accept": "text/html"}

        filtered, removed = plugin._filter_headers(headers, "test:context")

        assert filtered == headers
        assert removed == []

    # ── Integration-style scenarios ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_passthrough_for_vault_integration(self, plugin_context):
        """Test passthrough scenario: Vault plugin manages Authorization, filter manages others."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie", "X-API-Key"],
                "allow_passthrough_headers": ["Authorization"],
            },
        )
        plugin = HeaderFilter(config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "Authorization": "Bearer vault_token",
                    "Cookie": "session=abc",
                    "X-API-Key": "secret_key",
                    "Content-Type": "application/json",
                }
            ),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert result.modified_payload.headers.root["Authorization"] == "Bearer vault_token"
        assert "Cookie" not in result.modified_payload.headers.root
        assert "X-API-Key" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_multiple_passthrough_headers(self, plugin_context):
        """Test multiple headers in passthrough list."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie", "X-API-Key", "X-Custom-Header"],
                "allow_passthrough_headers": ["Authorization", "X-Custom-Header"],
            },
        )
        plugin = HeaderFilter(config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "Authorization": "Bearer token",
                    "Cookie": "session=xyz",
                    "X-API-Key": "api_key",
                    "X-Custom-Header": "custom_value",
                }
            ),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert "X-Custom-Header" in result.modified_payload.headers.root
        assert "Cookie" not in result.modified_payload.headers.root
        assert "X-API-Key" not in result.modified_payload.headers.root

    @pytest.mark.asyncio
    async def test_passthrough_case_insensitive(self, plugin_context):
        """Test that passthrough headers work case-insensitively."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization", "Cookie"],
                "allow_passthrough_headers": ["authorization"],
            },
        )
        plugin = HeaderFilter(config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload(
                {
                    "Authorization": "Bearer token",
                    "COOKIE": "session=xyz",
                }
            ),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert result.modified_payload is not None
        assert "Authorization" in result.modified_payload.headers.root
        assert "COOKIE" not in result.modified_payload.headers.root

    # ── Shutdown test ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_shutdown(self, plugin_config):
        """Test graceful shutdown."""
        plugin = HeaderFilter(plugin_config)

        result = await plugin.shutdown()

        assert result is None

    # ── Logging behavior tests ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_log_filtered_headers_disabled(self, plugin_context):
        """Test that logging is suppressed when log_filtered_headers is False."""
        config = PluginConfig(
            name="TestHeaderFilter",
            description="Test",
            author="Test",
            kind="plugins.header_filter.header_filter_plugin.HeaderFilter",
            version="1.0",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            tags=["test"],
            mode=PluginMode.SEQUENTIAL,
            priority=20,
            config={
                "filter_headers": ["Authorization"],
                "log_filtered_headers": False,
            },
        )
        plugin = HeaderFilter(config)
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={},
            headers=HttpHeaderPayload({"Authorization": "Bearer token", "Content-Type": "application/json"}),
        )

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        # Should still filter even with logging disabled
        assert result.modified_payload is not None
        assert "Authorization" not in result.modified_payload.headers.root
        assert "Content-Type" in result.modified_payload.headers.root


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
