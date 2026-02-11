# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.models — world-writable UDS, gRPC configs, edge cases."""

# Standard
from pathlib import Path, PurePath
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.constants import EXTERNAL_PLUGIN_TYPE
from mcpgateway.plugins.framework.models import (
    GRPCClientConfig,
    GRPCClientTLSConfig,
    GRPCServerConfig,
    GRPCServerTLSConfig,
    MCPClientConfig,
    MCPServerConfig,
    MCPServerTLSConfig,
    PluginConfig,
    UnixSocketClientConfig,
    UnixSocketServerConfig,
)
from mcpgateway.common.models import TransportType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(tmp_path: Path, name: str) -> str:
    file_path = tmp_path / name
    file_path.write_text("data")
    return str(file_path)


# ===========================================================================
# World-writable UDS directory warnings
# ===========================================================================


class TestWorldWritableUDS:
    def test_mcp_server_config_uds_world_writable(self, tmp_path, caplog):
        uds_dir = tmp_path / "ww_dir"
        uds_dir.mkdir()
        uds_dir.chmod(0o777)
        uds_path = str(uds_dir / "server.sock")

        config = MCPServerConfig(host="127.0.0.1", port=8000, uds=uds_path)
        assert config.uds is not None
        assert any("world-writable" in r.message for r in caplog.records)

    def test_mcp_client_config_uds_world_writable(self, tmp_path, caplog):
        uds_dir = tmp_path / "ww_dir"
        uds_dir.mkdir()
        uds_dir.chmod(0o777)
        uds_path = str(uds_dir / "client.sock")

        config = MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost/mcp", uds=uds_path)
        assert config.uds is not None
        assert any("world-writable" in r.message for r in caplog.records)

    def test_grpc_client_config_uds_world_writable(self, tmp_path, caplog):
        uds_dir = tmp_path / "ww_dir"
        uds_dir.mkdir()
        uds_dir.chmod(0o777)
        uds_path = str(uds_dir / "grpc.sock")

        config = GRPCClientConfig(uds=uds_path)
        assert config.uds is not None
        assert any("world-writable" in r.message for r in caplog.records)

    def test_grpc_server_config_uds_world_writable(self, tmp_path, caplog):
        uds_dir = tmp_path / "ww_dir"
        uds_dir.mkdir()
        uds_dir.chmod(0o777)
        uds_path = str(uds_dir / "grpc_srv.sock")

        config = GRPCServerConfig(uds=uds_path)
        assert config.uds is not None
        assert any("world-writable" in r.message for r in caplog.records)


# ===========================================================================
# gRPC TLS from_env
# ===========================================================================


class TestGRPCTLSFromEnv:
    def test_grpc_client_tls_from_env(self, monkeypatch, tmp_path):
        cert = _write_file(tmp_path, "gc-cert.pem")
        key = _write_file(tmp_path, "gc-key.pem")
        ca = _write_file(tmp_path, "gc-ca.pem")

        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_CERTFILE", cert)
        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_KEYFILE", key)
        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_CA_BUNDLE", ca)
        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_KEYFILE_PASSWORD", "secret")
        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_VERIFY", "false")

        config = GRPCClientTLSConfig.from_env()
        assert config is not None
        assert config.verify is False
        assert config.keyfile_password == "secret"

    def test_grpc_client_tls_from_env_empty(self, monkeypatch):
        monkeypatch.delenv("PLUGINS_GRPC_CLIENT_MTLS_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_CLIENT_MTLS_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_CLIENT_MTLS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_CLIENT_MTLS_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_CLIENT_MTLS_VERIFY", raising=False)
        config = GRPCClientTLSConfig.from_env()
        assert config is None

    def test_grpc_server_tls_from_env(self, monkeypatch, tmp_path):
        cert = _write_file(tmp_path, "gs-cert.pem")
        key = _write_file(tmp_path, "gs-key.pem")
        ca = _write_file(tmp_path, "gs-ca.pem")

        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE", key)
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_CERTFILE", cert)
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_CA_CERTS", ca)
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE_PASSWORD", "pw")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH", "optional")

        config = GRPCServerTLSConfig.from_env()
        assert config is not None
        assert config.client_auth == "optional"

    def test_grpc_server_tls_from_env_empty(self, monkeypatch):
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH", raising=False)
        config = GRPCServerTLSConfig.from_env()
        assert config is None


