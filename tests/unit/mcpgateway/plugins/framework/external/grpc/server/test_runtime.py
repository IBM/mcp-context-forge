# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/server/test_runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC plugin server runtime.
Tests for GrpcPluginRuntime initialization, start, and stop.
"""

# Standard
import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# Check if grpc is available
try:
    import grpc  # noqa: F401

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed")

# First-Party
from mcpgateway.plugins.framework.models import GRPCServerConfig, GRPCServerTLSConfig


class TestGrpcPluginRuntimeInit:
    """Tests for GrpcPluginRuntime initialization."""

    def test_init_default_config(self):
        """Test runtime initialization with default config."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()
        # config_path can be None (will use default path later)
        assert runtime._host_override is None
        assert runtime._port_override is None

    def test_init_with_config_path(self):
        """Test runtime initialization with custom config path."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime(config_path="/custom/config.yaml")
        assert runtime._config_path == "/custom/config.yaml"

    def test_init_with_host_port_override(self):
        """Test runtime initialization with host/port override."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime(host="127.0.0.1", port=50052)
        assert runtime._host_override == "127.0.0.1"
        assert runtime._port_override == 50052


class TestGrpcPluginRuntimeGetServerConfig:
    """Tests for GrpcPluginRuntime._get_server_config."""

    def test_get_server_config_from_plugin_server(self):
        """Test getting server config from plugin server."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()

        mock_plugin_server = MagicMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(
            return_value=GRPCServerConfig(host="192.168.1.1", port=50053)
        )
        runtime._plugin_server = mock_plugin_server

        config = runtime._get_server_config()
        assert config.host == "192.168.1.1"
        assert config.port == 50053

    def test_get_server_config_from_env(self):
        """Test getting server config from environment variables."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()

        mock_plugin_server = MagicMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=None)
        runtime._plugin_server = mock_plugin_server

        env_vars = {
            "PLUGINS_GRPC_SERVER_HOST": "10.0.0.1",
            "PLUGINS_GRPC_SERVER_PORT": "50054",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch.object(GRPCServerConfig, "from_env", return_value=GRPCServerConfig(host="10.0.0.1", port=50054)):
                config = runtime._get_server_config()
                assert config.host == "10.0.0.1"
                assert config.port == 50054

    def test_get_server_config_defaults(self):
        """Test getting default server config when no config available."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()

        mock_plugin_server = MagicMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=None)
        runtime._plugin_server = mock_plugin_server

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(GRPCServerConfig, "from_env", return_value=None):
                config = runtime._get_server_config()
                # Should return default config
                assert config.host == "127.0.0.1"
                assert config.port == 50051


class TestGrpcPluginRuntimeStart:
    """Tests for GrpcPluginRuntime.start."""

    @pytest.mark.asyncio
    async def test_start_creates_server(self):
        """Test start creates gRPC server."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()

        mock_plugin_server = AsyncMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=GRPCServerConfig())
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        mock_grpc_server = MagicMock()
        mock_grpc_server.start = AsyncMock()
        mock_grpc_server.add_insecure_port = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.ExternalPluginServer",
            return_value=mock_plugin_server,
        ):
            with patch("grpc.aio.server", return_value=mock_grpc_server):
                # Start in background and immediately trigger shutdown
                runtime._shutdown_event.set()
                await runtime.start()

                mock_grpc_server.add_insecure_port.assert_called_once()
                mock_grpc_server.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_with_uds(self, tmp_path):
        """Test start with Unix domain socket configuration."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        uds_path = str(tmp_path / "grpc.sock")
        runtime = GrpcPluginRuntime()

        mock_plugin_server = AsyncMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=GRPCServerConfig(uds=uds_path))
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        mock_grpc_server = MagicMock()
        mock_grpc_server.start = AsyncMock()
        mock_grpc_server.add_insecure_port = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.ExternalPluginServer",
            return_value=mock_plugin_server,
        ):
            with patch("grpc.aio.server", return_value=mock_grpc_server):
                runtime._shutdown_event.set()
                await runtime.start()

                # Should bind to unix:// address
                call_args = mock_grpc_server.add_insecure_port.call_args[0][0]
                assert call_args.startswith("unix://")
                assert uds_path in call_args

    @pytest.mark.asyncio
    async def test_start_with_tls(self, tmp_path):
        """Test start with TLS configuration."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        tls_config = GRPCServerTLSConfig(
            certfile=str(cert_file),
            keyfile=str(key_file),
            client_auth="none",
        )

        runtime = GrpcPluginRuntime()

        mock_plugin_server = AsyncMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=GRPCServerConfig(tls=tls_config))
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        mock_grpc_server = MagicMock()
        mock_grpc_server.start = AsyncMock()
        mock_grpc_server.add_secure_port = MagicMock()

        mock_credentials = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.ExternalPluginServer",
            return_value=mock_plugin_server,
        ):
            with patch("grpc.aio.server", return_value=mock_grpc_server):
                with patch(
                    "mcpgateway.plugins.framework.external.grpc.server.runtime.create_server_credentials",
                    return_value=mock_credentials,
                ):
                    runtime._shutdown_event.set()
                    await runtime.start()

                    mock_grpc_server.add_secure_port.assert_called_once()


