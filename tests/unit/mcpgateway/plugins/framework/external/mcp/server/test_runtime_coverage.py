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
# Module-Level Tool Functions
# ===========================================================================


class TestModuleLevelTools:
    @pytest.mark.asyncio
    async def test_get_plugin_config_requires_server(self, monkeypatch):
        monkeypatch.setattr(runtime, "SERVER", None)
        with pytest.raises(RuntimeError, match="Plugin server not initialized"):
            await runtime.get_plugin_config("anything")


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

    def test_ssl_config_tls_without_ca_or_password(self, tmp_path):
        """Exercise _get_ssl_config branches when optional TLS fields are missing."""
        from mcpgateway.plugins.framework.models import MCPServerTLSConfig

        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        cert_path.write_text("cert")
        key_path.write_text("key")

        config = MCPServerConfig(
            host="127.0.0.1",
            port=8000,
            tls=MCPServerTLSConfig(
                certfile=str(cert_path),
                keyfile=str(key_path),
                ca_bundle=None,
                keyfile_password=None,
                ssl_cert_reqs=2,
            ),
        )

        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config

        ssl_config = runtime.SSLCapableFastMCP._get_ssl_config(server)
        assert ssl_config["ssl_keyfile"] == str(key_path)
        assert ssl_config["ssl_certfile"] == str(cert_path)
        assert "ssl_ca_certs" not in ssl_config
        assert "ssl_keyfile_password" not in ssl_config


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
# _start_health_check_server endpoints
# ===========================================================================


class TestStartHealthCheckServerEndpoints:
    @pytest.mark.asyncio
    async def test_metrics_enabled_executes_health_and_metrics_endpoints(self, monkeypatch):
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")

        monkeypatch.setenv("ENABLE_METRICS", "true")

        called = {"health": False, "metrics": False}

        class DummyServer:
            def __init__(self, config):
                self.config = config

            async def serve(self):
                for route in self.config.app.routes:
                    if getattr(route, "path", None) == "/health":
                        resp = await route.endpoint(None)
                        called["health"] = resp is not None
                    if getattr(route, "path", None) == "/metrics/prometheus":
                        resp = await route.endpoint(None)
                        called["metrics"] = resp is not None

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP._start_health_check_server(server, 9000)
        assert called["health"] is True
        assert called["metrics"] is True

    @pytest.mark.asyncio
    async def test_metrics_disabled_executes_metrics_disabled_endpoint(self, monkeypatch):
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")

        monkeypatch.setenv("ENABLE_METRICS", "false")

        called = {"disabled": False}

        class DummyServer:
            def __init__(self, config):
                self.config = config

            async def serve(self):
                for route in self.config.app.routes:
                    if getattr(route, "path", None) == "/metrics/prometheus":
                        try:
                            resp = await route.endpoint(None)
                        except TypeError:
                            resp = await route.endpoint()
                        called["disabled"] = resp is not None

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP._start_health_check_server(server, 9000)
        assert called["disabled"] is True


# ===========================================================================
# run_streamable_http_async endpoints
# ===========================================================================


class TestRunStreamableHTTPAsyncEndpoints:
    @pytest.mark.asyncio
    async def test_metrics_enabled_executes_routes(self, monkeypatch):
        config = MCPServerConfig(host="127.0.0.1", port=8000)
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")
        server.streamable_http_app = lambda: SimpleNamespace(routes=[])

        monkeypatch.setenv("ENABLE_METRICS", "true")
        monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {})

        called = {"health": False, "metrics": False}

        class DummyServer:
            def __init__(self, cfg):
                self.config = cfg

            async def serve(self):
                for route in self.config.app.routes:
                    if getattr(route, "path", None) == "/health":
                        called["health"] = (await route.endpoint(None)) is not None
                    if getattr(route, "path", None) == "/metrics/prometheus":
                        called["metrics"] = (await route.endpoint(None)) is not None

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP.run_streamable_http_async(server)
        assert called["health"] is True
        assert called["metrics"] is True

    @pytest.mark.asyncio
    async def test_metrics_disabled_executes_route(self, monkeypatch):
        config = MCPServerConfig(host="127.0.0.1", port=8000)
        server = object.__new__(runtime.SSLCapableFastMCP)
        server.server_config = config
        server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")
        server.streamable_http_app = lambda: SimpleNamespace(routes=[])

        monkeypatch.setenv("ENABLE_METRICS", "false")
        monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {})

        called = {"disabled": False}

        class DummyServer:
            def __init__(self, cfg):
                self.config = cfg

            async def serve(self):
                for route in self.config.app.routes:
                    if getattr(route, "path", None) == "/metrics/prometheus":
                        try:
                            resp = await route.endpoint(None)
                        except TypeError:
                            resp = await route.endpoint()
                        called["disabled"] = resp is not None

        monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

        await runtime.SSLCapableFastMCP.run_streamable_http_async(server)
        assert called["disabled"] is True


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
    async def test_auto_detect_stdin_tty_defaults_to_http_and_logs_metrics(self, monkeypatch):
        created = {}

        class DummyServer:
            async def initialize(self):
                return True

            async def shutdown(self):
                created["shutdown"] = True

            def get_server_config(self):
                return MCPServerConfig(host="127.0.0.1", port=8000)

        class DummyMCP:
            def __init__(self, *args, **kwargs):
                created["mcp"] = True

            def tool(self, name):  # noqa: ARG002
                def decorator(fn):
                    return fn

                return decorator

            async def run_streamable_http_async(self):
                created["ran_http"] = True

        monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())
        monkeypatch.setattr(runtime, "SSLCapableFastMCP", DummyMCP)
        monkeypatch.delenv("PLUGINS_TRANSPORT", raising=False)
        monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))

        mock_logger = MagicMock()
        monkeypatch.setattr(runtime, "logger", mock_logger)

        await runtime.run()

        assert created.get("ran_http") is True
        assert created.get("shutdown") is True
        assert any("Prometheus metrics available" in str(call.args[0]) for call in mock_logger.info.call_args_list)
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
