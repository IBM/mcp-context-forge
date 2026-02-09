# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.external.mcp.client."""

# Standard
import asyncio
from contextlib import AsyncExitStack
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from mcp.types import TextContent
import orjson
import pytest

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.plugins.framework.base import PluginRef
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.mcp.client import ExternalHookRef, ExternalPlugin
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    MCPClientConfig,
    MCPClientTLSConfig,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
    PluginResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_config(url: str = "http://localhost:9999/mcp", **overrides) -> PluginConfig:
    defaults = dict(
        name="ext_plugin",
        kind="external",
        version="1.0.0",
        hooks=["prompt_pre_fetch"],
        mcp=MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url=url),
    )
    defaults.update(overrides)
    return PluginConfig(**defaults)


def _make_stdio_config(**overrides) -> PluginConfig:
    defaults = dict(
        name="ext_stdio_plugin",
        kind="external",
        version="1.0.0",
        hooks=["prompt_pre_fetch"],
        mcp=MCPClientConfig(proto=TransportType.STDIO, cmd=["python", "-m", "server"]),
    )
    defaults.update(overrides)
    return PluginConfig(**defaults)


def _make_plugin(config: PluginConfig | None = None) -> ExternalPlugin:
    with patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.current_task", return_value=None):
        return ExternalPlugin(config or _make_http_config())


# ===========================================================================
# ExternalHookRef
# ===========================================================================


class TestExternalHookRef:
    @pytest.mark.asyncio
    async def test_success(self):
        plugin = _make_plugin()
        ref = PluginRef(plugin)
        hook_ref = ExternalHookRef("prompt_pre_fetch", ref)
        assert hook_ref.name == "prompt_pre_fetch"
        assert hook_ref.plugin_ref is ref
        assert hook_ref.hook is not None

    @pytest.mark.asyncio
    async def test_not_external_raises(self):
        from mcpgateway.plugins.framework.base import Plugin

        config = PluginConfig(name="basic", kind="test.Plugin", version="1.0", hooks=["hook"])
        plugin = Plugin(config)
        ref = PluginRef(plugin)
        with pytest.raises(PluginError, match="is not an external plugin"):
            ExternalHookRef("hook", ref)


# ===========================================================================
# invoke_hook
# ===========================================================================


class TestInvokeHook:
    @pytest.mark.asyncio
    async def test_no_result_type_raises(self):
        plugin = _make_plugin()
        plugin._session = AsyncMock()
        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = None
            with pytest.raises(PluginError, match="not registered"):
                await plugin.invoke_hook("unknown_hook", MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_no_session_raises(self):
        plugin = _make_plugin()
        plugin._session = None
        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            with pytest.raises(PluginError, match="session not initialized"):
                await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_context_update(self):
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        result_data = {
            "context": {
                "state": {"key": "val"},
                "metadata": {"mk": "mv"},
                "global_context": {"request_id": "1", "state": {"gs": "gv"}},
            },
            "result": {"continue_processing": True},
        }
        text_content = TextContent(type="text", text=orjson.dumps(result_data).decode())
        call_result = MagicMock()
        call_result.content = [text_content]
        session.call_tool.return_value = call_result

        ctx = PluginContext(global_context=GlobalContext(request_id="1"))

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            result = await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), ctx)

        assert result.continue_processing is True
        assert ctx.state == {"key": "val"}
        assert ctx.metadata == {"mk": "mv"}
        assert ctx.global_context.state == {"gs": "gv"}

    @pytest.mark.asyncio
    async def test_json_decode_error(self):
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        text_content = TextContent(type="text", text="not-valid-json{{{")
        call_result = MagicMock()
        call_result.content = [text_content]
        session.call_tool.return_value = call_result

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            with pytest.raises(PluginError, match="Error trying to decode json"):
                await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_error_response(self):
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        result_data = {"error": {"message": "bad", "plugin_name": "ext_plugin"}}
        text_content = TextContent(type="text", text=orjson.dumps(result_data).decode())
        call_result = MagicMock()
        call_result.content = [text_content]
        session.call_tool.return_value = call_result

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            with pytest.raises(PluginError, match="bad"):
                await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), MagicMock())


