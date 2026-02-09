# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.external.mcp.server.runtime."""

# Standard
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import MCPServerConfig
import mcpgateway.plugins.framework.external.mcp.server.runtime as runtime


# ===========================================================================
# SSLCapableFastMCP __init__
# ===========================================================================


class TestSSLCapableFastMCPInit:
    def test_kwargs_override_host_port(self):
        config = MCPServerConfig(host="0.0.0.0", port=9000)
        server = runtime.SSLCapableFastMCP(
            server_config=config,
            name="Test",
            host="custom_host",
            port=1234,
        )
        assert server.settings.host == "custom_host"
        assert server.settings.port == 1234

    def test_uds_sets_transport_security(self, tmp_path):
        uds_path = str(tmp_path / "plugin.sock")
        config = MCPServerConfig(host="127.0.0.1", port=8000, uds=uds_path)
        server = runtime.SSLCapableFastMCP(server_config=config, name="UDSTest")
        assert server.server_config.uds == uds_path

    def test_ssl_config_partial_tls_warns(self, tmp_path, caplog):
        """TLS present but no keyfile/certfile returns empty dict + warning."""
        from mcpgateway.plugins.framework.models import MCPServerTLSConfig

        cert_path = tmp_path / "cert.pem"
        cert_path.write_text("cert")

        # Create a config object then patch tls to have certfile but no keyfile
        config = MCPServerConfig(host="127.0.0.1", port=8000)
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config

        # Manually set tls with no keyfile and no certfile
        tls = MagicMock()
        tls.keyfile = None
        tls.certfile = None
        tls.ca_bundle = None
        server.server_config.tls = tls

        ssl_config = server._get_ssl_config()
        assert ssl_config == {}
        assert any("keyfile/certfile not configured" in r.message for r in caplog.records)


# ===========================================================================
# run_streamable_http_async
# ===========================================================================


class TestRunStreamableHTTPAsync:
    @pytest.mark.asyncio
    async def test_with_uds(self, tmp_path, monkeypatch):
        uds_path = str(tmp_path / "plugin.sock")
        config = MCPServerConfig(host="127.0.0.1", port=8000, uds=uds_path)

        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="info")
        server.streamable_http_app = lambda: SimpleNamespace(routes=[])

        monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {})

        served = MagicMock()

        class DummyServer:
            def __init__(self, config):
                self.config = config

            async def serve(self):
                served()

        configs_seen = []
        original_config = runtime.uvicorn.Config

        def capture_config(**kwargs):
            configs_seen.append(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(runtime.uvicorn, "Config", capture_config)
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP.run_streamable_http_async(server)

        served.assert_called_once()
        assert configs_seen[0].get("uds") == uds_path
        assert "host" not in configs_seen[0]
        assert "port" not in configs_seen[0]

    @pytest.mark.asyncio
    async def test_no_ssl(self, monkeypatch):
        config = MCPServerConfig(host="127.0.0.1", port=8000)

        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="info")
        server.streamable_http_app = lambda: SimpleNamespace(routes=[])

        monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {})

        served = MagicMock()

        class DummyServer:
            def __init__(self, cfg):
                pass

            async def serve(self):
                served()

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP.run_streamable_http_async(server)
        served.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_disabled(self, monkeypatch):
        config = MCPServerConfig(host="127.0.0.1", port=8000)

        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="info")

        routes_added = []
        app = SimpleNamespace(routes=routes_added)
        server.streamable_http_app = lambda: app

        monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {})
        monkeypatch.setenv("ENABLE_METRICS", "false")

        served = MagicMock()

        class DummyServer:
            def __init__(self, cfg):
                pass

            async def serve(self):
                served()

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP.run_streamable_http_async(server)
        served.assert_called_once()
        # Verify routes were added (health + metrics_disabled)
        assert len(routes_added) >= 2


# ===========================================================================
# run() function
# ===========================================================================


class TestRunFunction:
    @pytest.mark.asyncio
    async def test_init_failure(self, monkeypatch):
        class DummyServer:
            async def initialize(self):
                return False

            async def shutdown(self):
                pass

        monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())

        await runtime.run()
        # Should return early without error
        runtime.SERVER = None

    @pytest.mark.asyncio
    async def test_auto_detect_stdin_not_tty(self, monkeypatch):
        created = {}

        class DummyServer:
            async def initialize(self):
                return True

            async def shutdown(self):
                created["shutdown"] = True

        class DummyFastMCP:
            def __init__(self, *args, **kwargs):
                created["mcp"] = True

            def tool(self, name):
                def decorator(fn):
                    return fn
                return decorator

            async def run_stdio_async(self):
                created["ran_stdio"] = True

        monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())
        monkeypatch.setattr(runtime, "FastMCP", DummyFastMCP)
        monkeypatch.delenv("PLUGINS_TRANSPORT", raising=False)
        monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))

        await runtime.run()

        assert created.get("ran_stdio") is True
        assert created.get("shutdown") is True
        runtime.SERVER = None

    @pytest.mark.asyncio
    async def test_exception_propagation(self, monkeypatch):
        class DummyServer:
            async def initialize(self):
                return True

            async def shutdown(self):
                pass

            def get_server_config(self):
                return None

        class DummyMCP:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, name):
                def decorator(fn):
                    return fn
                return decorator

            async def run_streamable_http_async(self):
                raise RuntimeError("server crashed")

        monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())
        monkeypatch.setattr(runtime, "SSLCapableFastMCP", DummyMCP)
        monkeypatch.setenv("PLUGINS_TRANSPORT", "http")

        with pytest.raises(RuntimeError, match="server crashed"):
            await runtime.run()

        runtime.SERVER = None

    @pytest.mark.asyncio
    async def test_health_check_metrics_disabled(self, monkeypatch):
        """Test _start_health_check_server with ENABLE_METRICS=false."""
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")

        monkeypatch.setenv("ENABLE_METRICS", "false")

        served = MagicMock()

        class DummyServer:
            def __init__(self, config):
                self.config = config

            async def serve(self):
                served()

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP._start_health_check_server(server, 9000)
        served.assert_called_once()
