# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/server/runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

gRPC server runtime for external plugins.

This module provides the entry point for running a gRPC server that exposes
plugin functionality. It reuses the ExternalPluginServer for plugin loading
and wraps it with gRPC servicers.

Usage:
    python -m mcpgateway.plugins.framework.external.grpc.server.runtime \\
        --config plugins/config.yaml \\
        --host 0.0.0.0 \\
        --port 50051

Environment Variables:
    PLUGINS_CONFIG_PATH: Path to plugins configuration file (default: ./resources/plugins/config.yaml)
    PLUGINS_GRPC_SERVER_HOST: Server host (default: 0.0.0.0)
    PLUGINS_GRPC_SERVER_PORT: Server port (default: 50051)
    PLUGINS_GRPC_SERVER_UDS: Unix domain socket path (alternative to host:port)
    PLUGINS_GRPC_SERVER_SSL_ENABLED: Enable TLS (true/false). Required to enable TLS. Not supported with UDS.
    PLUGINS_GRPC_SERVER_SSL_CERTFILE: Path to server certificate (required when SSL_ENABLED=true)
    PLUGINS_GRPC_SERVER_SSL_KEYFILE: Path to server private key (required when SSL_ENABLED=true)
    PLUGINS_GRPC_SERVER_SSL_CA_CERTS: Path to CA bundle for client verification (for mTLS)
    PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH: Client auth requirement (none/optional/require, default: require)
"""

# Standard
import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Optional

# Third-Party
import grpc

# First-Party
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2_grpc
from mcpgateway.plugins.framework.external.grpc.server.server import GrpcHealthServicer, GrpcPluginServicer
from mcpgateway.plugins.framework.external.grpc.tls_utils import create_server_credentials
from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer
from mcpgateway.plugins.framework.models import GRPCServerConfig

logger = logging.getLogger(__name__)


class GrpcPluginRuntime:
    """Runtime manager for the gRPC plugin server.

    This class handles the lifecycle of the gRPC server, including:
    - Plugin server initialization
    - gRPC server setup and configuration
    - TLS/mTLS configuration
    - Graceful shutdown handling

    Examples:
        >>> runtime = GrpcPluginRuntime(config_path="plugins/config.yaml")
        >>> # In async context:
        >>> # await runtime.start()
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Initialize the gRPC plugin runtime.

        Args:
            config_path: Path to the plugins configuration file.
            host: Server host to bind to (overrides config/env).
            port: Server port to bind to (overrides config/env).
        """
        self._config_path = config_path
        self._host_override = host
        self._port_override = port
        self._server: Optional[grpc.aio.Server] = None
        self._plugin_server: Optional[ExternalPluginServer] = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the gRPC plugin server.

        This method:
        1. Creates and initializes the ExternalPluginServer
        2. Creates the gRPC server with servicers
        3. Configures TLS if enabled
        4. Starts serving requests

        Raises:
            RuntimeError: If server fails to start.
        """
        logger.info("Starting gRPC plugin server...")

        # Create and initialize the plugin server
        self._plugin_server = ExternalPluginServer(config_path=self._config_path)
        await self._plugin_server.initialize()

        # Get server configuration
        server_config = self._get_server_config()

        # Determine bind address (UDS takes precedence, then overrides, then config)
        if server_config.uds:
            address = server_config.get_bind_address()
            is_uds = True
        else:
            host = self._host_override or server_config.host
            port = self._port_override or server_config.port
            address = f"{host}:{port}"
            is_uds = False

        # Create gRPC server
        self._server = grpc.aio.server()

        # Add servicers
        plugin_servicer = GrpcPluginServicer(self._plugin_server)
        health_servicer = GrpcHealthServicer(self._plugin_server)

        plugin_service_pb2_grpc.add_PluginServiceServicer_to_server(plugin_servicer, self._server)
        plugin_service_pb2_grpc.add_HealthServicer_to_server(health_servicer, self._server)

        # Configure address and TLS (TLS not supported for Unix domain sockets)
        if not is_uds and server_config.tls is not None:
            credentials = create_server_credentials(server_config.tls)
            self._server.add_secure_port(address, credentials)
            logger.info("gRPC server configured with TLS on %s", address)
        else:
            self._server.add_insecure_port(address)
            if is_uds:
                logger.info("gRPC server configured on Unix socket %s", server_config.uds)
            else:
                logger.warning("gRPC server configured WITHOUT TLS on %s - not recommended for production", address)

        # Start serving
        await self._server.start()
        logger.info("gRPC plugin server started on %s", address)
        logger.info("Loaded %d plugins", len(await self._plugin_server.get_plugin_configs()))

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop the gRPC plugin server gracefully.

        This method:
        1. Stops accepting new connections
        2. Waits for existing connections to complete (with timeout)
        3. Shuts down the plugin server
        """
        logger.info("Stopping gRPC plugin server...")

        if self._server:
            # Stop accepting new connections
            await self._server.stop(grace=5.0)
            logger.info("gRPC server stopped")

        if self._plugin_server:
            await self._plugin_server.shutdown()
            logger.info("Plugin server shutdown complete")

    def request_shutdown(self) -> None:
        """Request the server to shut down."""
        self._shutdown_event.set()

    def _get_server_config(self) -> GRPCServerConfig:
        """Get the gRPC server configuration.

        Checks the plugin configuration file first, then falls back to
        environment variables, then uses defaults.

        Returns:
            GRPCServerConfig with server settings.
        """
        # Check if config has gRPC server settings
        if self._plugin_server and self._plugin_server._config.grpc_server_settings:
            return self._plugin_server._config.grpc_server_settings

        # Fall back to environment variables
        env_config = GRPCServerConfig.from_env()
        if env_config:
            return env_config

        # Use defaults
        return GRPCServerConfig()


async def run_server(
    config_path: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Run the gRPC plugin server.

    Args:
        config_path: Path to the plugins configuration file.
        host: Server host to bind to.
        port: Server port to bind to.
    """
    runtime = GrpcPluginRuntime(
        config_path=config_path,
        host=host,
        port=port,
    )

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        runtime.request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await runtime.start()
    finally:
        await runtime.stop()


def main() -> None:
    """Main entry point for the gRPC plugin server."""
    parser = argparse.ArgumentParser(
        description="gRPC server for MCP Gateway external plugins",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Start with default settings
    python -m mcpgateway.plugins.framework.external.grpc.server.runtime

    # Start with custom config and port
    python -m mcpgateway.plugins.framework.external.grpc.server.runtime \\
        --config plugins/config.yaml --port 50051

    # Start with TLS enabled (configure via environment variables)
    PLUGINS_GRPC_SERVER_SSL_ENABLED=true \\
    PLUGINS_GRPC_SERVER_SSL_CERTFILE=/path/to/server.pem \\
    PLUGINS_GRPC_SERVER_SSL_KEYFILE=/path/to/server-key.pem \\
    PLUGINS_GRPC_SERVER_SSL_CA_CERTS=/path/to/ca.pem \\
    python -m mcpgateway.plugins.framework.external.grpc.server.runtime
        """,
    )

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=os.environ.get("PLUGINS_CONFIG_PATH"),
        help="Path to plugins configuration file",
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=None,
        help="Server host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="Server port to bind to (default: 50051)",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run the server
    try:
        asyncio.run(
            run_server(
                config_path=args.config,
                host=args.host,
                port=args.port,
            )
        )
    except KeyboardInterrupt:
        logger.info("Server shutdown complete")
        sys.exit(0)
    except Exception as e:
        logger.error("Server failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