class TestGrpcPluginRuntimeStop:
    """Tests for GrpcPluginRuntime.stop."""

    @pytest.mark.asyncio
    async def test_stop_graceful_shutdown(self):
        """Test stop performs graceful shutdown."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()

        mock_grpc_server = MagicMock()
        mock_grpc_server.stop = MagicMock(return_value=AsyncMock()())
        mock_grpc_server.wait_for_termination = AsyncMock()

        mock_plugin_server = AsyncMock()

        runtime._server = mock_grpc_server
        runtime._plugin_server = mock_plugin_server

        await runtime.stop()

        mock_grpc_server.stop.assert_called_once()
        runtime._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_stop_no_server(self):
        """Test stop handles case when server is None."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()
        # Server not started

        # Should not raise
        await runtime.stop()


class TestGrpcPluginRuntimeIntegration:
    """Integration tests for GrpcPluginRuntime."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path):
        """Test full start/stop lifecycle."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
plugins: []
plugin_settings:
  parallel_execution_within_band: false
"""
        )

        runtime = GrpcPluginRuntime(config_path=str(config_file))

        mock_plugin_server = AsyncMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=GRPCServerConfig())
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        mock_grpc_server = MagicMock()
        mock_grpc_server.start = AsyncMock()
        mock_grpc_server.stop = MagicMock(return_value=AsyncMock()())
        mock_grpc_server.wait_for_termination = AsyncMock()
        mock_grpc_server.add_insecure_port = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.ExternalPluginServer",
            return_value=mock_plugin_server,
        ):
            with patch("grpc.aio.server", return_value=mock_grpc_server):
                # Start and immediately stop
                runtime._shutdown_event.set()
                await runtime.start()
                await runtime.stop()

                mock_grpc_server.start.assert_called_once()
                mock_grpc_server.stop.assert_called_once()


class TestGrpcPluginRuntimeRequestShutdown:
    """Tests for GrpcPluginRuntime.request_shutdown."""

    def test_request_shutdown_sets_event(self):
        """Test request_shutdown sets the shutdown event."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()
        assert not runtime._shutdown_event.is_set()

        runtime.request_shutdown()
        assert runtime._shutdown_event.is_set()


class TestGrpcPluginRuntimeRunServer:
    """Tests for the run_server function."""

    @pytest.mark.asyncio
    async def test_run_server_creates_runtime_and_starts(self):
        """Test run_server creates a runtime and runs start/stop."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import run_server

        mock_runtime = MagicMock()
        mock_runtime.start = AsyncMock()
        mock_runtime.stop = AsyncMock()
        mock_runtime.request_shutdown = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.GrpcPluginRuntime",
            return_value=mock_runtime,
        ):
            # Make start() immediately complete by making shutdown_event set
            async def instant_start():
                return

            mock_runtime.start = AsyncMock(side_effect=instant_start)
            await run_server(config_path="/test/config.yaml", host="localhost", port=50052)

        mock_runtime.start.assert_called_once()
        mock_runtime.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_server_stop_called_on_exception(self):
        """Test run_server calls stop even when start raises."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import run_server

        mock_runtime = MagicMock()
        mock_runtime.start = AsyncMock(side_effect=RuntimeError("Start failed"))
        mock_runtime.stop = AsyncMock()
        mock_runtime.request_shutdown = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.GrpcPluginRuntime",
            return_value=mock_runtime,
        ):
            with pytest.raises(RuntimeError, match="Start failed"):
                await run_server()

        # stop() should still be called in finally block
        mock_runtime.stop.assert_called_once()


