# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Additional unit tests for ExternalPlugin client.
Tests for error conditions, edge cases, and uncovered code paths.
"""

# Standard
import os
import sys
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from mcp.types import CallToolResult, TextContent as MCPTextContent
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, ResourceContent, Role, TextContent, TransportType
from mcpgateway.plugins.framework import (
    ConfigLoader,
    GlobalContext,
    PluginContext,
    PromptHookType,
    ResourceHookType,
    ToolHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.models import MCPClientConfig
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.mcp.client import ExternalPlugin


@pytest.mark.asyncio
async def test_initialize_missing_mcp_config():
    """Test initialize raises ValueError when mcp config is missing."""
    # Use a real config but temporarily remove mcp section
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]

    # Create plugin and temporarily set mcp to None
    plugin = ExternalPlugin(plugin_config)
    plugin._config.mcp = None

    with pytest.raises(PluginError, match="The mcp section must be defined for external plugin"):
        await plugin.initialize()


@pytest.mark.asyncio
async def test_initialize_stdio_missing_script():
    """Test initialize raises ValueError for missing stdio script."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    # Mock the script path to be missing
    plugin._config.mcp.script = "/path/to/missing.sh"

    with pytest.raises(PluginError, match="Server script /path/to/missing.sh does not exist."):
        await plugin.initialize()


@pytest.mark.asyncio
async def test_resolve_stdio_command_from_cmd():
    """Test cmd-based stdio command resolution."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    command, args = plugin._ExternalPlugin__resolve_stdio_command(None, ["node", "server.js", "--flag"], None)
    assert command == "node"
    assert args == ["server.js", "--flag"]


@pytest.mark.asyncio
async def test_resolve_stdio_command_from_script_py():
    """Test script-based stdio command resolution for Python scripts."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    script_path = "mcpgateway/plugins/framework/external/mcp/server/runtime.py"
    command, args = plugin._ExternalPlugin__resolve_stdio_command(script_path, None, None)
    assert command == sys.executable
    assert args == [script_path]


@pytest.mark.asyncio
async def test_initialize_config_retrieval_failure():
    """Test initialize raises ValueError when plugin config retrieval fails."""
    os.environ["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    os.environ["PYTHONPATH"] = "."

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    # Mock stdio connection to succeed but config retrieval to fail
    mock_stdio = Mock()
    mock_write = Mock()
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock()
    mock_session.list_tools.return_value.tools = []

    # Mock get_plugin_config to return empty content (failure)
    mock_session.call_tool = AsyncMock()
    mock_session.call_tool.return_value = CallToolResult(content=[])

    with (
        patch("mcpgateway.plugins.framework.external.mcp.client.stdio_client") as mock_stdio_client,
        patch("mcpgateway.plugins.framework.external.mcp.client.ClientSession", return_value=mock_session),
    ):
        mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=(mock_stdio, mock_write))
        mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(PluginError, match="Unable to retrieve configuration for external plugin"):
            await plugin.initialize()

    # Cleanup
    if "PLUGINS_CONFIG_PATH" in os.environ:
        del os.environ["PLUGINS_CONFIG_PATH"]
    if "PYTHONPATH" in os.environ:
        del os.environ["PYTHONPATH"]


