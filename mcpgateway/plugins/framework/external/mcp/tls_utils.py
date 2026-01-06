# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/tls_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

TLS/SSL utility functions for external MCP plugin connections.

This module provides utilities for creating and configuring SSL contexts for
secure communication with external MCP plugin servers. It implements the
certificate validation logic that is tested in test_client_certificate_validation.py.

Examples:
    Create a basic SSL context with default settings:

    >>> from mcpgateway.plugins.framework.models import MCPClientTLSConfig
    >>> import ssl
    >>> config = MCPClientTLSConfig()
    >>> ctx = create_ssl_context(config, "ExamplePlugin")
    >>> ctx.verify_mode == ssl.CERT_REQUIRED
    True

    Create an SSL context with hostname verification disabled:

    >>> config = MCPClientTLSConfig(verify=True, check_hostname=False)
    >>> ctx = create_ssl_context(config, "NoHostnamePlugin")
    >>> ctx.verify_mode == ssl.CERT_REQUIRED
    True
    >>> ctx.check_hostname
    False

    Verify that TLS version is enforced:

    >>> config = MCPClientTLSConfig(verify=True)
    >>> ctx = create_ssl_context(config, "VersionTestPlugin")
    >>> ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    True

    All SSL contexts have TLS 1.2 minimum:

    >>> config1 = MCPClientTLSConfig(verify=True)
    >>> config2 = MCPClientTLSConfig(verify=False)
    >>> ctx1 = create_ssl_context(config1, "Plugin1")
    >>> ctx2 = create_ssl_context(config2, "Plugin2")
    >>> ctx1.minimum_version == ctx2.minimum_version
    True
    >>> ctx1.minimum_version.name
    'TLSv1_2'

    Verify mode differs based on configuration:

    >>> config_secure = MCPClientTLSConfig(verify=True)
    >>> config_insecure = MCPClientTLSConfig(verify=False)
    >>> ctx_secure = create_ssl_context(config_secure, "SecureP")
    >>> ctx_insecure = create_ssl_context(config_insecure, "InsecureP")
    >>> ctx_secure.verify_mode != ctx_insecure.verify_mode
    True
    >>> import ssl
    >>> ctx_secure.verify_mode == ssl.CERT_REQUIRED
    True
    >>> ctx_insecure.verify_mode == ssl.CERT_NONE
    True