# ===========================================================================
# HTTP connection retry
# ===========================================================================


class TestConnectHTTP:
    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        plugin = _make_plugin()
        call_count = 0

        class MockCtx:
            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("refused")
                read = AsyncMock()
                write = AsyncMock()
                get_session_id = MagicMock(return_value="sid")
                return read, write, get_session_id

            async def __aexit__(self, *args):
                pass

        def mock_streamable(*args, **kwargs):
            return MockCtx()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        list_tools_result = MagicMock()
        list_tools_result.tools = []
        mock_session.list_tools = AsyncMock(return_value=list_tools_result)

        with patch("mcpgateway.plugins.framework.external.mcp.client.streamablehttp_client", side_effect=mock_streamable), \
             patch("mcpgateway.plugins.framework.external.mcp.client.ClientSession", return_value=mock_session), \
             patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.sleep", new_callable=AsyncMock):
            plugin._exit_stack = AsyncExitStack()
            await plugin._ExternalPlugin__connect_to_http_server("http://localhost:9999/mcp")

    @pytest.mark.asyncio
    async def test_all_retries_fail(self):
        plugin = _make_plugin()

        class MockCtx:
            async def __aenter__(self):
                raise ConnectionError("refused")

            async def __aexit__(self, *args):
                pass

        def mock_streamable(*args, **kwargs):
            return MockCtx()

        with patch("mcpgateway.plugins.framework.external.mcp.client.streamablehttp_client", side_effect=mock_streamable), \
             patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.sleep", new_callable=AsyncMock):
            plugin._exit_stack = AsyncExitStack()
            with pytest.raises(PluginError, match="connection failed after 3 attempts"):
                await plugin._ExternalPlugin__connect_to_http_server("http://localhost:9999/mcp")


# ===========================================================================
# Shutdown
# ===========================================================================


