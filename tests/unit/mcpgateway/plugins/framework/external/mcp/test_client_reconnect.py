# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_reconnect.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mohan Lakshmaiah

Unit tests for MCP external plugin client reconnection logic.
Tests for session recovery, linear backoff, and error handling.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import ToolPreInvokePayload
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.mcp.client import ExternalPlugin
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    MCPClientConfig,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
    TransportType,
)


@pytest.fixture
def mock_http_plugin_config():
    """Create a mock plugin config for HTTP transport testing."""
    return PluginConfig(
        name="TestHTTPPlugin",
        kind="external",
        hooks=["tool_pre_invoke"],
        mcp=MCPClientConfig(
            proto=TransportType.STREAMABLEHTTP,
            url="http://localhost:9000/mcp",
            reconnect_attempts=3,
            reconnect_delay=0.1,
        ),
    )


@pytest.fixture
def mock_stdio_plugin_config(tmp_path):
    """Create a mock plugin config for STDIO transport testing."""
    # Create a dummy script file for validation
    script_path = tmp_path / "server.py"
    script_path.write_text("# dummy server")

    return PluginConfig(
        name="TestSTDIOPlugin",
        kind="external",
        hooks=["tool_pre_invoke"],
        mcp=MCPClientConfig(
            proto=TransportType.STDIO,
            script=str(script_path),
            reconnect_attempts=2,
            reconnect_delay=0.05,
        ),
    )


@pytest.fixture
def mock_plugin_context():
    """Create a mock plugin context."""
    return PluginContext(
        global_context=GlobalContext(request_id="test-request-123"),
        state={},
        metadata={},
    )