"""

# Standard
import logging
import ssl

# First-Party
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import MCPClientTLSConfig, PluginErrorModel

logger = logging.getLogger(__name__)


def create_ssl_context(tls_config: MCPClientTLSConfig, plugin_name: str) -> ssl.SSLContext:
    """Create and configure an SSL context for external plugin connections.

    This function implements the SSL/TLS security configuration for connecting to
    external MCP plugin servers. It supports both standard TLS and mutual TLS (mTLS)
    authentication.

    Security Features Implemented (per Python ssl docs and OpenSSL):

    1. **Invalid Certificate Rejection**: ssl.create_default_context() with CERT_REQUIRED
       automatically validates certificate signatures and chains via OpenSSL.

    2. **Expired Certificate Handling**: OpenSSL automatically checks notBefore and
       notAfter fields per RFC 5280 Section 6. Expired or not-yet-valid certificates
       are rejected during the handshake.

    3. **Certificate Chain Validation**: Full chain validation up to a trusted CA.
       Each certificate in the chain is verified for validity period, signature, etc.

    4. **Hostname Verification**: When check_hostname is enabled, the certificate's
       Subject Alternative Name (SAN) or Common Name (CN) must match the hostname.

    5. **MITM Prevention**: Via mutual authentication when client certificates are
       provided (mTLS mode).

    Args:
        tls_config: TLS configuration containing CA bundle, client certs, and verification settings
        plugin_name: Name of the plugin (for error messages)

    Returns:
        Configured SSLContext ready for use with httpx or other SSL connections

    Raises:
        PluginError: If SSL context configuration fails

    Examples:
        Create SSL context with verification enabled (default secure mode):

        >>> from mcpgateway.plugins.framework.models import MCPClientTLSConfig
        >>> tls_config = MCPClientTLSConfig(verify=True)
        >>> ssl_context = create_ssl_context(tls_config, "TestPlugin")
        >>> ssl_context.verify_mode == 2  # ssl.CERT_REQUIRED
        True
        >>> ssl_context.check_hostname
        True

        Create SSL context with verification disabled (development/testing):

        >>> tls_config = MCPClientTLSConfig(verify=False, check_hostname=False)
        >>> ssl_context = create_ssl_context(tls_config, "DevPlugin")
        >>> ssl_context.verify_mode == 0  # ssl.CERT_NONE
        True
        >>> ssl_context.check_hostname
        False

        Verify TLS 1.2 minimum version enforcement:

        >>> tls_config = MCPClientTLSConfig(verify=True)
        >>> ssl_context = create_ssl_context(tls_config, "SecurePlugin")
        >>> ssl_context.minimum_version.name
        'TLSv1_2'

        Mixed security settings (verify enabled, hostname check disabled):

        >>> tls_config = MCPClientTLSConfig(verify=True, check_hostname=False)
        >>> ssl_context = create_ssl_context(tls_config, "MixedPlugin")
        >>> ssl_context.verify_mode == 2  # ssl.CERT_REQUIRED
        True
        >>> ssl_context.check_hostname
        False

        Default configuration is secure:

        >>> tls_config = MCPClientTLSConfig()
        >>> ssl_context = create_ssl_context(tls_config, "DefaultPlugin")
        >>> ssl_context.verify_mode == 2  # ssl.CERT_REQUIRED
        True
        >>> ssl_context.check_hostname
        True
        >>> ssl_context.minimum_version.name
        'TLSv1_2'

        Test error handling with invalid certificate file:

        >>> import tempfile
        >>> import os
        >>> tmp_dir = tempfile.mkdtemp()
        >>> bad_cert = os.path.join(tmp_dir, "bad.pem")
        >>> with open(bad_cert, 'w') as f:
        ...     _ = f.write("INVALID CERT")
        >>> tls_config = MCPClientTLSConfig(certfile=bad_cert, keyfile=bad_cert, verify=False)
        >>> try:
        ...     ssl_context = create_ssl_context(tls_config, "BadCertPlugin")
        ... except PluginError as e:
        ...     "Failed to configure SSL context" in e.error.message
        True

        Verify logging occurs for different configurations:

        >>> import logging
        >>> tls_config = MCPClientTLSConfig(verify=False)
        >>> ssl_context = create_ssl_context(tls_config, "LogTestPlugin")
        >>> ssl_context is not None
        True
    """
    try:
        # Create SSL context with secure defaults
        # Per Python docs: "The settings are chosen by the ssl module, and usually
        # represent a higher security level than when calling the SSLContext
        # constructor directly."
        # This sets verify_mode to CERT_REQUIRED by default, which enables:
        # - Certificate signature validation
        # - Certificate chain validation up to trusted CA
        # - Automatic expiration checking (notBefore/notAfter per RFC 5280)
        ssl_context = ssl.create_default_context()

        # Enforce TLS 1.2 or higher for security
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        if not tls_config.verify:
            # Disable certificate verification (not recommended for production)
            logger.warning(f"Certificate verification disabled for plugin '{plugin_name}'. This is not recommended for production use.")
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE  # nosec B502  # noqa: DUO122
        else:
            # Enable strict certificate verification (production mode)
            # Load CA certificate bundle for server certificate validation
            if tls_config.ca_bundle:
                # This CA bundle will be used to validate the server's certificate
                # OpenSSL will check:
                # - Certificate is signed by a trusted CA in this bundle
                # - Certificate hasn't expired (notAfter > now)
                # - Certificate is already valid (notBefore < now)
                # - Certificate chain is complete and valid
                ssl_context.load_verify_locations(cafile=tls_config.ca_bundle)

            # Hostname verification
            # When enabled, certificate's SAN or CN must match the server hostname
            if not tls_config.check_hostname:
                logger.warning(f"Hostname verification disabled for plugin '{plugin_name}'. This increases risk of MITM attacks.")
                ssl_context.check_hostname = False

        # Load client certificate for mTLS (mutual authentication)
        # If provided, the client will authenticate itself to the server
        if tls_config.certfile:
            ssl_context.load_cert_chain(
                certfile=tls_config.certfile,
                keyfile=tls_config.keyfile,
                password=tls_config.keyfile_password,
            )
            logger.debug(f"mTLS enabled for plugin '{plugin_name}' with client certificate: {tls_config.certfile}")

        # Log security configuration
        logger.debug(
            f"SSL context created for plugin '{plugin_name}': verify_mode={ssl_context.verify_mode}, check_hostname={ssl_context.check_hostname}, minimum_version={ssl_context.minimum_version}"
        )

        return ssl_context

    except Exception as exc:
        error_msg = f"Failed to configure SSL context for plugin '{plugin_name}': {exc}"
        logger.error(error_msg)
        raise PluginError(error=PluginErrorModel(message=error_msg, plugin_name=plugin_name)) from exc
