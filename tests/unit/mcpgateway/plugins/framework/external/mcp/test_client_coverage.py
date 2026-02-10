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

    def test_relative_script_resolved_with_cwd(self, tmp_path):
        """Cover the cwd + relative path resolution branch."""
        script = tmp_path / "server.py"
        script.write_text("print('hello')")
        plugin = _make_plugin(_make_stdio_config())
        import sys

        cmd, args = plugin._ExternalPlugin__resolve_stdio_command("server.py", None, str(tmp_path))
        assert cmd == sys.executable
        assert args == [str(script)]

    def test_non_executable_non_script_raises(self, tmp_path):
        """Non-.py/.sh files must be executable."""
        script = tmp_path / "server.bin"
        script.write_text("data")
        script.chmod(0o644)
        plugin = _make_plugin(_make_stdio_config())
        with pytest.raises(PluginError, match="must be executable"):
            plugin._ExternalPlugin__resolve_stdio_command(str(script), None, None)

    def test_executable_non_script_returns_path(self, tmp_path):
        """Executable non-.py/.sh file should be executed directly."""
        script = tmp_path / "server.bin"
        script.write_text("data")
        script.chmod(0o755)
        plugin = _make_plugin(_make_stdio_config())
        cmd, args = plugin._ExternalPlugin__resolve_stdio_command(str(script), None, None)
        assert cmd == str(script)
        assert args == []


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


