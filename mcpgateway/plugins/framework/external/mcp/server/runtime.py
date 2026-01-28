#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/server/runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo, Teryl Taylor

MCP Plugin Runtime using FastMCP with SSL/TLS support.

This runtime does the following:
- Uses FastMCP from the MCP Python SDK
- Supports both mTLS and non-mTLS configurations
- Reads configuration from PLUGINS_SERVER_* environment variables or uses configurations
  the plugin config.yaml
- Implements all plugin hook tools (get_plugin_configs, tool_pre_invoke, etc.)

Examples:
    Create an SSL-capable FastMCP server:

    >>> from mcpgateway.plugins.framework.models import MCPServerConfig
    >>> config = MCPServerConfig(host="localhost", port=8000)
    >>> server = SSLCapableFastMCP(server_config=config, name="TestServer")
    >>> server.settings.host
    'localhost'
    >>> server.settings.port
    8000

    Check SSL configuration returns empty dict when TLS is not configured:

    >>> from mcpgateway.plugins.framework.models import MCPServerConfig
    >>> config = MCPServerConfig(host="127.0.0.1", port=8000, tls=None)
    >>> server = SSLCapableFastMCP(server_config=config, name="NoTLSServer")
    >>> ssl_config = server._get_ssl_config()
    >>> ssl_config
    {}

    Verify server configuration is accessible:

    >>> from mcpgateway.plugins.framework.models import MCPServerConfig
    >>> config = MCPServerConfig(host="localhost", port=9000)
    >>> server = SSLCapableFastMCP(server_config=config, name="ConfigTest")
    >>> server.server_config.host
    'localhost'
    >>> server.server_config.port
    9000

    Settings are properly passed to FastMCP:

    >>> from mcpgateway.plugins.framework.models import MCPServerConfig
    >>> config = MCPServerConfig(host="0.0.0.0", port=8080)
    >>> server = SSLCapableFastMCP(server_config=config, name="SettingsTest")
    >>> server.settings.host
    '0.0.0.0'
    >>> server.settings.port
    8080
"""

# Standard
import asyncio
import logging
import os
import sys
from typing import Any, Dict

# Third-Party
from mcp.server.fastmcp import FastMCP
import uvicorn

# First-Party
from mcpgateway.plugins.framework import ExternalPluginServer, MCPServerConfig
from mcpgateway.plugins.framework.constants import GET_PLUGIN_CONFIG, GET_PLUGIN_CONFIGS, INVOKE_HOOK, MCP_SERVER_INSTRUCTIONS, MCP_SERVER_NAME

logger = logging.getLogger(__name__)

SERVER: ExternalPluginServer | None = None


# Module-level tool functions (extracted for testability)


async def get_plugin_configs() -> list[dict]:
    """Get the plugin configurations installed on the server.

    Returns:
        JSON string containing list of plugin configuration dictionaries.

    Raises:
        RuntimeError: If plugin server not initialized.

    Examples:
        Function raises RuntimeError when server is not initialized:

        >>> import asyncio
        >>> asyncio.run(get_plugin_configs())  # doctest: +SKIP
        Traceback (most recent call last):
        ...
        RuntimeError: Plugin server not initialized
    """
    if not SERVER:
        raise RuntimeError("Plugin server not initialized")
    return await SERVER.get_plugin_configs()


async def get_plugin_config(name: str) -> dict:
    """Get the plugin configuration for a specific plugin.

    Args:
        name: The name of the plugin

    Returns:
        JSON string containing plugin configuration dictionary.

    Raises:
        RuntimeError: If plugin server not initialized.

    Examples:
        Function returns empty dict when result is None:

        >>> result = None
        >>> result if result is not None else {}
        {}
    """
    if not SERVER:
        raise RuntimeError("Plugin server not initialized")
    result = await SERVER.get_plugin_config(name)
    if result is None:
        return {}
    return result


async def invoke_hook(hook_type: str, plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute a hook for a plugin.

    Args:
        hook_type: The name or type of the hook.
        plugin_name: The name of the plugin to execute
        payload: The resource payload to be analyzed
        context: Contextual information

    Returns:
        Result dictionary with payload, context and any error information.

    Raises:
        RuntimeError: If plugin server not initialized.

    Examples:
        Function raises RuntimeError when server is not initialized:

        >>> import asyncio
        >>> asyncio.run(invoke_hook("hook", "plugin", {}, {}))  # doctest: +SKIP
        Traceback (most recent call last):
        ...
        RuntimeError: Plugin server not initialized
    """
    if not SERVER:
        raise RuntimeError("Plugin server not initialized")
    return await SERVER.invoke_hook(hook_type, plugin_name, payload, context)


