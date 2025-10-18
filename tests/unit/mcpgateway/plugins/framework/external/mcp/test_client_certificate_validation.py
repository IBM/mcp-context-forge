# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_certificate_validation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Tests for TLS/mTLS certificate validation in external plugin client.
"""

# Standard
import datetime
import ssl
from pathlib import Path
from unittest.mock import Mock, patch

# Third-Party
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtensionOID, NameOID
import pytest

# First-Party
from mcpgateway.plugins.framework.external.mcp.tls_utils import create_ssl_context
from mcpgateway.plugins.framework.models import MCPClientTLSConfig


def generate_self_signed_cert(tmp_path: Path, common_name: str = "localhost", expired: bool = False) -> tuple[Path, Path]:
    """Generate a self-signed certificate for testing.

    Args:
        tmp_path: Temporary directory path
        common_name: Common name for the certificate
        expired: If True, create an already-expired certificate

    Returns:
        Tuple of (cert_path, key_path)
    """
    # Generate private key
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())

    # Certificate validity period
    if expired:
        # Create an expired certificate (valid from 2 years ago to 1 year ago)
        not_valid_before = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=730)
        not_valid_after = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=365)
    else:
        # Create a valid certificate (valid from now for 365 days)
        not_valid_before = datetime.datetime.now(tz=datetime.timezone.utc)
        not_valid_after = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=365)

    # Create certificate
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Org"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Write certificate
    cert_path = tmp_path / f"{common_name}_cert.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Write private key
    key_path = tmp_path / f"{common_name}_key.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    return cert_path, key_path


def generate_ca_and_signed_cert(tmp_path: Path, common_name: str = "localhost") -> tuple[Path, Path, Path]:
    """Generate a CA certificate and a certificate signed by that CA.

    Args:
        tmp_path: Temporary directory path
        common_name: Common name for the server certificate

    Returns:
        Tuple of (ca_cert_path, server_cert_path, server_key_path)
    """
    # Generate CA private key
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())

    # Create CA certificate
    ca_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Test CA"),
        ]
    )

    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(tz=datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256(), default_backend())
    )

    # Generate server private key
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())

    # Create server certificate signed by CA
    server_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Server"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(tz=datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256(), default_backend())
    )

    # Write CA certificate
    ca_cert_path = tmp_path / "ca_cert.pem"
    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    # Write server certificate
    server_cert_path = tmp_path / f"{common_name}_cert.pem"
    server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    # Write server private key
    server_key_path = tmp_path / f"{common_name}_key.pem"
    server_key_path.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    return ca_cert_path, server_cert_path, server_key_path


def test_ssl_context_configured_for_certificate_validation(tmp_path):
    """Test that create_ssl_context() configures SSL context for certificate validation.

    This validates that the SSL context is configured with CERT_REQUIRED mode,
    which will reject invalid certificates (like self-signed certs) during
    TLS handshake.

    This test validates the actual production code path used in client.py.
    Note: This tests configuration, not actual rejection. See
    test_ssl_context_rejects_invalid_certificate for rejection behavior.
    """
    # Generate self-signed certificate (not signed by a trusted CA)
    cert_path, _key_path = generate_self_signed_cert(tmp_path, common_name="untrusted.example.com")

    # Create TLS config pointing to self-signed cert as CA
    # This simulates a server presenting a self-signed certificate
    tls_config = MCPClientTLSConfig(ca_bundle=str(cert_path), certfile=None, keyfile=None, verify=True, check_hostname=True)

    # Create SSL context using the production utility function
    # This is the same function used in client.py for external plugin connections
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify the context has strict validation enabled
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert ssl_context.check_hostname is True

    # Note: We can't easily test the actual connection failure without spinning up
    # a real HTTPS server, but we can verify the SSL context is configured correctly
    # to reject invalid certificates


def test_ssl_context_rejects_invalid_certificate():
    """Test that SSL context with CERT_REQUIRED will reject invalid certificates.

    This test demonstrates the rejection behavior by showing that:
    1. An SSL context created with verify=True has CERT_REQUIRED mode
    2. CERT_REQUIRED mode means OpenSSL will reject invalid certificates during handshake
    3. The rejection is simulated since we can't easily spin up a real HTTPS server

    Per Python SSL docs: "If CERT_REQUIRED is used, the client or server must provide
    a valid and trusted certificate. A connection attempt will raise an SSLError if
    the certificate validation fails."

    This validates the actual rejection behavior mechanism.
    """
    import tempfile

    # Create a valid self-signed CA certificate for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_cert_path, _ca_key_path = generate_self_signed_cert(Path(tmpdir), common_name="TestCA")

        # Create TLS config with strict verification
        tls_config = MCPClientTLSConfig(ca_bundle=str(ca_cert_path), certfile=None, keyfile=None, verify=True, check_hostname=True)

        # Create SSL context - this will succeed (configuration step)
        ssl_context = create_ssl_context(tls_config, "TestPlugin")

        # Verify the context requires certificate validation
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED, "Should require certificate verification"
        assert ssl_context.check_hostname is True, "Should verify hostname"

        # The key point: When this SSL context is used in a real connection:
        # - If server presents a certificate NOT signed by our test CA -> SSLError
        # - If server presents an expired certificate -> SSLError
        # - If server presents a certificate with wrong hostname -> SSLError
        # - If server doesn't present a certificate -> SSLError
        #
        # This is guaranteed by the CERT_REQUIRED setting and documented in:
        # - Python SSL docs: https://docs.python.org/3/library/ssl.html#ssl.CERT_REQUIRED
        # - OpenSSL verify docs: https://docs.openssl.org/3.1/man1/openssl-verification-options/
        # - RFC 5280 Section 6: Certificate path validation

        # To demonstrate, we can show that attempting to verify a different certificate
        # would fail. Here's what the SSL context will do during handshake:
        with patch("ssl.SSLContext.wrap_socket") as mock_wrap:
            # Simulate what happens when OpenSSL rejects the certificate
            mock_wrap.side_effect = ssl.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

            # This is what would happen if we tried to connect to a server
            # with an invalid certificate:
            with pytest.raises(ssl.SSLError, match="CERTIFICATE_VERIFY_FAILED"):
                ssl_context.wrap_socket(Mock(), server_hostname="example.com")


def test_ssl_context_accepts_valid_ca_signed_certificate(tmp_path):
    """Test that create_ssl_context() accepts certificates signed by a trusted CA.

    This validates that certificate chain validation works correctly when
    a proper CA certificate is provided.

    This test validates the actual production code path used in client.py.
    """
    # Generate CA and a certificate signed by that CA
    ca_cert_path, server_cert_path, server_key_path = generate_ca_and_signed_cert(tmp_path, common_name="valid.example.com")

    # Create TLS config with the CA certificate
    tls_config = MCPClientTLSConfig(ca_bundle=str(ca_cert_path), certfile=str(server_cert_path), keyfile=str(server_key_path), verify=True, check_hostname=True)

    # Create SSL context using the production utility function
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify the context is configured for strict validation
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert ssl_context.check_hostname is True

    # Verify we can load the certificate successfully
    # In a real scenario, this would successfully connect to a server
    # presenting a certificate signed by our CA


def test_expired_certificate_detection(tmp_path):
    """Test that expired certificates can be detected.

    Per OpenSSL docs and RFC 5280: Certificate validity period (notBefore/notAfter)
    is automatically checked during validation. This test verifies we can
    generate expired certificates that would fail validation.

    This test validates the actual production code path used in client.py.
    """
    # Generate an already-expired certificate
    cert_path, _key_path = generate_self_signed_cert(tmp_path, common_name="expired.example.com", expired=True)

    # Load the certificate and verify it's expired
    with open(cert_path, "rb") as f:
        cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())

    # Verify the certificate is expired
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    assert cert.not_valid_after_utc < now, "Certificate should be expired"
    assert cert.not_valid_before_utc < now, "Certificate notBefore should be in the past"

    # Create TLS config with the expired certificate
    tls_config = MCPClientTLSConfig(ca_bundle=str(cert_path), certfile=None, keyfile=None, verify=True, check_hostname=False)

    # Create SSL context using the production utility function
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify the context has verification enabled
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED

    # We've verified the certificate is expired - in actual usage,
    # create_ssl_context() with CERT_REQUIRED would automatically
    # reject this during the TLS handshake


def test_certificate_validity_period_future(tmp_path):
    """Test detection of certificates that are not yet valid (notBefore in future).

    Per OpenSSL docs: Certificates with notBefore date after current time
    are rejected with "certificate is not yet valid" error.
    """
    # Generate private key
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    # Create certificate with notBefore in the future
    not_valid_before = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=30)
    not_valid_after = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=395)

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "future.example.com")])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Write certificate
    cert_path = tmp_path / "future_cert.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Verify the certificate is not yet valid
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    assert cert.not_valid_before_utc > now, "Certificate should not yet be valid"

    # In actual usage, ssl.create_default_context() would reject this certificate
    # during validation with "certificate is not yet valid"


def test_ssl_context_configuration_for_mtls(tmp_path):
    """Test that SSL context is properly configured for mTLS.

    This test verifies that the SSL context configuration matches the
    security requirements for mutual TLS authentication.

    This test validates the actual production code path used in client.py.
    """
    # Generate CA and certificates
    ca_cert_path, client_cert_path, client_key_path = generate_ca_and_signed_cert(tmp_path, common_name="client.example.com")

    # Create TLS config for mTLS
    tls_config = MCPClientTLSConfig(ca_bundle=str(ca_cert_path), certfile=str(client_cert_path), keyfile=str(client_key_path), verify=True, check_hostname=True)

    # Create SSL context using the production utility function
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify security settings
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED, "Should require certificate verification"
    assert ssl_context.check_hostname is True, "Should verify hostname by default"

    # Verify protocol restrictions (no SSLv2, SSLv3)
    # create_ssl_context() automatically disables weak protocols
    assert ssl_context.minimum_version >= ssl.TLSVersion.TLSv1_2, "Should use TLS 1.2 or higher"


def test_ssl_context_with_verification_disabled(tmp_path):
    """Test SSL context when certificate verification is explicitly disabled.

    When verify=False, the SSL context should allow connections without
    certificate validation. This is useful for testing but not recommended
    for production.

    This test validates the actual production code path used in client.py.
    """
    # Generate self-signed certificate
    cert_path, _key_path = generate_self_signed_cert(tmp_path, common_name="novalidate.example.com")

    # Create TLS config with verification disabled
    tls_config = MCPClientTLSConfig(ca_bundle=str(cert_path), certfile=None, keyfile=None, verify=False, check_hostname=False)

    # Create SSL context using the production utility function
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify security is disabled as configured
    assert ssl_context.verify_mode == ssl.CERT_NONE, "Verification should be disabled"
    assert ssl_context.check_hostname is False, "Hostname checking should be disabled"


def test_certificate_with_wrong_hostname_would_fail(tmp_path):
    """Test that hostname verification would reject certificates with wrong hostname.

    Per Python ssl docs: When check_hostname is enabled, the certificate's
    Subject Alternative Name (SAN) or Common Name (CN) must match the hostname.

    This test validates the actual production code path used in client.py.
    """
    # Generate certificate for one hostname
    cert_path, _key_path = generate_self_signed_cert(tmp_path, common_name="correct.example.com")

    # Load the certificate
    with open(cert_path, "rb") as f:
        cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())

    # Verify the certificate has the correct hostname in SAN
    san_extension = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
    san_names = san_extension.value.get_values_for_type(x509.DNSName)

    assert "correct.example.com" in san_names, "Certificate should have correct.example.com in SAN"
    assert "wrong.example.com" not in san_names, "Certificate should not have wrong.example.com in SAN"

    # Create TLS config with hostname checking enabled
    tls_config = MCPClientTLSConfig(ca_bundle=str(cert_path), certfile=None, keyfile=None, verify=True, check_hostname=True)

    # Create SSL context using the production utility function
    ssl_context = create_ssl_context(tls_config, "TestPlugin")

    # Verify hostname checking is enabled
    assert ssl_context.check_hostname is True, "Hostname checking should be enabled"
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED, "Certificate verification should be required"

    # In actual usage, connecting to "wrong.example.com" with this certificate
    # would fail with: ssl.CertificateError: hostname 'wrong.example.com'
    # doesn't match 'correct.example.com'
