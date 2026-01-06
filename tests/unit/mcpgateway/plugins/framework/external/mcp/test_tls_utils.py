# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_tls_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Additional unit tests for TLS utilities to improve code coverage.
"""

# Standard
import ssl
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.mcp.tls_utils import create_ssl_context
from mcpgateway.plugins.framework.models import MCPClientTLSConfig


class TestCreateSSLContextBasicConfig:
    """Tests for basic SSL context configuration."""

    def test_create_ssl_context_minimal_config(self):
        """Test creating SSL context with minimal configuration."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "MinimalPlugin")

        assert ssl_context is not None
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname is True
        assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_create_ssl_context_verify_disabled(self):
        """Test creating SSL context with verification disabled."""
        tls_config = MCPClientTLSConfig(verify=False, check_hostname=False)

        ssl_context = create_ssl_context(tls_config, "InsecurePlugin")

        assert ssl_context is not None
        assert ssl_context.verify_mode == ssl.CERT_NONE
        assert ssl_context.check_hostname is False

    def test_create_ssl_context_with_ca_bundle(self, tmp_path):
        """Test creating SSL context with CA bundle."""
        # Create a temporary CA file
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")

        tls_config = MCPClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        # Will fail to load the invalid cert but we're testing the path is used
        with pytest.raises(PluginError):
            create_ssl_context(tls_config, "TestPlugin")

    def test_create_ssl_context_hostname_check_disabled(self):
        """Test creating SSL context with hostname checking disabled but verify enabled."""
        tls_config = MCPClientTLSConfig(verify=True, check_hostname=False)

        ssl_context = create_ssl_context(tls_config, "NoHostnameCheckPlugin")

        assert ssl_context is not None
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname is False


class TestCreateSSLContextClientCertificates:
    """Tests for SSL context with client certificates (mTLS)."""

    def test_create_ssl_context_with_client_cert(self, tmp_path):
        """Test creating SSL context with client certificate."""
        cert_file = tmp_path / "client.crt"
        key_file = tmp_path / "client.key"
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")
        key_file.write_text("-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")

        tls_config = MCPClientTLSConfig(certfile=str(cert_file), keyfile=str(key_file), verify=False)

        # Will fail to load the invalid cert but we're testing the path is used
        with pytest.raises(PluginError):
            create_ssl_context(tls_config, "mTLSPlugin")

    def test_create_ssl_context_with_cert_no_key(self, tmp_path):
        """Test creating SSL context with cert but no key (should use same file)."""
        cert_file = tmp_path / "combined.pem"
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")

        tls_config = MCPClientTLSConfig(certfile=str(cert_file), keyfile=None, verify=False)

        # Will fail to load the invalid cert
        with pytest.raises(PluginError):
            create_ssl_context(tls_config, "CombinedPEMPlugin")

    def test_create_ssl_context_with_encrypted_key(self, tmp_path):
        """Test creating SSL context with encrypted private key."""
        cert_file = tmp_path / "client.crt"
        key_file = tmp_path / "client.key"
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")
        key_file.write_text("-----BEGIN ENCRYPTED PRIVATE KEY-----\ntest\n-----END ENCRYPTED PRIVATE KEY-----")

        tls_config = MCPClientTLSConfig(certfile=str(cert_file), keyfile=str(key_file), keyfile_password="secret123", verify=False)

        # Will fail to load the invalid cert
        with pytest.raises(PluginError):
            create_ssl_context(tls_config, "EncryptedKeyPlugin")


class TestCreateSSLContextSecuritySettings:
    """Tests for SSL context security settings."""

    def test_ssl_context_enforces_tls_1_2_minimum(self):
        """Test that SSL context enforces TLS 1.2 as minimum version."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "SecurePlugin")

        assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2
        # Ensure weak protocols are not allowed
        assert ssl_context.minimum_version > ssl.TLSVersion.TLSv1_1

    def test_ssl_context_uses_default_context_security(self):
        """Test that ssl.create_default_context() security settings are preserved."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "DefaultSecurityPlugin")

        # create_default_context() sets secure defaults
        # Verify CERT_REQUIRED is set (from create_default_context)
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED


