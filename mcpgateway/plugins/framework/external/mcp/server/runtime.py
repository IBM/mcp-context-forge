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
from mcpgateway.plugins.framework import (
    ExternalPluginServer,
    Plugin,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.plugins.framework.constants import (
    GET_PLUGIN_CONFIG,
    GET_PLUGIN_CONFIGS,
    MCP_SERVER_INSTRUCTIONS,
    MCP_SERVER_NAME,
)
from mcpgateway.plugins.framework.models import HookType, MCPServerConfig

logger = logging.getLogger(__name__)

SERVER: ExternalPluginServer = None


# Module-level tool functions (extracted for testability)


async def get_plugin_configs() -> list[dict]:
    """Get the plugin configurations installed on the server.

    Returns:
        JSON string containing list of plugin configuration dictionaries.
    """
    return await SERVER.get_plugin_configs()


async def get_plugin_config(name: str) -> dict:
    """Get the plugin configuration for a specific plugin.

    Args:
        name: The name of the plugin

    Returns:
        JSON string containing plugin configuration dictionary.
    """
    return await SERVER.get_plugin_config(name)


async def prompt_pre_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute prompt prefetch hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The prompt name and arguments to be analyzed
        context: Contextual information required for execution

    Returns:
        Result dictionary from the prompt prefetch hook.
    """

    def prompt_pre_fetch_func(plugin: Plugin, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Wrapper function to invoke prompt prefetch on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The prompt prehook payload.
            context: The plugin context.

        Returns:
            Result from the plugin's prompt_pre_fetch method.
        """
        return plugin.prompt_pre_fetch(payload, context)

    return await SERVER.invoke_hook(PromptPrehookPayload, prompt_pre_fetch_func, plugin_name, payload, context)


async def prompt_post_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute prompt postfetch hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The prompt payload to be analyzed
        context: Contextual information

    Returns:
        Result dictionary from the prompt postfetch hook.
    """

    def prompt_post_fetch_func(plugin: Plugin, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Wrapper function to invoke prompt postfetch on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The prompt posthook payload.
            context: The plugin context.

        Returns:
            Result from the plugin's prompt_post_fetch method.
        """
        return plugin.prompt_post_fetch(payload, context)

    return await SERVER.invoke_hook(PromptPosthookPayload, prompt_post_fetch_func, plugin_name, payload, context)


async def tool_pre_invoke(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute tool pre-invoke hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The tool name and arguments to be analyzed
        context: Contextual information

    Returns:
        Result dictionary from the tool pre-invoke hook.
    """

    def tool_pre_invoke_func(plugin: Plugin, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Wrapper function to invoke tool pre-invoke on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The tool pre-invoke payload.
            context: The plugin context.

        Returns:
            Result from the plugin's tool_pre_invoke method.
        """
        return plugin.tool_pre_invoke(payload, context)

    return await SERVER.invoke_hook(ToolPreInvokePayload, tool_pre_invoke_func, plugin_name, payload, context)


async def tool_post_invoke(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute tool post-invoke hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The tool result to be analyzed
        context: Contextual information

    Returns:
        Result dictionary from the tool post-invoke hook.
    """

    def tool_post_invoke_func(plugin: Plugin, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Wrapper function to invoke tool post-invoke on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The tool post-invoke payload.
            context: The plugin context.

        Returns:
            Result from the plugin's tool_post_invoke method.
        """
        return plugin.tool_post_invoke(payload, context)

    return await SERVER.invoke_hook(ToolPostInvokePayload, tool_post_invoke_func, plugin_name, payload, context)


async def resource_pre_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute resource prefetch hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The resource name and arguments to be analyzed
        context: Contextual information

    Returns:
        Result dictionary from the resource prefetch hook.
    """

    def resource_pre_fetch_func(plugin: Plugin, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Wrapper function to invoke resource prefetch on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The resource prefetch payload.
            context: The plugin context.

        Returns:
            Result from the plugin's resource_pre_fetch method.
        """
        return plugin.resource_pre_fetch(payload, context)

    return await SERVER.invoke_hook(ResourcePreFetchPayload, resource_pre_fetch_func, plugin_name, payload, context)


async def resource_post_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Execute resource postfetch hook for a plugin.

    Args:
        plugin_name: The name of the plugin to execute
        payload: The resource payload to be analyzed
        context: Contextual information

    Returns:
        Result dictionary from the resource postfetch hook.
    """

    def resource_post_fetch_func(plugin: Plugin, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Wrapper function to invoke resource postfetch on a plugin instance.

        Args:
            plugin: The plugin instance to execute.
            payload: The resource postfetch payload.
            context: The plugin context.

        Returns:
            Result from the plugin's resource_post_fetch method.
        """
        return plugin.resource_post_fetch(payload, context)

    return await SERVER.invoke_hook(ResourcePostFetchPayload, resource_post_fetch_func, plugin_name, payload, context)


class SSLCapableFastMCP(FastMCP):
    """FastMCP server with SSL/TLS support using MCPServerConfig."""

    def __init__(self, server_config: MCPServerConfig, *args, **kwargs):
        """Initialize an SSL capable Fast MCP server.

        Args:
            server_config: the MCP server configuration including mTLS information.
            *args: Additional positional arguments passed to FastMCP.
            **kwargs: Additional keyword arguments passed to FastMCP.
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
        """
        ssl_config = {}

        if self.server_config.tls:
            tls = self.server_config.tls
            if tls.keyfile and tls.certfile:
                ssl_config["ssl_keyfile"] = tls.keyfile
                ssl_config["ssl_certfile"] = tls.certfile

                if tls.ca_bundle:
                    ssl_config["ssl_ca_certs"] = tls.ca_bundle

                ssl_config["ssl_cert_reqs"] = tls.ssl_cert_reqs

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
        """
        # Third-Party
        from starlette.applications import Starlette  # pylint: disable=import-outside-toplevel
        from starlette.requests import Request  # pylint: disable=import-outside-toplevel
        from starlette.responses import JSONResponse  # pylint: disable=import-outside-toplevel
        from starlette.routing import Route  # pylint: disable=import-outside-toplevel

        async def health_check(request: Request):  # pylint: disable=unused-argument
            """Health check endpoint for container orchestration.

            Args:
                request: the http request from which the health check occurs.

            Returns:
                JSON response with health status.
            """
            return JSONResponse({"status": "healthy"})

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
        """Run the server using StreamableHTTP transport with optional SSL/TLS."""
        starlette_app = self.streamable_http_app()

        # Add health check endpoint to main app
        # Third-Party
        from starlette.requests import Request  # pylint: disable=import-outside-toplevel
        from starlette.responses import JSONResponse  # pylint: disable=import-outside-toplevel
        from starlette.routing import Route  # pylint: disable=import-outside-toplevel

        async def health_check(request: Request):  # pylint: disable=unused-argument
            """Health check endpoint for container orchestration.

            Args:
                request: the http request from which the health check occurs.

            Returns:
                JSON response with health status.
            """
            return JSONResponse({"status": "healthy"})

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
        config = uvicorn.Config(**config_kwargs)
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


async def run():
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
            mcp.tool(name=HookType.PROMPT_PRE_FETCH.value)(prompt_pre_fetch)
            mcp.tool(name=HookType.PROMPT_POST_FETCH.value)(prompt_post_fetch)
            mcp.tool(name=HookType.TOOL_PRE_INVOKE.value)(tool_pre_invoke)
            mcp.tool(name=HookType.TOOL_POST_INVOKE.value)(tool_post_invoke)
            mcp.tool(name=HookType.RESOURCE_PRE_FETCH.value)(resource_pre_fetch)
            mcp.tool(name=HookType.RESOURCE_POST_FETCH.value)(resource_post_fetch)

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
            mcp.tool(name=HookType.PROMPT_PRE_FETCH.value)(prompt_pre_fetch)
            mcp.tool(name=HookType.PROMPT_POST_FETCH.value)(prompt_post_fetch)
            mcp.tool(name=HookType.TOOL_PRE_INVOKE.value)(tool_pre_invoke)
            mcp.tool(name=HookType.TOOL_POST_INVOKE.value)(tool_post_invoke)
            mcp.tool(name=HookType.RESOURCE_PRE_FETCH.value)(resource_pre_fetch)
            mcp.tool(name=HookType.RESOURCE_POST_FETCH.value)(resource_post_fetch)

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