class SSLCapableFastMCP(FastMCP):
    """FastMCP server with SSL/TLS support using MCPServerConfig.

    Examples:
        Create an SSL-capable FastMCP server:

        >>> from mcpgateway.plugins.framework.models import MCPServerConfig
        >>> config = MCPServerConfig(host="127.0.0.1", port=8000)
        >>> server = SSLCapableFastMCP(server_config=config, name="TestServer")
        >>> server.settings.host
        '127.0.0.1'
        >>> server.settings.port
        8000
    """

    def __init__(self, server_config: MCPServerConfig, *args, **kwargs):
        """Initialize an SSL capable Fast MCP server.

        Args:
            server_config: the MCP server configuration including mTLS information.
            *args: Additional positional arguments passed to FastMCP.
            **kwargs: Additional keyword arguments passed to FastMCP.

        Examples:
            >>> from mcpgateway.plugins.framework.models import MCPServerConfig
            >>> config = MCPServerConfig(host="0.0.0.0", port=9000)
            >>> server = SSLCapableFastMCP(server_config=config, name="PluginServer")
            >>> server.server_config.host
            '0.0.0.0'
            >>> server.server_config.port
            9000
        """
        # Load server config from environment

        self.server_config = server_config
        # Override FastMCP settings with our server config
        if "host" not in kwargs:
            kwargs["host"] = self.server_config.host
        if "port" not in kwargs:
            kwargs["port"] = self.server_config.port

        super().__init__(*args, **kwargs)

    def _get_ssl_config(self) -> dict:
        """Build SSL configuration for uvicorn from MCPServerConfig.

        Returns:
            Dictionary of SSL configuration parameters for uvicorn.

        Examples:
            >>> from mcpgateway.plugins.framework.models import MCPServerConfig
            >>> config = MCPServerConfig(host="127.0.0.1", port=8000, tls=None)
            >>> server = SSLCapableFastMCP(server_config=config, name="TestServer")
            >>> ssl_config = server._get_ssl_config()
            >>> ssl_config
            {}
        """
        ssl_config = {}

        if self.server_config.tls:
            tls = self.server_config.tls
            if tls.keyfile and tls.certfile:
                ssl_config["ssl_keyfile"] = tls.keyfile
                ssl_config["ssl_certfile"] = tls.certfile

                if tls.ca_bundle:
                    ssl_config["ssl_ca_certs"] = tls.ca_bundle

                ssl_config["ssl_cert_reqs"] = str(tls.ssl_cert_reqs)

                if tls.keyfile_password:
                    ssl_config["ssl_keyfile_password"] = tls.keyfile_password

                logger.info("SSL/TLS enabled (mTLS)")
                logger.info(f"  Key: {ssl_config['ssl_keyfile']}")
                logger.info(f"  Cert: {ssl_config['ssl_certfile']}")
                if "ssl_ca_certs" in ssl_config:
                    logger.info(f"  CA: {ssl_config['ssl_ca_certs']}")
                logger.info(f"  Client cert required: {ssl_config['ssl_cert_reqs'] == 2}")
            else:
                logger.warning("TLS config present but keyfile/certfile not configured")
        else:
            logger.info("SSL/TLS not enabled")

        return ssl_config

    async def _start_health_check_server(self, health_port: int) -> None:
        """Start a simple HTTP-only health check server on a separate port.

        This allows health checks to work even when the main server uses HTTPS/mTLS.

        Args:
            health_port: Port number for the health check server.

        Examples:
            Health check endpoint returns expected JSON response:

            >>> import asyncio
            >>> from starlette.responses import JSONResponse
            >>> from starlette.requests import Request
            >>> async def health_check(_request: Request):
            ...     return JSONResponse({"status": "healthy"})
            >>> response = asyncio.run(health_check(None))
            >>> response.status_code
            200
        """
        # Third-Party
        from starlette.applications import Starlette  # pylint: disable=import-outside-toplevel
        from starlette.requests import Request  # pylint: disable=import-outside-toplevel
        from starlette.routing import Route  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.utils.orjson_response import ORJSONResponse  # pylint: disable=import-outside-toplevel

        async def health_check(_request: Request):
            """Health check endpoint for container orchestration.

            Returns:
                JSON response with health status.
            """
            return ORJSONResponse({"status": "healthy"})

        # Create a minimal Starlette app with only the health endpoint
        health_app = Starlette(routes=[Route("/health", health_check, methods=["GET"])])

        logger.info(f"Starting HTTP health check server on {self.settings.host}:{health_port}")
        config = uvicorn.Config(
            app=health_app,
            host=self.settings.host,
            port=health_port,
            log_level="warning",  # Reduce noise from health checks
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def run_streamable_http_async(self) -> None:
        """Run the server using StreamableHTTP transport with optional SSL/TLS.

        Examples:
            Server uses configured host and port:

            >>> from mcpgateway.plugins.framework.models import MCPServerConfig
            >>> config = MCPServerConfig(host="0.0.0.0", port=9000)
            >>> server = SSLCapableFastMCP(server_config=config, name="HTTPServer")
            >>> server.settings.host
            '0.0.0.0'
            >>> server.settings.port
            9000
        """
        starlette_app = self.streamable_http_app()

        # Add health check endpoint to main app
        # Third-Party
        from starlette.requests import Request  # pylint: disable=import-outside-toplevel
        from starlette.routing import Route  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.utils.orjson_response import ORJSONResponse  # pylint: disable=import-outside-toplevel

        async def health_check(_request: Request):
            """Health check endpoint for container orchestration.

            Returns:
                JSON response with health status.
            """
            return ORJSONResponse({"status": "healthy"})

        # Add the health route to the Starlette app
        starlette_app.routes.append(Route("/health", health_check, methods=["GET"]))

        # Build uvicorn config with optional SSL
        ssl_config = self._get_ssl_config()
        config_kwargs = {
            "app": starlette_app,
            "host": self.settings.host,
            "port": self.settings.port,
            "log_level": self.settings.log_level.lower(),
        }
        config_kwargs.update(ssl_config)

        logger.info(f"Starting plugin server on {self.settings.host}:{self.settings.port}")
        config = uvicorn.Config(**config_kwargs)  # type: ignore[arg-type]
        server = uvicorn.Server(config)

        # If SSL is enabled, start a separate HTTP health check server
        if ssl_config:
            health_port = self.settings.port + 1000  # Use port+1000 for health checks
            logger.info(f"SSL enabled - starting separate HTTP health check on port {health_port}")
            # Run both servers concurrently
            await asyncio.gather(server.serve(), self._start_health_check_server(health_port))
        else:
            # Just run the main server (health check is already on it)
            await server.serve()


async def run() -> None:
    """Run the external plugin server with FastMCP.

    Supports both stdio and HTTP transports. Auto-detects transport based on stdin
    (if stdin is not a TTY, uses stdio mode), or you can explicitly set PLUGINS_TRANSPORT.

    Reads configuration from PLUGINS_SERVER_* environment variables:
        - PLUGINS_TRANSPORT: Transport type - 'stdio' or 'http' (default: auto-detect)
        - PLUGINS_SERVER_HOST: Server host (default: 0.0.0.0) - HTTP mode only
        - PLUGINS_SERVER_PORT: Server port (default: 8000) - HTTP mode only
        - PLUGINS_SERVER_SSL_ENABLED: Enable SSL/TLS (true/false) - HTTP mode only
        - PLUGINS_SERVER_SSL_KEYFILE: Path to server private key - HTTP mode only
        - PLUGINS_SERVER_SSL_CERTFILE: Path to server certificate - HTTP mode only
        - PLUGINS_SERVER_SSL_CA_CERTS: Path to CA bundle for client verification - HTTP mode only
        - PLUGINS_SERVER_SSL_CERT_REQS: Client cert requirement (0=NONE, 1=OPTIONAL, 2=REQUIRED) - HTTP mode only

    Raises:
        Exception: If plugin server initialization or execution fails.

    Examples:
        SERVER module variable starts as None:

        >>> SERVER is None
        True

        FastMCP server names are defined as constants:

        >>> from mcpgateway.plugins.framework.constants import MCP_SERVER_NAME
        >>> isinstance(MCP_SERVER_NAME, str)
        True
        >>> len(MCP_SERVER_NAME) > 0
        True
    """
    global SERVER  # pylint: disable=global-statement

    # Initialize plugin server
    SERVER = ExternalPluginServer()

    if not await SERVER.initialize():
        logger.error("Failed to initialize plugin server")
        return

    # Determine transport type from environment variable or auto-detect
    # Auto-detect: if stdin is not a TTY (i.e., it's being piped), use stdio mode
    transport = os.environ.get("PLUGINS_TRANSPORT", None)
    if transport is None:
        # Auto-detect based on stdin
        if not sys.stdin.isatty():
            transport = "stdio"
            logger.info("Auto-detected stdio transport (stdin is not a TTY)")
        else:
            transport = "http"
    else:
        transport = transport.lower()

    try:
        if transport == "stdio":
            # Create basic FastMCP server for stdio (no SSL support needed for stdio)
            mcp = FastMCP(
                name=MCP_SERVER_NAME,
                instructions=MCP_SERVER_INSTRUCTIONS,
            )

            # Register module-level tool functions with FastMCP
            mcp.tool(name=GET_PLUGIN_CONFIGS)(get_plugin_configs)
            mcp.tool(name=GET_PLUGIN_CONFIG)(get_plugin_config)
            mcp.tool(name=INVOKE_HOOK)(invoke_hook)

            # Run with stdio transport
            logger.info("Starting MCP plugin server with FastMCP (stdio transport)")
            await mcp.run_stdio_async()

        else:  # http or streamablehttp
            # Create FastMCP server with SSL support
            mcp = SSLCapableFastMCP(
                server_config=SERVER.get_server_config(),
                name=MCP_SERVER_NAME,
                instructions=MCP_SERVER_INSTRUCTIONS,
            )

            # Register module-level tool functions with FastMCP
            mcp.tool(name=GET_PLUGIN_CONFIGS)(get_plugin_configs)
            mcp.tool(name=GET_PLUGIN_CONFIG)(get_plugin_config)
            mcp.tool(name=INVOKE_HOOK)(invoke_hook)

            # Run with streamable-http transport
            logger.info("Starting MCP plugin server with FastMCP (HTTP transport)")
            await mcp.run_streamable_http_async()

    except Exception:
        logger.exception("Caught error while executing plugin server")
        raise
    finally:
        await SERVER.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
