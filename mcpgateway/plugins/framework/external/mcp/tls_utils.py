# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/tls_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

TLS/SSL utility functions for external MCP plugin connections.

This module provides utilities for creating and configuring SSL contexts for
secure communication with external MCP plugin servers. It implements the
certificate validation logic that is tested in test_client_certificate_validation.py.
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

    Example:
        >>> tls_config = MCPClientTLSConfig(  # doctest: +SKIP
        ...     ca_bundle="/path/to/ca.crt",
        ...     certfile="/path/to/client.crt",
        ...     keyfile="/path/to/client.key",
        ...     verify=True,
        ...     check_hostname=True
        ... )
        >>> ssl_context = create_ssl_context(tls_config, "MyPlugin")  # doctest: +SKIP
        >>> # Use ssl_context with httpx or other SSL connections
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

        if not tls_config.verify:
            # Disable certificate verification (not recommended for production)
            logger.warning(f"Certificate verification disabled for plugin '{plugin_name}'. " "This is not recommended for production use.")
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE  # noqa: DUO122
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
                logger.warning(f"Hostname verification disabled for plugin '{plugin_name}'. " "This increases risk of MITM attacks.")
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
            f"SSL context created for plugin '{plugin_name}': "
            f"verify_mode={ssl_context.verify_mode}, "
            f"check_hostname={ssl_context.check_hostname}, "
            f"minimum_version={ssl_context.minimum_version}"
        )

        return ssl_context

    except Exception as exc:
        error_msg = f"Failed to configure SSL context for plugin '{plugin_name}': {exc}"
        logger.error(error_msg)
        raise PluginError(error=PluginErrorModel(message=error_msg, plugin_name=plugin_name)) from exc