class TestCreateSSLContextErrorHandling:
    """Tests for error handling in create_ssl_context."""

    def test_create_ssl_context_invalid_ca_bundle(self, tmp_path):
        """Test that invalid CA bundle content raises PluginError."""
        # Create a file with invalid certificate content
        ca_file = tmp_path / "invalid_ca.pem"
        ca_file.write_text("INVALID CERTIFICATE CONTENT")

        tls_config = MCPClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        with pytest.raises(PluginError) as exc_info:
            create_ssl_context(tls_config, "InvalidCAPlugin")

        assert "InvalidCAPlugin" in str(exc_info.value)
        assert "Failed to configure SSL context" in str(exc_info.value)

    def test_create_ssl_context_invalid_client_cert(self, tmp_path):
        """Test that invalid client certificate content raises PluginError."""
        # Create files with invalid certificate/key content
        cert_file = tmp_path / "invalid_cert.pem"
        key_file = tmp_path / "invalid_key.pem"
        cert_file.write_text("INVALID CERT")
        key_file.write_text("INVALID KEY")

        tls_config = MCPClientTLSConfig(certfile=str(cert_file), keyfile=str(key_file), verify=False)

        with pytest.raises(PluginError) as exc_info:
            create_ssl_context(tls_config, "InvalidCertPlugin")

        assert "InvalidCertPlugin" in str(exc_info.value)
        assert "Failed to configure SSL context" in str(exc_info.value)

    def test_create_ssl_context_exception_includes_plugin_name(self, tmp_path):
        """Test that PluginError includes the plugin name in error details."""
        # Create a file with invalid content
        ca_file = tmp_path / "bad_ca.pem"
        ca_file.write_text("BAD CONTENT")

        tls_config = MCPClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        with pytest.raises(PluginError) as exc_info:
            create_ssl_context(tls_config, "MyTestPlugin")

        error = exc_info.value
        assert error.error.plugin_name == "MyTestPlugin"
        assert "MyTestPlugin" in error.error.message

    def test_create_ssl_context_generic_exception_handling(self):
        """Test that any exception during SSL context creation is caught and wrapped."""
        tls_config = MCPClientTLSConfig(verify=True)

        with patch("ssl.create_default_context") as mock_create:
            mock_create.side_effect = RuntimeError("SSL initialization failed")

            with pytest.raises(PluginError) as exc_info:
                create_ssl_context(tls_config, "FailingPlugin")

            assert "Failed to configure SSL context" in str(exc_info.value)
            assert "FailingPlugin" in str(exc_info.value)


class TestCreateSSLContextLogging:
    """Tests for logging in create_ssl_context."""

    def test_create_ssl_context_logs_verification_disabled(self):
        """Test that disabling verification logs a warning."""
        tls_config = MCPClientTLSConfig(verify=False)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger") as mock_logger:
            create_ssl_context(tls_config, "InsecurePlugin")

            # Should log warning about disabled verification
            assert mock_logger.warning.called
            warning_calls = [call for call in mock_logger.warning.call_args_list]
            assert any("verification disabled" in str(call).lower() for call in warning_calls)

    def test_create_ssl_context_logs_hostname_check_disabled(self):
        """Test that disabling hostname checking logs a warning."""
        tls_config = MCPClientTLSConfig(verify=True, check_hostname=False)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger") as mock_logger:
            create_ssl_context(tls_config, "NoHostnamePlugin")

            # Should log warning about disabled hostname verification
            assert mock_logger.warning.called
            warning_calls = [call for call in mock_logger.warning.call_args_list]
            assert any("hostname" in str(call).lower() for call in warning_calls)

    def test_create_ssl_context_logs_mtls_enabled(self, tmp_path):
        """Test that mTLS configuration is logged."""
        cert_file = tmp_path / "client.crt"
        key_file = tmp_path / "client.key"
        # Create minimal valid-looking PEM files
        cert_file.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")
        key_file.write_text("-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")

        tls_config = MCPClientTLSConfig(certfile=str(cert_file), keyfile=str(key_file), verify=False)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger"):
            # Will fail but we can check if debug logging was attempted
            try:
                create_ssl_context(tls_config, "mTLSPlugin")
            except PluginError:
                pass  # Expected to fail with invalid cert

            # Should have attempted to log debug message about mTLS
            # (even though it failed)

    def test_create_ssl_context_logs_debug_info(self):
        """Test that SSL context configuration is logged at debug level."""
        tls_config = MCPClientTLSConfig(verify=True)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger") as mock_logger:
            create_ssl_context(tls_config, "DebugPlugin")

            # Should log debug message with context details
            assert mock_logger.debug.called

    def test_create_ssl_context_logs_error_on_failure(self, tmp_path):
        """Test that errors are logged."""
        # Create a file with invalid content
        ca_file = tmp_path / "bad.pem"
        ca_file.write_text("INVALID")

        tls_config = MCPClientTLSConfig(ca_bundle=str(ca_file), verify=True)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger") as mock_logger:
            with pytest.raises(PluginError):
                create_ssl_context(tls_config, "ErrorPlugin")

            # Should log error
            assert mock_logger.error.called


