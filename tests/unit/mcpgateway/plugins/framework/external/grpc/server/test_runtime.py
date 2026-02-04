# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/server/test_runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC plugin server runtime.
Tests for GrpcPluginRuntime initialization, start, and stop.
"""

# Standard
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

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
