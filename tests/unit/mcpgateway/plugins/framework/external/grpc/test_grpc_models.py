# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/test_grpc_models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC configuration models.
Tests for GRPCClientConfig, GRPCServerConfig, and related TLS configurations.
"""

# Standard
import os
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import (
    GRPCClientConfig,
    GRPCClientTLSConfig,
    GRPCServerConfig,
    GRPCServerTLSConfig,
)


class TestGRPCClientTLSConfig:
    """Tests for GRPCClientTLSConfig model."""

    def test_default_values(self):
        """Test default TLS configuration values."""
        config = GRPCClientTLSConfig()
        assert config.verify is True

    def test_verify_disabled(self):
        """Test TLS configuration with verify disabled."""
        config = GRPCClientTLSConfig(verify=False)
        assert config.verify is False

    def test_with_certificates(self, tmp_path):
        """Test TLS configuration with certificate paths."""
        ca_file = tmp_path / "ca.pem"
        cert_file = tmp_path / "client.pem"
        key_file = tmp_path / "client-key.pem"
        ca_file.touch()
        cert_file.touch()
        key_file.touch()

        config = GRPCClientTLSConfig(
            ca_bundle=str(ca_file),
            certfile=str(cert_file),
            keyfile=str(key_file),
            verify=True,
        )
        assert config.ca_bundle == str(ca_file)
        assert config.certfile == str(cert_file)
        assert config.keyfile == str(key_file)

    def test_from_env_empty(self):
        """Test from_env returns None when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            result = GRPCClientTLSConfig.from_env()
            assert result is None

    def test_from_env_with_values(self, tmp_path):
        """Test from_env with environment variables."""
        ca_file = tmp_path / "ca.pem"
        cert_file = tmp_path / "client.pem"
        key_file = tmp_path / "client-key.pem"
        ca_file.touch()
        cert_file.touch()
        key_file.touch()

        env_vars = {
            "PLUGINS_GRPC_CLIENT_MTLS_CA_BUNDLE": str(ca_file),
            "PLUGINS_GRPC_CLIENT_MTLS_CERTFILE": str(cert_file),
            "PLUGINS_GRPC_CLIENT_MTLS_KEYFILE": str(key_file),
            "PLUGINS_GRPC_CLIENT_MTLS_VERIFY": "false",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = GRPCClientTLSConfig.from_env()
            assert result is not None
            assert result.ca_bundle == str(ca_file)
            assert result.certfile == str(cert_file)
            assert result.keyfile == str(key_file)
            assert result.verify is False


class TestGRPCServerTLSConfig:
    """Tests for GRPCServerTLSConfig model."""

    def test_default_client_auth(self):
        """Test default client_auth is 'require'."""
        config = GRPCServerTLSConfig()
        assert config.client_auth == "require"

    def test_valid_client_auth_values(self):
        """Test valid client_auth values."""
        for value in ["none", "optional", "require"]:
            config = GRPCServerTLSConfig(client_auth=value)
            assert config.client_auth == value.lower()

    def test_invalid_client_auth_value(self):
        """Test invalid client_auth value raises ValueError."""
        with pytest.raises(ValueError, match="client_auth must be one of"):
            GRPCServerTLSConfig(client_auth="invalid")

    def test_client_auth_case_insensitive(self):
        """Test client_auth values are case-insensitive."""
        config = GRPCServerTLSConfig(client_auth="REQUIRE")
        assert config.client_auth == "require"

    def test_from_env_empty(self):
        """Test from_env returns None when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            result = GRPCServerTLSConfig.from_env()
            assert result is None

    def test_from_env_with_values(self, tmp_path):
        """Test from_env with environment variables."""
        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        ca_file = tmp_path / "ca.pem"
        cert_file.touch()
        key_file.touch()
        ca_file.touch()

        env_vars = {
            "PLUGINS_GRPC_SERVER_SSL_CERTFILE": str(cert_file),
            "PLUGINS_GRPC_SERVER_SSL_KEYFILE": str(key_file),
            "PLUGINS_GRPC_SERVER_SSL_CA_CERTS": str(ca_file),
            "PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH": "optional",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = GRPCServerTLSConfig.from_env()
            assert result is not None
            assert result.certfile == str(cert_file)
            assert result.keyfile == str(key_file)
            assert result.ca_bundle == str(ca_file)
            assert result.client_auth == "optional"


class TestGRPCClientConfig:
    """Tests for GRPCClientConfig model."""

    def test_target_only(self):
        """Test configuration with target only."""
        config = GRPCClientConfig(target="localhost:50051")
        assert config.target == "localhost:50051"
        assert config.uds is None
        assert config.get_target() == "localhost:50051"

    def test_uds_only(self, tmp_path):
        """Test configuration with UDS only."""
        uds_path = str(tmp_path / "grpc.sock")
        config = GRPCClientConfig(uds=uds_path)
        assert config.uds == uds_path
        assert config.target is None
        assert config.get_target() == f"unix://{uds_path}"

    def test_target_validation(self):
        """Test target must contain host:port format."""
        with pytest.raises(ValueError, match="must be in host:port format"):
            GRPCClientConfig(target="localhost")

    def test_empty_target_rejected(self):
        """Test empty target string is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            GRPCClientConfig(target="")

    def test_uds_relative_path_rejected(self, tmp_path):
        """Test relative UDS path is rejected because parent doesn't exist."""
        # Relative paths are resolved to absolute, then parent dir is checked
        # The error will be about the parent directory not existing
        with pytest.raises(ValueError, match="parent directory does not exist"):
            GRPCClientConfig(uds="relative/path.sock")

    def test_uds_parent_must_exist(self, tmp_path):
        """Test UDS parent directory must exist."""
        with pytest.raises(ValueError, match="parent directory does not exist"):
            GRPCClientConfig(uds="/nonexistent/path/grpc.sock")

    def test_neither_target_nor_uds_rejected(self):
        """Test configuration must have either target or uds."""
        with pytest.raises(ValueError, match="must have either 'target' or 'uds'"):
            GRPCClientConfig()

    def test_both_target_and_uds_rejected(self, tmp_path):
        """Test configuration cannot have both target and uds."""
        uds_path = str(tmp_path / "grpc.sock")
        with pytest.raises(ValueError, match="cannot have both 'target' and 'uds'"):
            GRPCClientConfig(target="localhost:50051", uds=uds_path)

    def test_uds_with_tls_rejected(self, tmp_path):
        """Test TLS is not allowed with UDS."""
        uds_path = str(tmp_path / "grpc.sock")
        tls_config = GRPCClientTLSConfig(verify=True)
        with pytest.raises(ValueError, match="TLS configuration is not supported for Unix domain sockets"):
            GRPCClientConfig(uds=uds_path, tls=tls_config)

    def test_target_with_tls_allowed(self):
        """Test TLS is allowed with target."""
        tls_config = GRPCClientTLSConfig(verify=True)
        config = GRPCClientConfig(target="localhost:50051", tls=tls_config)
        assert config.tls is not None
        assert config.tls.verify is True

    def test_get_target_tcp(self):
        """Test get_target returns host:port for TCP."""
        config = GRPCClientConfig(target="example.com:50051")
        assert config.get_target() == "example.com:50051"

    def test_get_target_uds(self, tmp_path):
        """Test get_target returns unix:// format for UDS."""
        uds_path = str(tmp_path / "grpc.sock")
        config = GRPCClientConfig(uds=uds_path)
        assert config.get_target() == f"unix://{uds_path}"


class TestGRPCServerConfig:
    """Tests for GRPCServerConfig model."""

    def test_default_values(self):
        """Test default server configuration values."""
        config = GRPCServerConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 50051
        assert config.uds is None
        assert config.tls is None

    def test_custom_host_port(self):
        """Test custom host and port."""
        config = GRPCServerConfig(host="127.0.0.1", port=50052)
        assert config.host == "127.0.0.1"
        assert config.port == 50052
        assert config.get_bind_address() == "127.0.0.1:50052"

    def test_uds_configuration(self, tmp_path):
        """Test UDS configuration."""
        uds_path = str(tmp_path / "grpc.sock")
        config = GRPCServerConfig(uds=uds_path)
        assert config.uds == uds_path
        assert config.get_bind_address() == f"unix://{uds_path}"

    def test_uds_relative_path_rejected(self):
        """Test relative UDS path is rejected because parent doesn't exist."""
        # Relative paths are resolved to absolute, then parent dir is checked
        with pytest.raises(ValueError, match="parent directory does not exist"):
            GRPCServerConfig(uds="relative/path.sock")

    def test_uds_nonexistent_parent_rejected(self):
        """Test UDS with non-existent parent directory is rejected."""
        with pytest.raises(ValueError, match="parent directory does not exist"):
            GRPCServerConfig(uds="/nonexistent/path/grpc.sock")

    def test_uds_with_tls_rejected(self, tmp_path):
        """Test TLS is not allowed with UDS."""
        uds_path = str(tmp_path / "grpc.sock")
        tls_config = GRPCServerTLSConfig()
        with pytest.raises(ValueError, match="TLS configuration is not supported for Unix domain sockets"):
            GRPCServerConfig(uds=uds_path, tls=tls_config)

    def test_tcp_with_tls_allowed(self):
        """Test TLS is allowed with TCP binding."""
        tls_config = GRPCServerTLSConfig(client_auth="none")
        config = GRPCServerConfig(host="0.0.0.0", port=50051, tls=tls_config)
        assert config.tls is not None
        assert config.tls.client_auth == "none"

    def test_get_bind_address_tcp(self):
        """Test get_bind_address returns host:port for TCP."""
        config = GRPCServerConfig(host="192.168.1.1", port=50052)
        assert config.get_bind_address() == "192.168.1.1:50052"

    def test_get_bind_address_uds(self, tmp_path):
        """Test get_bind_address returns unix:// format for UDS."""
        uds_path = str(tmp_path / "grpc.sock")
        config = GRPCServerConfig(uds=uds_path)
        assert config.get_bind_address() == f"unix://{uds_path}"

    def test_from_env_empty(self):
        """Test from_env returns None when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            result = GRPCServerConfig.from_env()
            assert result is None

    def test_from_env_with_host_port(self):
        """Test from_env with host and port."""
        env_vars = {
            "PLUGINS_GRPC_SERVER_HOST": "127.0.0.1",
            "PLUGINS_GRPC_SERVER_PORT": "50052",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = GRPCServerConfig.from_env()
            assert result is not None
            assert result.host == "127.0.0.1"
            assert result.port == 50052

    def test_from_env_with_uds(self, tmp_path):
        """Test from_env with UDS."""
        uds_path = str(tmp_path / "grpc.sock")
        env_vars = {
            "PLUGINS_GRPC_SERVER_UDS": uds_path,
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = GRPCServerConfig.from_env()
            assert result is not None
            assert result.uds == uds_path

    def test_from_env_with_tls(self, tmp_path):
        """Test from_env with TLS enabled."""
        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        cert_file.touch()
        key_file.touch()

        env_vars = {
            "PLUGINS_GRPC_SERVER_HOST": "0.0.0.0",
            "PLUGINS_GRPC_SERVER_PORT": "50051",
            "PLUGINS_GRPC_SERVER_SSL_ENABLED": "true",
            "PLUGINS_GRPC_SERVER_SSL_CERTFILE": str(cert_file),
            "PLUGINS_GRPC_SERVER_SSL_KEYFILE": str(key_file),
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = GRPCServerConfig.from_env()
            assert result is not None
            assert result.tls is not None
            assert result.tls.certfile == str(cert_file)

    def test_from_env_invalid_port(self):
        """Test from_env raises ValueError for invalid port."""
        env_vars = {
            "PLUGINS_GRPC_SERVER_PORT": "invalid",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="Invalid PLUGINS_GRPC_SERVER_PORT"):
                GRPCServerConfig.from_env()


class TestGRPCConfigEdgeCases:
    """Edge case tests for gRPC configuration models."""

    def test_client_config_ipv6_target(self):
        """Test client config with IPv6 target."""
        config = GRPCClientConfig(target="[::1]:50051")
        assert config.target == "[::1]:50051"
        assert config.get_target() == "[::1]:50051"

    def test_client_config_domain_with_port(self):
        """Test client config with domain name."""
        config = GRPCClientConfig(target="grpc.example.com:50051")
        assert config.target == "grpc.example.com:50051"

    def test_server_config_ipv6_host(self):
        """Test server config with IPv6 host."""
        config = GRPCServerConfig(host="::", port=50051)
        assert config.host == "::"
        assert config.get_bind_address() == ":::50051"

    def test_uds_path_with_spaces(self, tmp_path):
        """Test UDS path with spaces in name."""
        socket_dir = tmp_path / "my socket dir"
        socket_dir.mkdir()
        uds_path = str(socket_dir / "grpc.sock")
        config = GRPCClientConfig(uds=uds_path)
        assert " " in config.uds

    def test_uds_path_normalized(self, tmp_path):
        """Test UDS path is normalized (resolved to canonical path)."""
        uds_path = str(tmp_path / "subdir" / ".." / "grpc.sock")
        config = GRPCClientConfig(uds=uds_path)
        # Path should be resolved to canonical form
        assert ".." not in config.uds