@pytest.mark.asyncio
async def test_hook_methods_empty_content():
    """Test hook methods raise PluginError when content is empty."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    # Set up session mock
    mock_session = AsyncMock()
    plugin._session = mock_session

    # Mock empty content response
    mock_session.call_tool = AsyncMock()
    mock_session.call_tool.return_value = CallToolResult(content=[])

    context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))

    # Test prompt_pre_fetch with empty content - should raise PluginError
    payload = PromptPrehookPayload(prompt_id="1", args={})
    with pytest.raises(PluginError):
        await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

    # Test prompt_post_fetch with empty content - should raise PluginError
    message = Message(content=TextContent(type="text", text="test"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(prompt_id="1", result=prompt_result)
    with pytest.raises(PluginError):
        await plugin.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload, context)

    # Test tool_pre_invoke with empty content - should raise PluginError
    payload = ToolPreInvokePayload(name="test", args={})
    with pytest.raises(PluginError):
        await plugin.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, payload, context)

    # Test tool_post_invoke with empty content - should raise PluginError
    payload = ToolPostInvokePayload(name="test", result={})
    with pytest.raises(PluginError):
        await plugin.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, context)

    # Test resource_pre_fetch with empty content - should raise PluginError
    payload = ResourcePreFetchPayload(uri="file://test.txt")
    with pytest.raises(PluginError):
        await plugin.invoke_hook(ResourceHookType.RESOURCE_PRE_FETCH, payload, context)

    # Test resource_post_fetch with empty content - should raise PluginError
    resource_content = ResourceContent(type="resource", id="123",uri="file://test.txt", text="content")
    payload = ResourcePostFetchPayload(uri="file://test.txt", content=resource_content)
    with pytest.raises(PluginError):
        await plugin.invoke_hook(ResourceHookType.RESOURCE_POST_FETCH, payload, context)

    await plugin.shutdown()


@pytest.mark.asyncio
async def test_get_plugin_config_no_content():
    """Test __get_plugin_config returns None when no content."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    # Set up session mock
    mock_session = AsyncMock()
    plugin._session = mock_session

    # Mock empty content response
    mock_session.call_tool = AsyncMock()
    mock_session.call_tool.return_value = CallToolResult(content=[])

    result = await plugin._ExternalPlugin__get_plugin_config()
    assert result is None

    await plugin.shutdown()


@pytest.mark.asyncio
async def test_get_plugin_config_empty_dict():
    """Test __get_plugin_config returns None on empty config payload."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    mock_session = AsyncMock()
    plugin._session = mock_session

    mock_session.call_tool = AsyncMock()
    mock_session.call_tool.return_value = CallToolResult(content=[MCPTextContent(type="text", text="{}")])

    result = await plugin._ExternalPlugin__get_plugin_config()
    assert result is None

    await plugin.shutdown()


@pytest.mark.asyncio
async def test_shutdown():
    """Test shutdown method calls exit_stack.aclose()."""
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    plugin_config = config.plugins[0]
    plugin = ExternalPlugin(plugin_config)

    # Mock the exit stack
    mock_exit_stack = AsyncMock()
    plugin._exit_stack = mock_exit_stack

    await plugin.shutdown()
    mock_exit_stack.aclose.assert_called_once()


def test_mcp_config_env_rejected_for_http():
    """STDIO-only env should be rejected for HTTP transports."""
    with pytest.raises(ValueError, match="script/cmd/env/cwd are only valid for STDIO transport"):
        MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost:8000/mcp", env={"PLUGINS_CONFIG_PATH": "plugins/config.yaml"})


def test_mcp_config_env_accepts_stdio():
    """STDIO env overrides are accepted for STDIO transports."""
    cfg = MCPClientConfig(
        proto=TransportType.STDIO,
        script="mcpgateway/plugins/framework/external/mcp/server/runtime.py",
        env={"PLUGINS_CONFIG_PATH": "plugins/config.yaml"},
    )
    assert cfg.env is not None


def test_mcp_config_cwd_invalid():
    """STDIO cwd must be a valid directory."""
    with pytest.raises(ValueError, match="MCP stdio cwd"):
        MCPClientConfig(
            proto=TransportType.STDIO,
            script="mcpgateway/plugins/framework/external/mcp/server/runtime.py",
            cwd="/path/to/nowhere",
        )


def test_mcp_config_cwd_valid():
    """STDIO cwd accepts existing directories."""
    cfg = MCPClientConfig(
        proto=TransportType.STDIO,
        script="mcpgateway/plugins/framework/external/mcp/server/runtime.py",
        cwd=".",
    )
    assert cfg.cwd == "."


def test_mcp_config_uds_invalid_transport():
    """UDS is only valid for streamable HTTP."""
    with pytest.raises(ValueError, match="uds is only valid for STREAMABLEHTTP transport"):
        MCPClientConfig(proto=TransportType.STDIO, script="mcpgateway/plugins/framework/external/mcp/server/runtime.py", uds="/tmp/mcp.sock")


def test_mcp_config_uds_accepts_streamable_http():
    """UDS is accepted for streamable HTTP."""
    cfg = MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost/mcp", uds="/tmp/mcp.sock")
    assert cfg.uds == "/tmp/mcp.sock"


def test_mcp_config_uds_tls_rejected():
    """UDS should not allow TLS configuration."""
    with pytest.raises(ValueError, match="TLS configuration is not supported for Unix domain sockets"):
        MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost/mcp", uds="/tmp/mcp.sock", tls={})
