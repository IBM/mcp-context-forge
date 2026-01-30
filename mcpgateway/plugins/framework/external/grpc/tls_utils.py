# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/tls_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

gRPC TLS credential utilities for external plugin transport.

This module provides helper functions for creating gRPC channel and server
credentials with TLS/mTLS support.
"""

# Standard
import logging
from typing import Optional

# Third-Party
import grpc

# First-Party
from mcpgateway.plugins.framework.models import GRPCClientTLSConfig, GRPCServerTLSConfig

logger = logging.getLogger(__name__)


def _read_file(path: str) -> bytes:
    """Read file contents as bytes.

    Args:
        path: Path to the file to read.

    Returns:
        File contents as bytes.

    Raises:
        FileNotFoundError: If file does not exist.
        IOError: If file cannot be read.
    """
    with open(path, "rb") as f:
        return f.read()


def create_client_credentials(tls_config: GRPCClientTLSConfig, plugin_name: str = "unknown") -> grpc.ChannelCredentials:
    """Create gRPC channel credentials for client connections.

    This function creates SSL channel credentials for connecting to a gRPC server.
    It supports:
    - Server certificate verification (with custom CA bundle)
    - Client certificate authentication (mTLS)
    - Disabling verification (not recommended for production)

    Args:
        tls_config: TLS configuration containing certificate paths and options.
        plugin_name: Name of the plugin for logging purposes.

    Returns:
        gRPC ChannelCredentials configured for TLS/mTLS.

    Raises:
        FileNotFoundError: If certificate files are not found.
        ValueError: If TLS configuration is invalid.

    Examples:
        >>> from mcpgateway.plugins.framework.models import GRPCClientTLSConfig
        >>> config = GRPCClientTLSConfig(
        ...     ca_bundle="/path/to/ca.pem",
        ...     certfile="/path/to/client.pem",
        ...     keyfile="/path/to/client-key.pem",
        ...     verify=True
        ... )
        >>> creds = create_client_credentials(config, "my_plugin")
    """
    root_certificates: Optional[bytes] = None
    private_key: Optional[bytes] = None
    certificate_chain: Optional[bytes] = None

    # Load CA bundle for server verification
    if tls_config.ca_bundle:
        logger.debug("Loading CA bundle for plugin %s: %s", plugin_name, tls_config.ca_bundle)
        root_certificates = _read_file(tls_config.ca_bundle)

    # Load client certificate for mTLS
    if tls_config.certfile and tls_config.keyfile:
        logger.debug("Loading client certificate for plugin %s: %s", plugin_name, tls_config.certfile)
        certificate_chain = _read_file(tls_config.certfile)
        private_key = _read_file(tls_config.keyfile)

    # Handle verification setting
    if not tls_config.verify:
        logger.warning("TLS verification disabled for plugin %s - not recommended for production", plugin_name)
        # When verification is disabled, we still create credentials but without root certificates
        # This allows the connection but skips certificate validation
        # Note: grpc-python doesn't have a direct "skip verify" option, so we use empty root_certificates
        # which effectively disables server certificate validation
        return grpc.ssl_channel_credentials(
            root_certificates=None,
            private_key=private_key,
            certificate_chain=certificate_chain,
        )

    return grpc.ssl_channel_credentials(
        root_certificates=root_certificates,
        private_key=private_key,
        certificate_chain=certificate_chain,
    )


def create_server_credentials(tls_config: GRPCServerTLSConfig) -> grpc.ServerCredentials:
    """Create gRPC server credentials for accepting client connections.

    This function creates SSL server credentials for a gRPC server.
    It supports:
    - Server certificate presentation
    - Client certificate authentication (mTLS with configurable requirements)

    Args:
        tls_config: TLS configuration containing certificate paths and client auth settings.

    Returns:
        gRPC ServerCredentials configured for TLS/mTLS.

    Raises:
        FileNotFoundError: If certificate files are not found.
        ValueError: If required certificates are not provided.

    Examples:
        >>> from mcpgateway.plugins.framework.models import GRPCServerTLSConfig
        >>> config = GRPCServerTLSConfig(
        ...     certfile="/path/to/server.pem",
        ...     keyfile="/path/to/server-key.pem",
        ...     ca_bundle="/path/to/ca.pem",
        ...     client_auth="require"
        ... )
        >>> creds = create_server_credentials(config)
    """
    if not tls_config.certfile or not tls_config.keyfile:
        raise ValueError("Server certificate (certfile) and private key (keyfile) are required for gRPC TLS")

    logger.debug("Loading server certificate: %s", tls_config.certfile)
    server_certificate = _read_file(tls_config.certfile)
    private_key = _read_file(tls_config.keyfile)

    # Load CA bundle for client certificate verification
    root_certificates: Optional[bytes] = None
    if tls_config.ca_bundle:
        logger.debug("Loading CA bundle for client verification: %s", tls_config.ca_bundle)
        root_certificates = _read_file(tls_config.ca_bundle)

    # Map client_auth setting to gRPC requirement
    client_auth_map = {
        "none": False,
        "optional": False,  # gRPC doesn't have "optional" - handled in application layer
        "require": True,
    }
    require_client_auth = client_auth_map.get(tls_config.client_auth.lower(), True)

    logger.info(
        "Creating gRPC server credentials with client_auth=%s (require_client_auth=%s)",
        tls_config.client_auth,
        require_client_auth,
    )

    return grpc.ssl_server_credentials(
        private_key_certificate_chain_pairs=[(private_key, server_certificate)],
        root_certificates=root_certificates,
        require_client_auth=require_client_auth,
    )


def create_insecure_channel(target: str) -> grpc.aio.Channel:
    """Create an insecure gRPC channel (no TLS).

    Args:
        target: The target address in host:port format.

    Returns:
        An insecure async gRPC channel.

    Note:
        This should only be used for development/testing.
        Production deployments should always use TLS.
    """
    logger.warning("Creating insecure gRPC channel to %s - not recommended for production", target)
    return grpc.aio.insecure_channel(target)


def create_secure_channel(target: str, tls_config: GRPCClientTLSConfig, plugin_name: str = "unknown") -> grpc.aio.Channel:
    """Create a secure gRPC channel with TLS.

    Args:
        target: The target address in host:port format.
        tls_config: TLS configuration for the channel.
        plugin_name: Name of the plugin for logging purposes.

    Returns:
        A secure async gRPC channel with TLS credentials.
    """
    credentials = create_client_credentials(tls_config, plugin_name)
    logger.info("Creating secure gRPC channel to %s for plugin %s", target, plugin_name)
    return grpc.aio.secure_channel(target, credentials)
