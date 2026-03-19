# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/test_tls_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC TLS utilities.
Tests for create_client_credentials, create_server_credentials, and channel creation functions.
"""

# Standard
from unittest.mock import MagicMock, patch

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
from mcpgateway.plugins.framework.models import GRPCClientTLSConfig, GRPCServerTLSConfig


class TestReadFile:
    """Tests for the _read_file helper function."""

    def test_read_file_success(self, tmp_path):
        """Test reading a file successfully."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import _read_file

        test_file = tmp_path / "test.txt"
        test_content = b"test content"
        test_file.write_bytes(test_content)

        result = _read_file(str(test_file))
        assert result == test_content

    def test_read_file_not_found(self):
        """Test reading a non-existent file raises FileNotFoundError."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import _read_file

        with pytest.raises(FileNotFoundError):
            _read_file("/nonexistent/path/file.txt")

    def test_read_file_binary_content(self, tmp_path):
        """Test reading binary content."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import _read_file

        test_file = tmp_path / "binary.bin"
        binary_content = bytes(range(256))
        test_file.write_bytes(binary_content)

        result = _read_file(str(test_file))
        assert result == binary_content


class TestCreateClientCredentials:
    """Tests for create_client_credentials function."""

    def test_minimal_config(self):
        """Test creating credentials with minimal config."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials

        config = GRPCClientTLSConfig(verify=True)

        with patch("grpc.ssl_channel_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            result = create_client_credentials(config, "TestPlugin")

            mock_ssl.assert_called_once()
            assert result is not None

    def test_with_ca_bundle(self, tmp_path):
        """Test creating credentials with CA bundle."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials

        ca_file = tmp_path / "ca.pem"
        ca_file.write_bytes(b"CA CERTIFICATE")

        config = GRPCClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        with patch("grpc.ssl_channel_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_client_credentials(config, "TestPlugin")

            call_kwargs = mock_ssl.call_args[1]
            assert call_kwargs["root_certificates"] == b"CA CERTIFICATE"

    def test_with_client_certificates(self, tmp_path):
        """Test creating credentials with client certificates (mTLS)."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials

        cert_file = tmp_path / "client.pem"
        key_file = tmp_path / "client-key.pem"
        cert_file.write_bytes(b"CLIENT CERT")
        key_file.write_bytes(b"CLIENT KEY")

        config = GRPCClientTLSConfig(
            certfile=str(cert_file),
            keyfile=str(key_file),
            verify=True,
        )

        with patch("grpc.ssl_channel_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_client_credentials(config, "TestPlugin")

            call_kwargs = mock_ssl.call_args[1]
            assert call_kwargs["certificate_chain"] == b"CLIENT CERT"
            assert call_kwargs["private_key"] == b"CLIENT KEY"

    def test_verify_disabled(self):
        """Test creating credentials with verification disabled."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials

        config = GRPCClientTLSConfig(verify=False)

        with patch("grpc.ssl_channel_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_client_credentials(config, "InsecurePlugin")

            call_kwargs = mock_ssl.call_args[1]
            # When verify is disabled, root_certificates should be None
            assert call_kwargs["root_certificates"] is None

    def test_full_mtls_config(self, tmp_path):
        """Test creating credentials with full mTLS configuration."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials

        ca_file = tmp_path / "ca.pem"
        cert_file = tmp_path / "client.pem"
        key_file = tmp_path / "client-key.pem"
        ca_file.write_bytes(b"CA CERT")
        cert_file.write_bytes(b"CLIENT CERT")
        key_file.write_bytes(b"CLIENT KEY")

        config = GRPCClientTLSConfig(
            ca_bundle=str(ca_file),
            certfile=str(cert_file),
            keyfile=str(key_file),
            verify=True,
        )

        with patch("grpc.ssl_channel_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_client_credentials(config, "mTLSPlugin")

            call_kwargs = mock_ssl.call_args[1]
            assert call_kwargs["root_certificates"] == b"CA CERT"
            assert call_kwargs["certificate_chain"] == b"CLIENT CERT"
            assert call_kwargs["private_key"] == b"CLIENT KEY"

    def test_missing_ca_file_raises_at_model_creation(self):
        """Test that missing CA file raises ValueError during model creation.

        The Pydantic model validates that TLS files exist when the config is created.
        """
        with pytest.raises(ValueError, match="TLS file path does not exist"):
            GRPCClientTLSConfig(ca_bundle="/nonexistent/ca.pem", verify=True)

    def test_missing_cert_file_raises_at_model_creation(self, tmp_path):
        """Test that missing cert file raises ValueError during model creation.

        The Pydantic model validates that TLS files exist when the config is created.
        """
        key_file = tmp_path / "client-key.pem"
        key_file.write_bytes(b"KEY")

        with pytest.raises(ValueError, match="TLS file path does not exist"):
            GRPCClientTLSConfig(
                certfile="/nonexistent/client.pem",
                keyfile=str(key_file),
                verify=True,
            )


class TestCreateServerCredentials:
    """Tests for create_server_credentials function."""

    def test_basic_tls_config(self, tmp_path):
        """Test creating server credentials with basic TLS."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials

        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        cert_file.write_bytes(b"SERVER CERT")
        key_file.write_bytes(b"SERVER KEY")

        config = GRPCServerTLSConfig(
            certfile=str(cert_file),
            keyfile=str(key_file),
            client_auth="none",
        )

        with patch("grpc.ssl_server_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_server_credentials(config)

            call_kwargs = mock_ssl.call_args[1]
            assert call_kwargs["private_key_certificate_chain_pairs"] == [(b"SERVER KEY", b"SERVER CERT")]
            assert call_kwargs["require_client_auth"] is False

    def test_mtls_config_require(self, tmp_path):
        """Test creating server credentials with mTLS (client auth required)."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials

        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        ca_file = tmp_path / "ca.pem"
        cert_file.write_bytes(b"SERVER CERT")
        key_file.write_bytes(b"SERVER KEY")
        ca_file.write_bytes(b"CA CERT")

        config = GRPCServerTLSConfig(
            certfile=str(cert_file),
            keyfile=str(key_file),
            ca_bundle=str(ca_file),
            client_auth="require",
        )

        with patch("grpc.ssl_server_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_server_credentials(config)

            call_kwargs = mock_ssl.call_args[1]
            assert call_kwargs["root_certificates"] == b"CA CERT"
            assert call_kwargs["require_client_auth"] is True

    def test_mtls_config_optional(self, tmp_path):
        """Test creating server credentials with optional client auth."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials

        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        cert_file.write_bytes(b"SERVER CERT")
        key_file.write_bytes(b"SERVER KEY")

        config = GRPCServerTLSConfig(
            certfile=str(cert_file),
            keyfile=str(key_file),
            client_auth="optional",
        )

        with patch("grpc.ssl_server_credentials") as mock_ssl:
            mock_ssl.return_value = MagicMock()
            create_server_credentials(config)

            call_kwargs = mock_ssl.call_args[1]
            # "optional" maps to False in gRPC (no native optional support)
            assert call_kwargs["require_client_auth"] is False

    def test_keyfile_without_certfile_raises_at_model_creation(self, tmp_path):
        """Test that keyfile without certfile raises ValueError during model creation.

        The Pydantic model requires certfile when keyfile is specified.
        """
        key_file = tmp_path / "server-key.pem"
        key_file.write_bytes(b"KEY")

        with pytest.raises(ValueError, match="keyfile requires certfile"):
            GRPCServerTLSConfig(keyfile=str(key_file), client_auth="none")

    def test_certfile_without_keyfile_allowed_at_model_creation(self, tmp_path):
        """Test that certfile without keyfile is allowed during model creation.

        The model validation only requires certfile when keyfile is specified,
        not the reverse. This is because certfile-only configs may be valid
        for some use cases (e.g., when keyfile will be provided later).
        """
        cert_file = tmp_path / "server.pem"
        cert_file.write_bytes(b"CERT")

        # This should NOT raise - certfile alone is allowed
        config = GRPCServerTLSConfig(certfile=str(cert_file), client_auth="none")
        assert config.certfile == str(cert_file)
        assert config.keyfile is None

    def test_nonexistent_file_raises_at_model_creation(self):
        """Test that non-existent certificate files raise ValueError during model creation.

        The Pydantic model validates that TLS files exist when the config is created.
        """
        with pytest.raises(ValueError, match="TLS file path does not exist"):
            GRPCServerTLSConfig(
                certfile="/nonexistent/server.pem",
                keyfile="/nonexistent/server-key.pem",
                client_auth="none",
            )


class TestCreateInsecureChannel:
    """Tests for create_insecure_channel function."""

    def test_creates_insecure_channel(self):
        """Test creating an insecure channel."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_insecure_channel

        with patch("grpc.aio.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock()
            result = create_insecure_channel("localhost:50051")

            mock_channel.assert_called_once_with("localhost:50051")
            assert result is not None

    def test_logs_warning(self):
        """Test that creating insecure channel logs a warning."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_insecure_channel

        with patch("grpc.aio.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock()
            with patch("mcpgateway.plugins.framework.external.grpc.tls_utils.logger") as mock_logger:
                create_insecure_channel("localhost:50051")
                mock_logger.warning.assert_called()


class TestCreateSecureChannel:
    """Tests for create_secure_channel function."""

    def test_creates_secure_channel(self, tmp_path):
        """Test creating a secure channel."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_secure_channel

        ca_file = tmp_path / "ca.pem"
        ca_file.write_bytes(b"CA CERT")

        config = GRPCClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        with patch("grpc.aio.secure_channel") as mock_channel:
            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_channel.return_value = MagicMock()
                mock_creds.return_value = MagicMock()

                result = create_secure_channel("localhost:50051", config, "TestPlugin")

                mock_channel.assert_called_once()
                assert result is not None

    def test_passes_credentials(self):
        """Test that credentials are passed to secure_channel."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_secure_channel

        config = GRPCClientTLSConfig(verify=True)

        with patch("grpc.aio.secure_channel") as mock_channel:
            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_credentials = MagicMock()
                mock_creds.return_value = mock_credentials
                mock_channel.return_value = MagicMock()

                create_secure_channel("localhost:50051", config, "TestPlugin")

                # Verify credentials were passed
                call_args = mock_channel.call_args
                assert call_args[0][0] == "localhost:50051"
                assert call_args[0][1] == mock_credentials

    def test_logs_info(self):
        """Test that creating secure channel logs info."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_secure_channel

        config = GRPCClientTLSConfig(verify=True)

        with patch("grpc.aio.secure_channel") as mock_channel:
            with patch("grpc.ssl_channel_credentials"):
                mock_channel.return_value = MagicMock()
                with patch("mcpgateway.plugins.framework.external.grpc.tls_utils.logger") as mock_logger:
                    create_secure_channel("localhost:50051", config, "TestPlugin")
                    mock_logger.info.assert_called()


class TestTLSUtilsIntegration:
    """Integration tests for TLS utilities."""

    def test_client_credentials_chain(self, tmp_path):
        """Test full chain of creating client credentials and channel."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials, create_secure_channel

        ca_file = tmp_path / "ca.pem"
        cert_file = tmp_path / "client.pem"
        key_file = tmp_path / "client-key.pem"
        ca_file.write_bytes(b"CA")
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        config = GRPCClientTLSConfig(
            ca_bundle=str(ca_file),
            certfile=str(cert_file),
            keyfile=str(key_file),
            verify=True,
        )

        with patch("grpc.ssl_channel_credentials") as mock_creds:
            with patch("grpc.aio.secure_channel") as mock_channel:
                mock_creds.return_value = MagicMock()
                mock_channel.return_value = MagicMock()

                # Create credentials
                creds = create_client_credentials(config, "TestPlugin")
                assert creds is not None

                # Create channel with same config
                channel = create_secure_channel("localhost:50051", config, "TestPlugin")
                assert channel is not None

    def test_server_credentials_all_client_auth_modes(self, tmp_path):
        """Test server credentials with all client auth modes."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials

        cert_file = tmp_path / "server.pem"
        key_file = tmp_path / "server-key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        for mode, expected_require in [("none", False), ("optional", False), ("require", True)]:
            config = GRPCServerTLSConfig(
                certfile=str(cert_file),
                keyfile=str(key_file),
                client_auth=mode,
            )

            with patch("grpc.ssl_server_credentials") as mock_ssl:
                mock_ssl.return_value = MagicMock()
                create_server_credentials(config)

                call_kwargs = mock_ssl.call_args[1]
                assert call_kwargs["require_client_auth"] is expected_require, f"Failed for mode={mode}"

    def test_missing_certfile_raises_value_error(self):
        """Test create_server_credentials raises ValueError when certfile is missing."""
        from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials

        config = GRPCServerTLSConfig(client_auth="none")
        assert config.certfile is None

        with pytest.raises(ValueError, match="certfile.*keyfile.*required"):
            create_server_credentials(config)
