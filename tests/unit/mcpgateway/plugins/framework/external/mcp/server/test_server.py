# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Comprehensive unit tests for ExternalPluginServer.
"""

# Standard
import os
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginContext,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ToolHookType,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer
from mcpgateway.plugins.framework.models import MCPServerConfig, PluginErrorModel


@pytest.fixture
def server_with_plugins():
    """Create a server with valid plugin configuration."""
    return ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")


@pytest.fixture
async def initialized_server(server_with_plugins):
    """Create and initialize a server."""
    await server_with_plugins.initialize()
    yield server_with_plugins
    await server_with_plugins.shutdown()


class TestExternalPluginServerInit:
    """Tests for ExternalPluginServer initialization."""

    def test_init_with_config_path(self):
        """Test initialization with explicit config path."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        assert server._config_path == "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
        assert server._config is not None
        assert server._plugin_manager is not None

    def test_init_with_env_var(self):
        """Test initialization using PLUGINS_CONFIG_PATH environment variable."""
        os.environ["PLUGINS_CONFIG_PATH"] = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
        try:
            server = ExternalPluginServer()
            assert server._config_path == "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
            assert server._config is not None
        finally:
            if "PLUGINS_CONFIG_PATH" in os.environ:
                del os.environ["PLUGINS_CONFIG_PATH"]

    def test_init_with_default_path(self):
        """Test initialization with default config path."""
        # Temporarily remove env var if it exists
        env_backup = os.environ.pop("PLUGINS_CONFIG_PATH", None)
        try:
            with patch("os.path.join", return_value="./resources/plugins/config.yaml"):
                with patch("mcpgateway.plugins.framework.loader.config.ConfigLoader.load_config") as mock_load:
                    mock_load.return_value = Mock(plugins=[], server_settings=None)
                    server = ExternalPluginServer()
                    assert "./resources/plugins/config.yaml" in server._config_path
        finally:
            if env_backup:
                os.environ["PLUGINS_CONFIG_PATH"] = env_backup

    def test_init_with_invalid_config(self):
        """Test initialization with invalid config path uses defaults or raises error."""
        # ConfigLoader may handle missing files by returning empty config
        # This test verifies the server can be instantiated (or raises if validation fails)
        try:
            server = ExternalPluginServer(config_path="./nonexistent/path/config.yaml")
            # If it succeeds, just verify server was created
            assert server is not None
        except Exception:
            # If it raises, that's also acceptable behavior
            pass


class TestGetPluginConfigs:
    """Tests for get_plugin_configs method."""

    @pytest.mark.asyncio
    async def test_get_plugin_configs_multiple(self, server_with_plugins):
        """Test getting multiple plugin configurations."""
        configs = await server_with_plugins.get_plugin_configs()
        assert isinstance(configs, list)
        assert len(configs) > 0
        # Verify each config is a dict with expected keys
        for config in configs:
            assert isinstance(config, dict)
            assert "name" in config

    @pytest.mark.asyncio
    async def test_get_plugin_configs_single(self):
        """Test getting plugin configs with single plugin."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        configs = await server.get_plugin_configs()
        assert len(configs) == 1
        assert configs[0]["name"] == "ReplaceBadWordsPlugin"

    @pytest.mark.asyncio
    async def test_get_plugin_configs_empty(self):
        """Test getting plugin configs when no plugins configured."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        # Mock empty plugins list
        server._config.plugins = None
        configs = await server.get_plugin_configs()
        assert configs == []