# ===========================================================================
# initialize
# ===========================================================================


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_requires_mcp_section(self):
        # Use a non-external kind so model validators don't reject missing transport config.
        config = PluginConfig(name="no_mcp", kind="internal", version="1.0.0", hooks=["prompt_pre_fetch"])
        plugin = _make_plugin(config)
        with pytest.raises(PluginError, match="mcp section must be defined"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_stdio_requires_script_or_cmd(self):
        config = _make_stdio_config()
        plugin = _make_plugin(config)
        # Break invariants after model validation so we can exercise initialize() checks.
        object.__setattr__(plugin._config.mcp, "cmd", None)
        object.__setattr__(plugin._config.mcp, "script", None)
        with pytest.raises(PluginError, match="STDIO transport requires script or cmd"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_streamablehttp_requires_url(self):
        config = _make_http_config()
        plugin = _make_plugin(config)
        object.__setattr__(plugin._config.mcp, "url", None)
        with pytest.raises(PluginError, match="STREAMABLEHTTP transport requires url"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_skips_connect_for_other_transports(self):
        """TransportType.SSE isn't handled by initialize() connect logic (falls through)."""
        config = PluginConfig(
            name="sse_plugin",
            kind="external",
            version="1.0.0",
            hooks=["prompt_pre_fetch"],
            mcp=MCPClientConfig(proto=TransportType.SSE, url="http://localhost:9999/mcp"),
        )
        plugin = _make_plugin(config)
        with patch.object(plugin, "shutdown", new=AsyncMock()):
            with pytest.raises(PluginError, match="session not initialized"):
                await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_merges_remote_config(self):
        """Happy path: connect + fetch remote config, then merge with local config."""
        config = _make_http_config()
        plugin = _make_plugin(config)

        remote_config = PluginConfig(
            name=config.name,
            kind="external",
            version="2.0.0",
            description="remote description",
            hooks=config.hooks,
            mcp=config.mcp,
        )

        with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new=AsyncMock()), patch.object(
            plugin, "_ExternalPlugin__get_plugin_config", new=AsyncMock(return_value=remote_config)
        ):
            await plugin.initialize()

        assert plugin.config.description == "remote description"
        # Local config values override remote config (remote is used as base defaults).
        assert plugin.config.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_initialize_when_config_missing_triggers_shutdown_even_if_shutdown_fails(self):
        config = _make_http_config()
        plugin = _make_plugin(config)

        with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new=AsyncMock()), patch.object(
            plugin, "_ExternalPlugin__get_plugin_config", new=AsyncMock(return_value=None)
        ), patch.object(plugin, "shutdown", new=AsyncMock(side_effect=RuntimeError("shutdown fail"))):
            with pytest.raises(PluginError, match="Unable to retrieve configuration"):
                await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_generic_exception_converted_to_pluginerror_and_shutdown_errors_swallowed(self):
        config = _make_http_config()
        plugin = _make_plugin(config)

        with patch.object(plugin, "_ExternalPlugin__connect_to_http_server", new=AsyncMock()), patch.object(
            plugin, "_ExternalPlugin__get_plugin_config", new=AsyncMock(side_effect=ValueError("boom"))
        ), patch.object(plugin, "shutdown", new=AsyncMock(side_effect=RuntimeError("shutdown fail"))):
            with pytest.raises(PluginError):
                await plugin.initialize()


# ===========================================================================
# Additional MCP client branch coverage
# ===========================================================================


class TestHTTPClientFactory:
    @pytest.mark.asyncio
    async def test_http_client_factory_includes_headers_auth_and_tls(self):
        config = _make_http_config()
        # Provide a TLS config so create_ssl_context path is exercised.
        object.__setattr__(config.mcp, "tls", MCPClientTLSConfig(verify=True, check_hostname=True))
        plugin = _make_plugin(config)

        class OkCtx:
            async def __aenter__(self):
                read = AsyncMock()
                write = AsyncMock()
                get_session_id = MagicMock(return_value="sid")
                return read, write, get_session_id

            async def __aexit__(self, *args):
                return False

        mock_session = AsyncMock()
        list_tools_result = MagicMock()
        list_tools_result.tools = []
        mock_session.list_tools = AsyncMock(return_value=list_tools_result)

        with patch("mcpgateway.plugins.framework.external.mcp.client.streamablehttp_client", return_value=OkCtx()), patch(
            "mcpgateway.plugins.framework.external.mcp.client.ClientSession", return_value=mock_session
        ), patch("mcpgateway.plugins.framework.external.mcp.client.create_ssl_context", return_value="sslctx"), patch(
            "mcpgateway.plugins.framework.external.mcp.client.httpx.AsyncClient"
        ) as mock_httpx, patch(
            "mcpgateway.plugins.framework.external.mcp.client.settings"
        ) as mock_settings:
            # Keep limits deterministic
            mock_settings.httpx_max_connections = 10
            mock_settings.httpx_max_keepalive_connections = 5
            mock_settings.httpx_keepalive_expiry = 30
            plugin._exit_stack = AsyncExitStack()
            await plugin._ExternalPlugin__connect_to_http_server("http://localhost:9999/mcp")

            assert plugin._http_client_factory is not None
            plugin._http_client_factory(headers={"x-test": "1"}, auth=httpx.BasicAuth("u", "p"))

        assert mock_httpx.call_count >= 1
        _, kwargs = mock_httpx.call_args
        assert kwargs["headers"]["x-test"] == "1"
        assert kwargs["auth"] is not None
        assert kwargs["verify"] == "sslctx"


class TestGetPluginConfig:
    @pytest.mark.asyncio
    async def test_get_plugin_config_requires_session(self):
        plugin = _make_plugin()
        plugin._session = None
        with pytest.raises(PluginError, match="session not initialized"):
            await plugin._ExternalPlugin__get_plugin_config()

    @pytest.mark.asyncio
    async def test_get_plugin_config_skips_non_text_content(self):
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        conf = PluginConfig(name=plugin.name, kind="external", version="1.0.0", hooks=["prompt_pre_fetch"], mcp=_make_http_config().mcp)
        text_content = TextContent(type="text", text=orjson.dumps(conf.model_dump()).decode())
        call_result = MagicMock()
        call_result.content = [MagicMock(), text_content]
        session.call_tool.return_value = call_result

        loaded = await plugin._ExternalPlugin__get_plugin_config()
        assert loaded is not None
        assert loaded.name == plugin.name

    @pytest.mark.asyncio
    async def test_get_plugin_config_errors_converted(self):
        plugin = _make_plugin()
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=RuntimeError("nope"))
        plugin._session = session
        with pytest.raises(PluginError):
            await plugin._ExternalPlugin__get_plugin_config()


