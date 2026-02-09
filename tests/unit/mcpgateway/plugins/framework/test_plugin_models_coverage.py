# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.plugins.framework.models — world-writable UDS, gRPC configs, edge cases."""

# Standard
import os
import stat
from pathlib import Path

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import (
    GRPCClientConfig,
    GRPCClientTLSConfig,
    GRPCServerConfig,
    GRPCServerTLSConfig,
    MCPClientConfig,
    MCPServerConfig,
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
        with pytest.raises(ValueError, match="Invalid PLUGINS_GRPC_SERVER_PORT"):
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
        with pytest.raises(ValueError, match="Invalid PLUGINS_SERVER_PORT"):
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


# ===========================================================================
# MCPServerTLSConfig from_env
# ===========================================================================


class TestMCPServerTLSConfigFromEnv:
    def test_invalid_cert_reqs(self, monkeypatch):
        from mcpgateway.plugins.framework.models import MCPServerTLSConfig

        monkeypatch.setenv("PLUGINS_SERVER_SSL_CERT_REQS", "invalid")
        with pytest.raises(ValueError, match="Invalid PLUGINS_SERVER_SSL_CERT_REQS"):
            MCPServerTLSConfig.from_env()