# ===========================================================================
# GRPCServerConfig from_env
# ===========================================================================


class TestGRPCServerConfigFromEnv:
    def test_from_env_basic(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_PORT", "50051")
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_UDS", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", raising=False)

        config = GRPCServerConfig.from_env()
        assert config is not None
        assert config.host == "0.0.0.0"
        assert config.port == 50051

    def test_from_env_invalid_port(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_PORT", "not_a_number")
        with pytest.raises((ValueError, Exception)):
            GRPCServerConfig.from_env()

    def test_from_env_empty(self, monkeypatch):
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_HOST", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_PORT", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_UDS", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", raising=False)
        config = GRPCServerConfig.from_env()
        assert config is None

    def test_from_env_with_ssl(self, monkeypatch, tmp_path):
        cert = _write_file(tmp_path, "cert.pem")
        key = _write_file(tmp_path, "key.pem")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_HOST", "localhost")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", "true")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_CERTFILE", cert)
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE", key)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH", raising=False)

        config = GRPCServerConfig.from_env()
        assert config is not None
        assert config.tls is not None


# ===========================================================================
# GRPCClientConfig methods
# ===========================================================================


class TestGRPCClientConfig:
    def test_get_target_tcp(self):
        config = GRPCClientConfig(target="localhost:50051")
        assert config.get_target() == "localhost:50051"

    def test_get_target_uds(self, tmp_path):
        uds_dir = tmp_path / "sock_dir"
        uds_dir.mkdir()
        uds_path = str(uds_dir / "grpc.sock")
        config = GRPCClientConfig(uds=uds_path)
        assert config.get_target().startswith("unix://")

    def test_validate_target_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            GRPCClientConfig(target="")

    def test_validate_target_no_colon_raises(self):
        with pytest.raises(ValueError, match="host:port"):
            GRPCClientConfig(target="localhost")


# ===========================================================================
# GRPCServerConfig methods
# ===========================================================================


class TestGRPCServerConfigMethods:
    def test_get_bind_address_tcp(self):
        config = GRPCServerConfig(host="0.0.0.0", port=50051)
        assert config.get_bind_address() == "0.0.0.0:50051"

    def test_get_bind_address_uds(self, tmp_path):
        uds_dir = tmp_path / "sock_dir"
        uds_dir.mkdir()
        uds_path = str(uds_dir / "grpc.sock")
        config = GRPCServerConfig(uds=uds_path)
        assert config.get_bind_address().startswith("unix://")

    def test_validate_client_auth_valid(self):
        config = GRPCServerTLSConfig(client_auth="optional")
        assert config.client_auth == "optional"

    def test_validate_client_auth_invalid(self):
        with pytest.raises(ValueError, match="client_auth must be one of"):
            GRPCServerTLSConfig(client_auth="invalid")


# ===========================================================================
# UnixSocketServerConfig
# ===========================================================================


class TestUnixSocketServerConfig:
    def test_from_env_with_path(self, monkeypatch):
        monkeypatch.setenv("UNIX_SOCKET_PATH", "/tmp/custom.sock")
        config = UnixSocketServerConfig.from_env()
        assert config is not None
        assert config.path == "/tmp/custom.sock"

    def test_from_env_without_env(self, monkeypatch):
        monkeypatch.delenv("UNIX_SOCKET_PATH", raising=False)
        config = UnixSocketServerConfig.from_env()
        assert config is None


# ===========================================================================
# MCPServerConfig from_env
# ===========================================================================