class TestInvokeHookMoreBranches:
    @pytest.mark.asyncio
    async def test_invoke_hook_skips_non_text_content(self):
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        result_data = {"result": {"continue_processing": True}}
        text_content = TextContent(type="text", text=orjson.dumps(result_data).decode())
        call_result = MagicMock()
        call_result.content = [MagicMock(), text_content]
        session.call_tool.return_value = call_result

        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            result = await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), PluginContext(global_context=GlobalContext(request_id="1")))

        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_invoke_hook_call_tool_exception_is_converted(self):
        plugin = _make_plugin()
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
        plugin._session = session
        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            with pytest.raises(PluginError):
                await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), PluginContext(global_context=GlobalContext(request_id="1")))

    @pytest.mark.asyncio
    async def test_invoke_hook_context_only_then_result_loops(self):
        """Exercise the branch where a TextContent payload contains only CONTEXT and the loop continues."""
        plugin = _make_plugin()
        session = AsyncMock()
        plugin._session = session

        ctx_only = {"context": {"state": {"k": "v"}, "metadata": {}, "global_context": {"request_id": "1", "state": {}}}}
        res = {"result": {"continue_processing": True}}
        call_result = MagicMock()
        call_result.content = [
            TextContent(type="text", text=orjson.dumps(ctx_only).decode()),
            TextContent(type="text", text=orjson.dumps(res).decode()),
        ]
        session.call_tool.return_value = call_result

        ctx = PluginContext(global_context=GlobalContext(request_id="1"))
        with patch("mcpgateway.plugins.framework.external.mcp.client.get_hook_registry") as mock_reg:
            mock_reg.return_value.get_result_type.return_value = PluginResult
            result = await plugin.invoke_hook("prompt_pre_fetch", MagicMock(), ctx)

        assert result.continue_processing is True
        assert ctx.state == {"k": "v"}