class TestGrpcPluginRuntimeMain:
    """Tests for the main() entry point."""

    def test_main_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt gracefully."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import main

        with patch("sys.argv", ["runtime"]):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.server.runtime.asyncio.run",
                side_effect=KeyboardInterrupt,
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_main_exception_exits_with_error(self):
        """Test main exits with code 1 on unexpected exception."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import main

        with patch("sys.argv", ["runtime"]):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.server.runtime.asyncio.run",
                side_effect=RuntimeError("Server failed"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_main_parses_arguments(self):
        """Test main correctly parses command line arguments."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import main

        with patch(
            "sys.argv",
            ["runtime", "--config", "/custom/config.yaml", "--host", "127.0.0.1", "--port", "50052", "--log-level", "DEBUG"],
        ):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.server.runtime.asyncio.run",
            ) as mock_run:
                mock_run.return_value = None
                main()
                mock_run.assert_called_once()


class TestGrpcPluginRuntimeUdsChmod:
    """Tests for UDS chmod behavior."""

    @pytest.mark.asyncio
    async def test_start_sets_socket_permissions(self, tmp_path):
        """Test start sets permissions on UDS socket file."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        uds_path = str(tmp_path / "grpc.sock")
        runtime = GrpcPluginRuntime()

        mock_plugin_server = AsyncMock()
        mock_plugin_server.get_grpc_server_config = MagicMock(return_value=GRPCServerConfig(uds=uds_path))
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        mock_grpc_server = MagicMock()
        mock_grpc_server.start = AsyncMock()
        mock_grpc_server.add_insecure_port = MagicMock()

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.ExternalPluginServer",
            return_value=mock_plugin_server,
        ):
            with patch("grpc.aio.server", return_value=mock_grpc_server):
                # Create the socket file to test chmod
                with open(uds_path, "w") as f:
                    f.write("")

                runtime._shutdown_event.set()
                await runtime.start()

                # Verify permissions were set to 0o600
                assert os.path.exists(uds_path)
                mode = oct(os.stat(uds_path).st_mode & 0o777)
                assert mode == "0o600"


class TestGrpcPluginRuntimeGetServerConfigNoPluginServer:
    """Tests for _get_server_config when _plugin_server is None."""

    def test_get_server_config_no_plugin_server_falls_to_env(self):
        """Test _get_server_config falls through to env when _plugin_server is None."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()
        runtime._plugin_server = None

        with patch.object(GRPCServerConfig, "from_env", return_value=GRPCServerConfig(host="10.0.0.1", port=50055)):
            config = runtime._get_server_config()
            assert config.host == "10.0.0.1"
            assert config.port == 50055

    def test_get_server_config_no_plugin_server_falls_to_defaults(self):
        """Test _get_server_config falls to defaults when _plugin_server is None and no env."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import GrpcPluginRuntime

        runtime = GrpcPluginRuntime()
        runtime._plugin_server = None

        with patch.object(GRPCServerConfig, "from_env", return_value=None):
            config = runtime._get_server_config()
            assert config.host == "127.0.0.1"
            assert config.port == 50051


class TestGrpcPluginRuntimeSignalHandler:
    """Tests for the signal handler in run_server."""

    @pytest.mark.asyncio
    async def test_signal_handler_calls_request_shutdown(self):
        """Test that the signal handler triggers request_shutdown."""
        from mcpgateway.plugins.framework.external.grpc.server.runtime import run_server

        captured_handlers = {}

        mock_runtime = MagicMock()
        mock_runtime.request_shutdown = MagicMock()

        async def mock_start():
            pass

        mock_runtime.start = AsyncMock(side_effect=mock_start)
        mock_runtime.stop = AsyncMock()

        mock_loop = MagicMock()

        def capture_signal_handler(sig, handler):
            captured_handlers[sig] = handler

        mock_loop.add_signal_handler = MagicMock(side_effect=capture_signal_handler)

        with patch(
            "mcpgateway.plugins.framework.external.grpc.server.runtime.GrpcPluginRuntime",
            return_value=mock_runtime,
        ):
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                await run_server()

        # Signal handlers should have been registered
        assert signal.SIGINT in captured_handlers
        assert signal.SIGTERM in captured_handlers

        # Call the handler - should trigger request_shutdown
        captured_handlers[signal.SIGINT]()
        mock_runtime.request_shutdown.assert_called_once()