class TestMCPServerConfigFromEnv:
    def test_from_env_empty(self, monkeypatch):
        monkeypatch.delenv("PLUGINS_SERVER_HOST", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_PORT", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_UDS", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_ENABLED", raising=False)
        config = MCPServerConfig.from_env()
        assert config is None

    def test_from_env_invalid_port(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        with pytest.raises((ValueError, Exception)):
            MCPServerConfig.from_env()

    def test_from_env_with_uds(self, monkeypatch, tmp_path):
        uds_dir = tmp_path / "sock_dir"
        uds_dir.mkdir()
        uds_path = str(uds_dir / "server.sock")
        monkeypatch.setenv("PLUGINS_SERVER_UDS", uds_path)
        monkeypatch.delenv("PLUGINS_SERVER_HOST", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_PORT", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_ENABLED", raising=False)

        config = MCPServerConfig.from_env()
        assert config is not None
        assert config.uds is not None

    def test_from_env_with_ssl(self, monkeypatch, tmp_path):
        cert = _write_file(tmp_path, "cert.pem")
        key = _write_file(tmp_path, "key.pem")
        monkeypatch.setenv("PLUGINS_SERVER_HOST", "localhost")
        monkeypatch.setenv("PLUGINS_SERVER_SSL_ENABLED", "true")
        monkeypatch.setenv("PLUGINS_SERVER_SSL_CERTFILE", cert)
        monkeypatch.setenv("PLUGINS_SERVER_SSL_KEYFILE", key)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERT_REQS", raising=False)

        config = MCPServerConfig.from_env()
        assert config is not None
        assert config.tls is not None

    def test_from_env_ssl_enabled_without_tls_data(self, monkeypatch):
        """Cover branch where SSL is enabled but no TLS env vars are set (tls stays None)."""
        monkeypatch.setenv("PLUGINS_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("PLUGINS_SERVER_SSL_ENABLED", "true")
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERT_REQS", raising=False)

        config = MCPServerConfig.from_env()
        assert config is not None
        assert config.tls is None


# ===========================================================================
# MCPServerTLSConfig from_env
# ===========================================================================


class TestMCPServerTLSConfigFromEnv:
    def test_from_env_with_ca_bundle_and_password(self, monkeypatch, tmp_path):
        ca = _write_file(tmp_path, "server-ca.pem")
        monkeypatch.setenv("PLUGINS_SERVER_SSL_CA_CERTS", ca)
        monkeypatch.setenv("PLUGINS_SERVER_SSL_KEYFILE_PASSWORD", "pw")
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERT_REQS", raising=False)

        config = MCPServerTLSConfig.from_env()
        assert config is not None
        assert config.ca_bundle is not None
        assert config.keyfile_password == "pw"

    def test_from_env_empty_returns_none(self, monkeypatch):
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_SERVER_SSL_CERT_REQS", raising=False)
        assert MCPServerTLSConfig.from_env() is None

    def test_invalid_cert_reqs(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_SSL_CERT_REQS", "invalid")
        with pytest.raises((ValueError, Exception)):
            MCPServerTLSConfig.from_env()


# ===========================================================================
# Validators / edge branches (UDS, env parsing, PluginConfig)
# ===========================================================================


class TestMCPServerConfigValidators:
    def test_uds_none(self):
        config = MCPServerConfig(uds=None)
        assert config.uds is None

    def test_uds_is_absolute_check_branch(self, tmp_path):
        uds_path = tmp_path / "socket.sock"
        with patch.object(PurePath, "is_absolute", return_value=False):
            with pytest.raises(ValueError, match="must be absolute"):
                MCPServerConfig(uds=str(uds_path))

    def test_uds_parent_stat_oserror_is_ignored(self, tmp_path):
        uds_path = tmp_path / "socket.sock"
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "stat", side_effect=OSError("boom")):
            config = MCPServerConfig(uds=str(uds_path))
        assert config.uds is not None

    def test_bool_parsing_via_settings(self, monkeypatch):
        """Bool fields on PluginsSettings handle false values correctly."""
        from mcpgateway.plugins.framework.settings import PluginsSettings

        monkeypatch.setenv("PLUGINS_SERVER_SSL_ENABLED", "false")
        assert PluginsSettings().server_ssl_enabled is False


class TestMCPClientConfigMoreBranches:
    def test_validate_script_missing_file_raises(self, tmp_path):
        missing = tmp_path / "missing.py"
        with pytest.raises(ValueError, match="does not exist"):
            MCPClientConfig(proto=TransportType.STDIO, script=str(missing))

    def test_validate_script_py_file_allows_non_executable(self, tmp_path):
        script = tmp_path / "script.py"
        script.write_text("print('hi')")
        config = MCPClientConfig(proto=TransportType.STDIO, script=str(script))
        assert config.script == str(script)

    def test_validate_env_empty_key_raises(self):
        with pytest.raises(ValueError, match="env keys must be non-empty"):
            MCPClientConfig(proto=TransportType.STDIO, cmd=["python"], env={"": "x"})

    def test_validate_env_non_string_value_raises(self):
        with pytest.raises(ValueError, match="env values must be strings"):
            MCPClientConfig.validate_env({"KEY": 1})  # type: ignore[arg-type]

    def test_validate_uds_is_absolute_check_branch(self):
        with patch.object(PurePath, "is_absolute", return_value=False):
            with pytest.raises(ValueError, match="must be absolute"):
                MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost/mcp", uds="/tmp/socket.sock")

    def test_validate_uds_parent_stat_oserror_is_ignored(self, tmp_path):
        uds_path = tmp_path / "client.sock"
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "stat", side_effect=OSError("boom")):
            config = MCPClientConfig(proto=TransportType.STREAMABLEHTTP, url="http://localhost/mcp", uds=str(uds_path))
        assert config.uds is not None


class TestGRPCUDSMoreBranches:
    def test_grpc_client_uds_none(self):
        config = GRPCClientConfig(target="localhost:50051", uds=None)
        assert config.uds is None

    def test_grpc_client_uds_empty_string_raises(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            GRPCClientConfig(uds="")

    def test_grpc_client_uds_is_absolute_check_branch(self):
        with patch.object(PurePath, "is_absolute", return_value=False):
            with pytest.raises(ValueError, match="must be absolute"):
                GRPCClientConfig(uds="/tmp/grpc.sock")

    def test_grpc_client_uds_parent_stat_oserror_is_ignored(self):
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "stat", side_effect=OSError("boom")):
            config = GRPCClientConfig(uds="/tmp/grpc.sock")
        assert config.uds is not None

    def test_grpc_server_uds_none(self):
        config = GRPCServerConfig(uds=None)
        assert config.uds is None

    def test_grpc_server_uds_empty_string_raises(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            GRPCServerConfig(uds="")

    def test_grpc_server_uds_is_absolute_check_branch(self):
        with patch.object(PurePath, "is_absolute", return_value=False):
            with pytest.raises(ValueError, match="must be absolute"):
                GRPCServerConfig(uds="/tmp/grpc.sock")

    def test_grpc_server_uds_parent_stat_oserror_is_ignored(self):
        with patch.object(Path, "is_dir", return_value=True), patch.object(Path, "stat", side_effect=OSError("boom")):
            config = GRPCServerConfig(uds="/tmp/grpc.sock")
        assert config.uds is not None

    def test_grpc_server_from_env_ssl_enabled_without_tls_data(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_HOST", "localhost")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", "true")
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CA_CERTS", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_KEYFILE_PASSWORD", raising=False)
        monkeypatch.delenv("PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH", raising=False)

        config = GRPCServerConfig.from_env()
        assert config is not None
        assert config.tls is None


class TestUnixSocketClientConfigBranches:
    def test_unix_socket_client_path_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            UnixSocketClientConfig(path="")

    def test_unix_socket_client_path_not_absolute_raises(self):
        with pytest.raises(ValueError, match="must be absolute"):
            UnixSocketClientConfig(path="relative.sock")


class TestPluginConfigBranches:
    def test_plugin_config_rejects_unknown_mcp_transport_type(self):
        mcp = MCPClientConfig(proto=TransportType.HTTP, url="http://localhost/mcp")
        with pytest.raises(ValueError, match="must set transport type"):
            PluginConfig(name="plug", kind="internal", mcp=mcp)

    def test_external_plugin_cannot_have_multiple_transports(self):
        mcp = MCPClientConfig(proto=TransportType.SSE, url="http://localhost/mcp")
        grpc = GRPCClientConfig(target="localhost:50051")
        with pytest.raises(ValueError, match="only have one transport configured"):
            PluginConfig(name="external", kind=EXTERNAL_PLUGIN_TYPE, mcp=mcp, grpc=grpc)