class TestShutdownMoreBranches:
    @pytest.mark.asyncio
    async def test_shutdown_stdio_task_without_stop_event(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_task = AsyncMock()
        plugin._stdio_stop = None
        plugin._stdio_ready = MagicMock()
        plugin._exit_stack = AsyncMock()
        plugin._session = MagicMock()

        await plugin.shutdown()
        assert plugin._stdio_task is None

    @pytest.mark.asyncio
    async def test_shutdown_cleans_stdio_state_even_when_proto_is_http(self):
        """Weird-but-possible: stdio task exists but config says STREAMABLEHTTP."""
        plugin = _make_plugin(_make_http_config())
        plugin._stdio_task = AsyncMock()
        plugin._stdio_stop = AsyncMock()
        plugin._stdio_stop.set = MagicMock()
        plugin._stdio_ready = MagicMock()
        plugin._exit_stack = None
        plugin._session_id = None

        await plugin.shutdown()
        assert plugin._stdio_task is None


class TestRunStdioSessionBranches:
    @pytest.mark.asyncio
    async def test_run_stdio_session_error_before_exit_stack_sets_ready(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_ready.set()  # already set -> skip set() in finally
        plugin._stdio_stop = None
        plugin._stdio_error = None

        with patch.object(plugin, "_ExternalPlugin__resolve_stdio_command", side_effect=ValueError("bad")):
            await plugin._ExternalPlugin__run_stdio_session(None, ["python"], None, None)

        assert plugin._stdio_error is not None

    @pytest.mark.asyncio
    async def test_run_stdio_session_error_after_exit_stack_closes_exit_stack(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_stop = None
        plugin._stdio_error = None

        class FailCtx:
            async def __aenter__(self):
                raise RuntimeError("enter failed")

            async def __aexit__(self, *args):
                return False

        with patch("mcpgateway.plugins.framework.external.mcp.client.stdio_client", return_value=FailCtx()):
            await plugin._ExternalPlugin__run_stdio_session(None, ["python"], None, None)

        assert plugin._stdio_error is not None

    @pytest.mark.asyncio
    async def test_run_stdio_session_waits_on_stop_and_skips_close_when_exit_stack_cleared(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_stop = asyncio.Event()
        plugin._stdio_error = None

        after_list_tools = asyncio.Event()

        async def _list_tools_side_effect():
            after_list_tools.set()
            res = MagicMock()
            res.tools = []
            return res

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(side_effect=_list_tools_side_effect)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        class OkCtx:
            async def __aenter__(self):
                return AsyncMock(), AsyncMock()

            async def __aexit__(self, *args):
                return False

        async def flip_exit_stack():
            await after_list_tools.wait()
            # Let __run_stdio_session reach the wait() point.
            await asyncio.sleep(0)
            plugin._stdio_exit_stack = None
            plugin._stdio_stop.set()

        flip_task = asyncio.create_task(flip_exit_stack())
        try:
            with patch.object(plugin, "_ExternalPlugin__resolve_stdio_command", return_value=("python", ["-c", "pass"])), patch(
                "mcpgateway.plugins.framework.external.mcp.client.stdio_client", return_value=OkCtx()
            ), patch("mcpgateway.plugins.framework.external.mcp.client.ClientSession", return_value=mock_session):
                await plugin._ExternalPlugin__run_stdio_session(None, ["python"], None, None)
        finally:
            await flip_task

    @pytest.mark.asyncio
    async def test_run_stdio_session_success_without_stop_event(self):
        """Cover the branch where _stdio_stop is falsy and we skip waiting."""
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_stop = None
        plugin._stdio_error = None

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

        class OkCtx:
            async def __aenter__(self):
                return AsyncMock(), AsyncMock()

            async def __aexit__(self, *args):
                return False

        with patch.object(plugin, "_ExternalPlugin__resolve_stdio_command", return_value=("python", ["-c", "pass"])), patch(
            "mcpgateway.plugins.framework.external.mcp.client.stdio_client", return_value=OkCtx()
        ), patch("mcpgateway.plugins.framework.external.mcp.client.ClientSession", return_value=mock_session):
            await plugin._ExternalPlugin__run_stdio_session(None, ["python"], None, None)

        assert plugin._stdio_error is None


class TestConnectStdioBranches:
    @pytest.mark.asyncio
    async def test_connect_to_stdio_server_reuses_existing_events(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_ready.set()
        plugin._stdio_stop = asyncio.Event()

        # Patch the worker coroutine, but let create_task schedule it to avoid un-awaited coroutine warnings.
        with patch.object(plugin, "_ExternalPlugin__run_stdio_session", new=AsyncMock()):
            await plugin._ExternalPlugin__connect_to_stdio_server(None, ["python", "-c", "pass"], None, None)

        assert plugin._stdio_task is not None

    @pytest.mark.asyncio
    async def test_connect_to_stdio_server_create_task_error_converted(self):
        plugin = _make_plugin(_make_stdio_config())
        plugin._stdio_ready = asyncio.Event()
        plugin._stdio_ready.set()
        plugin._stdio_stop = asyncio.Event()

        def _raise(coro, *args, **kwargs):
            coro.close()
            raise RuntimeError("boom")

        with patch("mcpgateway.plugins.framework.external.mcp.client.asyncio.create_task", side_effect=_raise):
            with pytest.raises(PluginError):
                await plugin._ExternalPlugin__connect_to_stdio_server(None, ["python", "-c", "pass"], None, None)


class TestConnectHTTPMoreBranches:
    @pytest.mark.asyncio
    async def test_connect_http_range_empty_exits_loop(self):
        plugin = _make_plugin()
        plugin._exit_stack = AsyncExitStack()
        with patch("mcpgateway.plugins.framework.external.mcp.client.range", return_value=[]):
            # No attempts performed; should just fall through and return.
            await plugin._ExternalPlugin__connect_to_http_server("http://localhost:9999/mcp")


class TestTerminateHTTPSessionErrors:
    @pytest.mark.asyncio
    async def test_terminate_http_session_delete_failure_is_swallowed(self, caplog):
        plugin = _make_plugin()
        plugin._session_id = "sid"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.delete = AsyncMock(side_effect=RuntimeError("delete failed"))

        plugin._http_client_factory = MagicMock(return_value=mock_client)
        with caplog.at_level("DEBUG"):
            await plugin._ExternalPlugin__terminate_http_session()

        assert any("Failed to terminate streamable HTTP session" in r.message for r in caplog.records)