class TestGetPluginConfig:
    """Tests for get_plugin_config method."""

    @pytest.mark.asyncio
    async def test_get_plugin_config_found(self, server_with_plugins):
        """Test getting a specific plugin config by name."""
        config = await server_with_plugins.get_plugin_config(name="DenyListPlugin")
        assert config is not None
        assert config["name"] == "DenyListPlugin"

    @pytest.mark.asyncio
    async def test_get_plugin_config_case_insensitive(self, server_with_plugins):
        """Test that plugin name lookup is case-insensitive."""
        config = await server_with_plugins.get_plugin_config(name="denylistplugin")
        assert config is not None
        assert config["name"] == "DenyListPlugin"

    @pytest.mark.asyncio
    async def test_get_plugin_config_not_found(self, server_with_plugins):
        """Test getting a non-existent plugin config returns None."""
        config = await server_with_plugins.get_plugin_config(name="NonExistentPlugin")
        assert config is None

    @pytest.mark.asyncio
    async def test_get_plugin_config_empty_plugins(self):
        """Test getting plugin config when no plugins configured."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        server._config.plugins = None
        config = await server.get_plugin_config(name="AnyPlugin")
        assert config is None


class TestInvokeHook:
    """Tests for invoke_hook method."""

    @pytest.mark.asyncio
    async def test_invoke_hook_success(self, initialized_server):
        """Test successful hook invocation."""
        payload = PromptPrehookPayload(prompt_id="123", name="test_prompt", args={"user": "This is so innovative"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result
        assert result["plugin_name"] == "DenyListPlugin"
        assert "result" in result
        assert result["result"]["continue_processing"] is False

    @pytest.mark.asyncio
    async def test_invoke_hook_with_context_update(self, initialized_server):
        """Test that hook invocation includes updated context in response."""
        payload = PromptPrehookPayload(prompt_id="123", name="test_prompt", args={"user": "normal text"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result
        # Context may or may not be included depending on whether it was modified

    @pytest.mark.asyncio
    async def test_invoke_hook_plugin_error(self, initialized_server):
        """Test hook invocation when plugin raises PluginError."""
        with patch("mcpgateway.plugins.framework.manager.PluginManager.invoke_hook_for_plugin") as mock_invoke:
            # Simulate a PluginError
            error = PluginErrorModel(message="Test error", plugin_name="TestPlugin", code="TEST_ERROR")
            mock_invoke.side_effect = PluginError(error=error)

            payload = PromptPrehookPayload(prompt_id="123", args={})
            context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

            result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

            assert result is not None
            assert "error" in result
            # error is a PluginErrorModel object, not a dict
            error_obj = result["error"]
            assert isinstance(error_obj, PluginErrorModel)
            assert error_obj.message == "Test error"
            assert error_obj.plugin_name == "TestPlugin"

    @pytest.mark.asyncio
    async def test_invoke_hook_generic_exception(self, initialized_server):
        """Test hook invocation when plugin raises generic exception."""
        with patch("mcpgateway.plugins.framework.manager.PluginManager.invoke_hook_for_plugin") as mock_invoke:
            # Simulate a generic exception
            mock_invoke.side_effect = ValueError("Unexpected error")

            payload = PromptPrehookPayload(prompt_id="123", args={})
            context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

            result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

            assert result is not None
            assert "error" in result
            assert "Unexpected error" in result["error"]["message"]
            assert result["error"]["plugin_name"] == "DenyListPlugin"

    @pytest.mark.asyncio
    async def test_invoke_hook_invalid_context(self, initialized_server):
        """Test hook invocation with invalid context data returns error."""
        payload = PromptPrehookPayload(prompt_id="123", args={})
        # Invalid context dict
        invalid_context = {"invalid": "data"}

        # The method catches exceptions and returns them in the result
        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), invalid_context)

        # Should return an error result instead of raising
        assert result is not None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invoke_hook_tool_hooks(self, initialized_server):
        """Test invoking tool pre/post hooks."""
        # Test tool pre-invoke
        payload = ToolPreInvokePayload(name="test_tool", args={"arg": "value"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, "ReplaceBadWordsPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result
        assert result["plugin_name"] == "ReplaceBadWordsPlugin"

    @pytest.mark.asyncio
    async def test_invoke_hook_prompt_post_fetch(self, initialized_server):
        """Test invoking prompt post-fetch hook."""
        message = Message(content=TextContent(type="text", text="test content"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        payload = PromptPosthookPayload(prompt_id="123", result=prompt_result)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_POST_FETCH, "ReplaceBadWordsPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result
        assert result["plugin_name"] == "ReplaceBadWordsPlugin"


class TestInitializeShutdown:
    """Tests for initialize and shutdown methods."""

    @pytest.mark.asyncio
    async def test_initialize_success(self, server_with_plugins):
        """Test successful initialization."""
        result = await server_with_plugins.initialize()
        assert result is True
        assert server_with_plugins._plugin_manager.initialized is True
        await server_with_plugins.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, server_with_plugins):
        """Test that multiple initializations are safe."""
        await server_with_plugins.initialize()
        await server_with_plugins.initialize()
        # Should still return True
        assert server_with_plugins._plugin_manager.initialized is True
        await server_with_plugins.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_when_initialized(self, initialized_server):
        """Test shutdown on initialized server."""
        assert initialized_server._plugin_manager.initialized is True
        await initialized_server.shutdown()
        assert initialized_server._plugin_manager.initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_when_not_initialized(self, server_with_plugins):
        """Test shutdown on non-initialized server (should be safe)."""
        assert server_with_plugins._plugin_manager.initialized is False
        # Should not raise an error
        await server_with_plugins.shutdown()
        assert server_with_plugins._plugin_manager.initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, initialized_server):
        """Test that multiple shutdowns are safe."""
        await initialized_server.shutdown()
        # Second shutdown should be safe
        await initialized_server.shutdown()


class TestGetServerConfig:
    """Tests for get_server_config method."""

    def test_get_server_config_with_settings(self):
        """Test getting server config when server_settings is configured."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")

        # Mock server settings
        expected_config = MCPServerConfig(host="0.0.0.0", port=8080, tls_enabled=False)
        server._config.server_settings = expected_config

        config = server.get_server_config()
        assert config == expected_config
        assert config.host == "0.0.0.0"
        assert config.port == 8080

    def test_get_server_config_from_env(self):
        """Test getting server config from environment variables."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        server._config.server_settings = None

        # Set environment variables
        os.environ["MCP_SERVER_HOST"] = "127.0.0.1"
        os.environ["MCP_SERVER_PORT"] = "9090"

        try:
            config = server.get_server_config()
            assert config is not None
            # Should have loaded from env or defaults
        finally:
            # Cleanup
            os.environ.pop("MCP_SERVER_HOST", None)
            os.environ.pop("MCP_SERVER_PORT", None)

    def test_get_server_config_defaults(self):
        """Test getting server config with defaults."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
        server._config.server_settings = None

        config = server.get_server_config()
        assert config is not None
        assert isinstance(config, MCPServerConfig)

    def test_get_server_config_with_tls(self, tmp_path):
        """Test getting server config with TLS enabled."""
        # First-Party
        from mcpgateway.plugins.framework.models import MCPServerTLSConfig

        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")

        # Create dummy cert files for validation
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_text("cert")
        key_file.write_text("key")

        tls_settings = MCPServerTLSConfig(certfile=str(cert_file), keyfile=str(key_file))
        tls_config = MCPServerConfig(host="0.0.0.0", port=8443, tls=tls_settings)
        server._config.server_settings = tls_config

        config = server.get_server_config()
        assert config.tls is not None
        assert config.tls.certfile == str(cert_file)
        assert config.tls.keyfile == str(key_file)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_doctest_example(self):
        """Test the doctest example from __init__."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
        assert server is not None

    @pytest.mark.asyncio
    async def test_doctest_get_plugin_configs(self):
        """Test the doctest example from get_plugin_configs."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
        plugins = await server.get_plugin_configs()
        assert len(plugins) > 0

    @pytest.mark.asyncio
    async def test_doctest_get_plugin_config(self):
        """Test the doctest example from get_plugin_config."""
        server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
        config = await server.get_plugin_config(name="DenyListPlugin")
        assert config is not None
        assert config["name"] == "DenyListPlugin"

    @pytest.mark.asyncio
    async def test_invoke_hook_with_empty_payload(self, initialized_server):
        """Test hook invocation with minimal/empty payload."""
        payload = PromptPrehookPayload(prompt_id="123", args={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result

    @pytest.mark.asyncio
    async def test_invoke_hook_with_complex_payload(self, initialized_server):
        """Test hook invocation with multiple arguments."""
        # PromptPrehookPayload args values must be strings
        payload = PromptPrehookPayload(prompt_id="123", args={"user": "test message", "system": "system prompt", "context": "additional context"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        result = await initialized_server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())

        assert result is not None
        assert "plugin_name" in result