class TestShutdown:
    @pytest.mark.asyncio
    async def test_stdio_cleanup(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_task = AsyncMock()
        plugin._stdio_stop = AsyncMock()
        plugin._stdio_stop.set = MagicMock()
        plugin._stdio_ready = MagicMock()
        plugin._stdio_exit_stack = MagicMock()
        plugin._stdio_error = None
        plugin._stdio = MagicMock()
        plugin._write = MagicMock()
        plugin._session = MagicMock()
        plugin._exit_stack = AsyncMock()

        await plugin.shutdown()

        assert plugin._stdio_task is None
        assert plugin._stdio_ready is None
        assert plugin._stdio_stop is None
        assert plugin._session is None

    @pytest.mark.asyncio
    async def test_stdio_error_during_shutdown(self):
        plugin = _make_plugin(_make_stdio_config())

        async def raise_error():
            raise RuntimeError("shutdown fail")

        plugin._stdio_task = AsyncMock(side_effect=raise_error)
        plugin._stdio_stop = AsyncMock()
        plugin._stdio_stop.set = MagicMock()
        plugin._stdio_ready = MagicMock()
        plugin._stdio_exit_stack = MagicMock()
        plugin._stdio = MagicMock()
        plugin._write = MagicMock()
        plugin._session = MagicMock()
        plugin._exit_stack = AsyncMock()

        # Should not raise
        await plugin.shutdown()
        assert plugin._stdio_task is None


# ===========================================================================
# Terminate HTTP session
# ===========================================================================


class TestTerminateHTTPSession:
    @pytest.mark.asyncio
    async def test_no_session_id_returns(self):
        plugin = _make_plugin()
        plugin._session_id = None
        # Should return early without error
        await plugin._ExternalPlugin__terminate_http_session()

    @pytest.mark.asyncio
    async def test_with_factory(self):
        plugin = _make_plugin()
        plugin._session_id = "test-session"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        plugin._http_client_factory = MagicMock(return_value=mock_client)

        await plugin._ExternalPlugin__terminate_http_session()
        mock_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_factory(self):
        plugin = _make_plugin()
        plugin._session_id = "test-session"
        plugin._http_client_factory = None

        with patch("mcpgateway.plugins.framework.external.mcp.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await plugin._ExternalPlugin__terminate_http_session()
            mock_client.delete.assert_called_once()


# ===========================================================================
# Command Resolution
# ===========================================================================


class TestResolveStdioCommand:
    def test_sh_script(self, tmp_path):
        script = tmp_path / "server.sh"
        script.write_text("#!/bin/sh\necho hello")
        plugin = _make_plugin(_make_stdio_config())
        cmd, args = plugin._ExternalPlugin__resolve_stdio_command(str(script), None, None)
        assert cmd == "sh"
        assert args == [str(script)]

    def test_invalid_cmd(self):
        plugin = _make_plugin(_make_stdio_config())
        with pytest.raises(PluginError, match="non-empty list"):
            plugin._ExternalPlugin__resolve_stdio_command(None, [""], None)

    def test_no_script_no_cmd(self):
        plugin = _make_plugin(_make_stdio_config())
        with pytest.raises(PluginError, match="requires script or cmd"):
            plugin._ExternalPlugin__resolve_stdio_command(None, None, None)

    def test_cmd_success(self):
        plugin = _make_plugin(_make_stdio_config())
        cmd, args = plugin._ExternalPlugin__resolve_stdio_command(None, ["python", "-m", "server"], None)
        assert cmd == "python"
        assert args == ["-m", "server"]

    def test_nonexistent_script(self, tmp_path):
        plugin = _make_plugin(_make_stdio_config())
        with pytest.raises(PluginError, match="does not exist"):
            plugin._ExternalPlugin__resolve_stdio_command(str(tmp_path / "nonexistent.py"), None, None)

    def test_python_script(self, tmp_path):
        script = tmp_path / "server.py"
        script.write_text("print('hello')")
        plugin = _make_plugin(_make_stdio_config())
        import sys

        cmd, args = plugin._ExternalPlugin__resolve_stdio_command(str(script), None, None)
        assert cmd == sys.executable
        assert args == [str(script)]


# ===========================================================================
# UDS + TLS warning
# ===========================================================================


class TestResolveStdioCommandSync:
    """Tests that don't need async context — use patched ExternalPlugin."""

    def test_build_stdio_env(self):
        """Test __build_stdio_env merges env correctly."""
        with patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.current_task", return_value=None):
            plugin = _make_plugin(_make_stdio_config())
        env = plugin._ExternalPlugin__build_stdio_env({"MY_VAR": "val"})
        assert env["MY_VAR"] == "val"
        assert "PATH" in env  # should include current env


class TestConnectHTTPUDS:
    @pytest.mark.asyncio
    async def test_uds_with_tls_warning(self, caplog):
        """When uds_path is set with TLS config, warn that TLS is ignored."""
        # Cannot create config with both uds and tls due to model validator,
        # so we test the internal code path by setting attributes after creation
        config = _make_http_config()
        plugin = _make_plugin(config)
        plugin._config.mcp.uds = "/tmp/test.sock"
        # Set a TLS config directly (bypassing validation)
        tls_config = MagicMock()
        object.__setattr__(plugin._config.mcp, "tls", tls_config)

        class FailCtx:
            async def __aenter__(self):
                raise ConnectionError("fail")

            async def __aexit__(self, *args):
                pass

        # Mock the connection to fail immediately so we can check the warning
        with patch("mcpgateway.plugins.framework.external.mcp.client.streamablehttp_client", return_value=FailCtx()), \
             patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.sleep", new_callable=AsyncMock), \
             pytest.raises(PluginError):
            plugin._exit_stack = AsyncExitStack()
            await plugin._ExternalPlugin__connect_to_http_server("http://localhost:9999/mcp")

        assert any("TLS configuration is ignored" in r.message for r in caplog.records)