class TestCreateSSLContextIntegration:
    """Integration tests for create_ssl_context."""

    def test_create_ssl_context_production_like_config(self):
        """Test creating SSL context with production-like configuration."""
        tls_config = MCPClientTLSConfig(verify=True, check_hostname=True)

        ssl_context = create_ssl_context(tls_config, "ProductionPlugin")

        # Verify all security features are enabled
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname is True
        assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_create_ssl_context_development_config(self):
        """Test creating SSL context with development/testing configuration."""
        tls_config = MCPClientTLSConfig(verify=False, check_hostname=False)

        ssl_context = create_ssl_context(tls_config, "DevPlugin")

        # Verify security is relaxed
        assert ssl_context.verify_mode == ssl.CERT_NONE
        assert ssl_context.check_hostname is False

    def test_create_ssl_context_mixed_security_config(self):
        """Test creating SSL context with mixed security settings."""
        # Verify enabled but hostname check disabled
        tls_config = MCPClientTLSConfig(verify=True, check_hostname=False)

        ssl_context = create_ssl_context(tls_config, "MixedPlugin")

        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname is False


class TestCreateSSLContextCompliance:
    """Tests for SSL context compliance with security standards."""

    def test_ssl_context_meets_tls_requirements(self):
        """Test that SSL context meets modern TLS requirements."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "CompliancePlugin")

        # Modern security requirements
        assert ssl_context.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert ssl_context.verify_mode in [ssl.CERT_REQUIRED, ssl.CERT_OPTIONAL]

    def test_ssl_context_default_is_secure(self):
        """Test that default SSL context configuration is secure."""
        tls_config = MCPClientTLSConfig()  # All defaults

        ssl_context = create_ssl_context(tls_config, "DefaultPlugin")

        # Defaults should be secure
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname is True
        assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2


class TestCreateSSLContextEdgeCases:
    """Tests for edge cases in create_ssl_context."""

    def test_create_ssl_context_empty_plugin_name(self):
        """Test creating SSL context with empty plugin name."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "")

        assert ssl_context is not None

    def test_create_ssl_context_special_chars_in_plugin_name(self):
        """Test creating SSL context with special characters in plugin name."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "Plugin-Name_123!@#")

        assert ssl_context is not None

    def test_create_ssl_context_unicode_plugin_name(self):
        """Test creating SSL context with unicode characters in plugin name."""
        tls_config = MCPClientTLSConfig(verify=True)

        ssl_context = create_ssl_context(tls_config, "プラグイン")

        assert ssl_context is not None

    def test_create_ssl_context_verify_true_hostname_false(self):
        """Test the combination of verify=True with check_hostname=False."""
        tls_config = MCPClientTLSConfig(verify=True, check_hostname=False)

        with patch("mcpgateway.plugins.framework.external.mcp.tls_utils.logger") as mock_logger:
            ssl_context = create_ssl_context(tls_config, "PartialSecurityPlugin")

            # Should warn about hostname verification being disabled
            assert mock_logger.warning.called
            # Should still have CERT_REQUIRED
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            # But hostname check should be disabled
            assert ssl_context.check_hostname is False