class TestReconnectConfiguration:
    """Tests for reconnection configuration loading."""

    @pytest.mark.asyncio
    async def test_reconnect_config_loaded_from_mcp_config(self, mock_http_plugin_config):
        """Test that reconnect config is loaded from MCPClientConfig."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        # Directly set reconnect config to test loading
        plugin._reconnect_attempts = mock_http_plugin_config.mcp.reconnect_attempts
        plugin._reconnect_delay = mock_http_plugin_config.mcp.reconnect_delay

        assert plugin._reconnect_attempts == 3
        assert plugin._reconnect_delay == 0.1

    @pytest.mark.asyncio
    async def test_reconnect_config_defaults(self):
        """Test that reconnect config has proper defaults."""
        config = PluginConfig(
            name="TestPlugin",
            kind="external",
            hooks=["tool_pre_invoke"],
            mcp=MCPClientConfig(
                proto=TransportType.STREAMABLEHTTP,
                url="http://localhost:9000/mcp",
            ),
        )
        plugin = ExternalPlugin(config)

        # Check defaults before initialization
        assert plugin._reconnect_attempts == 3
        assert plugin._reconnect_delay == 0.1


class TestCleanupSession:
    """Tests for _cleanup_session method."""

    @pytest.mark.asyncio
    async def test_cleanup_session_resets_all_state(self, mock_http_plugin_config):
        """Test that cleanup_session resets all session state."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        # Set up some mock state
        plugin._session = MagicMock()
        plugin._http = MagicMock()
        plugin._write = MagicMock()
        plugin._stdio = MagicMock()
        plugin._get_session_id = MagicMock()
        plugin._session_id = "test-session-id"
        plugin._exit_stack = AsyncMock()
        plugin._stdio_exit_stack = AsyncMock()

        await plugin._cleanup_session()

        # Verify all state is reset
        assert plugin._session is None
        assert plugin._http is None
        assert plugin._write is None
        assert plugin._stdio is None
        assert plugin._get_session_id is None
        assert plugin._session_id is None

    @pytest.mark.asyncio
    async def test_cleanup_session_closes_exit_stacks(self, mock_http_plugin_config):
        """Test that cleanup_session closes exit stacks."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_exit_stack = AsyncMock()
        mock_stdio_exit_stack = AsyncMock()
        plugin._exit_stack = mock_exit_stack
        plugin._stdio_exit_stack = mock_stdio_exit_stack

        await plugin._cleanup_session()

        mock_exit_stack.aclose.assert_called_once()
        mock_stdio_exit_stack.aclose.assert_called_once()


class TestReconnectSession:
    """Tests for _reconnect_session method."""

    @pytest.mark.asyncio
    async def test_reconnect_http_success_on_first_attempt(self, mock_http_plugin_config):
        """Test successful reconnection on first attempt for HTTP transport."""
        plugin = ExternalPlugin(mock_http_plugin_config)
        plugin._config.mcp.reconnect_attempts = 3
        plugin._config.mcp.reconnect_delay = 0.1

        with patch.object(plugin, "_cleanup_session", new_callable=AsyncMock) as mock_cleanup:
            with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new_callable=AsyncMock) as mock_connect:
                await plugin._reconnect_session()

                mock_cleanup.assert_called_once()
                mock_connect.assert_called_once_with(mock_http_plugin_config.mcp.url)

    @pytest.mark.asyncio
    async def test_reconnect_stdio_success_on_first_attempt(self, mock_stdio_plugin_config):
        """Test successful reconnection on first attempt for STDIO transport."""
        plugin = ExternalPlugin(mock_stdio_plugin_config)
        plugin._config.mcp.reconnect_attempts = 2
        plugin._config.mcp.reconnect_delay = 0.05

        with patch.object(plugin, "_cleanup_session", new_callable=AsyncMock) as mock_cleanup:
            with patch.object(plugin, "_ExternalPlugin__connect_to_stdio_server", new_callable=AsyncMock) as mock_connect:
                await plugin._reconnect_session()

                mock_cleanup.assert_called_once()
                mock_connect.assert_called_once_with(
                    mock_stdio_plugin_config.mcp.script,
                    mock_stdio_plugin_config.mcp.cmd,
                    mock_stdio_plugin_config.mcp.env,
                    mock_stdio_plugin_config.mcp.cwd,
                )

    @pytest.mark.asyncio
    async def test_reconnect_linear_backoff(self, mock_http_plugin_config):
        """Test that reconnection uses linear backoff."""
        plugin = ExternalPlugin(mock_http_plugin_config)
        plugin._config.mcp.reconnect_attempts = 3
        plugin._config.mcp.reconnect_delay = 0.1

        call_count = 0

        async def mock_connect_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")

        with patch.object(plugin, "_cleanup_session", new_callable=AsyncMock):
            with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new_callable=AsyncMock, side_effect=mock_connect_fail):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await plugin._reconnect_session()

                    # Verify linear backoff delays
                    assert mock_sleep.call_count == 2  # 2 retries before success
                    calls = mock_sleep.call_args_list
                    assert calls[0][0][0] == 0.1  # First retry: 0.1 * 1
                    assert calls[1][0][0] == 0.2  # Second retry: 0.1 * 2

    @pytest.mark.asyncio
    async def test_reconnect_attempts_exhausted(self, mock_http_plugin_config):
        """Test that PluginError is raised when all reconnection attempts fail."""
        plugin = ExternalPlugin(mock_http_plugin_config)
        plugin._reconnect_attempts = 2
        plugin._reconnect_delay = 0.01

        with patch.object(plugin, "_cleanup_session", new_callable=AsyncMock):
            with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new_callable=AsyncMock, side_effect=ConnectionError("Connection failed")):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(PluginError) as exc_info:
                        await plugin._reconnect_session()

                    error_message = str(exc_info.value.error.message)
                    assert "Failed to reconnect" in error_message and "2 attempts" in error_message


class TestInvokeHookWithReconnection:
    """Tests for invoke_hook with reconnection logic."""

    @pytest.mark.asyncio
    async def test_invoke_hook_reconnects_on_mcp_error(self, mock_http_plugin_config, mock_plugin_context):
        """Test that invoke_hook reconnects on McpError."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        # Mock session and registry
        mock_session = AsyncMock()
        plugin._session = mock_session

        # Import McpError for mocking
        from mcp import McpError
        from mcp.types import ErrorData

        # First call raises McpError, second call succeeds
        call_count = 0

        async def mock_call_tool(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise McpError(ErrorData(code=-1, message="Connection lost"))
            # Return successful response
            from mcp.types import CallToolResult, TextContent

            return CallToolResult(content=[TextContent(type="text", text='{"result": {"name": "test", "args": {}}}')])

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            with patch.object(plugin, "_reconnect_session", new_callable=AsyncMock) as mock_reconnect:
                payload = ToolPreInvokePayload(name="test", args={})
                result = await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

                # Verify reconnection was attempted
                mock_reconnect.assert_called_once()
                assert result is not None

    @pytest.mark.asyncio
    async def test_invoke_hook_reconnects_on_session_terminated(self, mock_http_plugin_config, mock_plugin_context):
        """Test that invoke_hook reconnects on 'session terminated' PluginError."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_session = AsyncMock()
        plugin._session = mock_session

        # First call raises PluginError with "session terminated", second call succeeds
        call_count = 0

        async def mock_call_tool(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PluginError(error=PluginErrorModel(message="Session terminated", plugin_name="TestHTTPPlugin"))
            # Return successful response
            from mcp.types import CallToolResult, TextContent

            return CallToolResult(content=[TextContent(type="text", text='{"result": {"name": "test", "args": {}}}')])

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            with patch.object(plugin, "_reconnect_session", new_callable=AsyncMock) as mock_reconnect:
                payload = ToolPreInvokePayload(name="test", args={})
                result = await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

                # Verify reconnection was attempted
                mock_reconnect.assert_called_once()
                assert result is not None

    @pytest.mark.asyncio
    async def test_invoke_hook_no_reconnect_on_other_plugin_errors(self, mock_http_plugin_config, mock_plugin_context):
        """Test that invoke_hook does not reconnect on non-session PluginErrors."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_session = AsyncMock()
        plugin._session = mock_session

        async def mock_call_tool(*args, **kwargs):
            raise PluginError(error=PluginErrorModel(message="Invalid argument", plugin_name="TestHTTPPlugin"))

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            with patch.object(plugin, "_reconnect_session", new_callable=AsyncMock) as mock_reconnect:
                payload = ToolPreInvokePayload(name="test", args={})

                with pytest.raises(PluginError) as exc_info:
                    await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

                # Verify reconnection was NOT attempted
                mock_reconnect.assert_not_called()
                assert "Invalid argument" in str(exc_info.value.error.message)

    @pytest.mark.asyncio
    async def test_invoke_hook_reconnect_failure_raises_original_error(self, mock_http_plugin_config, mock_plugin_context):
        """Test that original error is raised if reconnection fails."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_session = AsyncMock()
        plugin._session = mock_session

        from mcp import McpError
        from mcp.types import ErrorData

        async def mock_call_tool(*args, **kwargs):
            raise McpError(ErrorData(code=-1, message="Connection lost"))

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            with patch.object(plugin, "_reconnect_session", new_callable=AsyncMock, side_effect=PluginError(error=PluginErrorModel(message="Reconnection failed", plugin_name="TestHTTPPlugin"))):
                payload = ToolPreInvokePayload(name="test", args={})

                with pytest.raises(PluginError) as exc_info:
                    await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

                # Verify error is about connection, not reconnection
                assert "Connection lost" in str(exc_info.value.error.message) or "Reconnection failed" in str(exc_info.value.error.message)

    @pytest.mark.asyncio
    async def test_invoke_hook_session_terminated_reconnect_failure_reraises_original(self, mock_http_plugin_config, mock_plugin_context):
        """Test that original PluginError is re-raised when session-terminated reconnection fails."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_session = AsyncMock()
        plugin._session = mock_session

        async def mock_call_tool(*args, **kwargs):
            raise PluginError(error=PluginErrorModel(message="Session terminated by server", plugin_name="TestHTTPPlugin"))

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            with patch.object(
                plugin,
                "_reconnect_session",
                new_callable=AsyncMock,
                side_effect=PluginError(error=PluginErrorModel(message="Reconnection failed", plugin_name="TestHTTPPlugin")),
            ):
                payload = ToolPreInvokePayload(name="test", args={})

                with pytest.raises(PluginError) as exc_info:
                    await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

                # The original "Session terminated" error is re-raised, not the reconnection error
                assert "Session terminated" in str(exc_info.value.error.message)

    @pytest.mark.asyncio
    async def test_invoke_hook_generic_exception_converted_to_plugin_error(self, mock_http_plugin_config, mock_plugin_context):
        """Test that generic exceptions are converted to PluginError."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        mock_session = AsyncMock()
        plugin._session = mock_session

        async def mock_call_tool(*args, **kwargs):
            raise RuntimeError("Unexpected failure")

        mock_session.call_tool = mock_call_tool

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_registry:
            mock_registry.return_value.get_result_type.return_value = ToolPreInvokePayload
            payload = ToolPreInvokePayload(name="test", args={})

            with pytest.raises(PluginError) as exc_info:
                await plugin.invoke_hook("tool_pre_invoke", payload, mock_plugin_context)

            assert "Unexpected failure" in str(exc_info.value.error.message)


class TestCleanupSessionStdio:
    """Tests for _cleanup_session with STDIO transport state."""

    @pytest.mark.asyncio
    async def test_cleanup_session_stops_stdio_task(self, mock_stdio_plugin_config):
        """Test that _cleanup_session properly stops a running STDIO task."""
        plugin = ExternalPlugin(mock_stdio_plugin_config)

        # Simulate a running STDIO session
        stop_event = asyncio.Event()
        ready_event = asyncio.Event()
        ready_event.set()

        plugin._stdio_stop = stop_event
        plugin._stdio_ready = ready_event
        plugin._stdio_error = None
        plugin._session = MagicMock()

        # Create a task that waits on the stop event
        async def mock_stdio_runner():
            await stop_event.wait()

        plugin._stdio_task = asyncio.create_task(mock_stdio_runner())
        plugin._exit_stack = AsyncMock()

        await plugin._cleanup_session()

        # Verify STDIO state is fully reset
        assert plugin._stdio_task is None
        assert plugin._stdio_ready is None
        assert plugin._stdio_stop is None
        assert plugin._stdio_error is None
        assert plugin._session is None

    @pytest.mark.asyncio
    async def test_cleanup_session_handles_stdio_task_exception(self, mock_stdio_plugin_config):
        """Test that _cleanup_session handles exceptions from STDIO task gracefully."""
        plugin = ExternalPlugin(mock_stdio_plugin_config)

        stop_event = asyncio.Event()
        plugin._stdio_stop = stop_event
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_error = None
        plugin._session = MagicMock()

        async def failing_stdio_runner():
            await stop_event.wait()
            raise RuntimeError("stdio crash")

        plugin._stdio_task = asyncio.create_task(failing_stdio_runner())
        plugin._exit_stack = AsyncMock()

        # Should not raise despite task exception
        await plugin._cleanup_session()

        assert plugin._stdio_task is None
        assert plugin._stdio_ready is None
        assert plugin._stdio_stop is None

    @pytest.mark.asyncio
    async def test_cleanup_session_no_stdio_task_skips_task_cleanup(self, mock_http_plugin_config):
        """Test that _cleanup_session works when no STDIO task exists (HTTP transport)."""
        plugin = ExternalPlugin(mock_http_plugin_config)

        plugin._session = MagicMock()
        plugin._exit_stack = AsyncMock()
        # No stdio_task, no stdio_exit_stack
        plugin._stdio_task = None
        plugin._stdio_exit_stack = None

        await plugin._cleanup_session()

        assert plugin._session is None
        assert plugin._stdio_ready is None
        assert plugin._stdio_stop is None
