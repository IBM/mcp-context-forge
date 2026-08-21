#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/server.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Container Scanner external plugin MCP server entry point.

Runs the ContainerScannerPlugin as a standalone MCP server that the gateway
reaches over HTTP (StreamableHTTP) or STDIO.  The gateway config entry uses
``kind: "external"`` and points to this server's MCP URL — no core gateway
files are modified.

In HTTP mode the server also exposes a self-contained dashboard:

    GET /        — HTML dashboard (served from templates/ui.html)
    GET /scans   — JSON list of recent scan results
    GET /health  — liveness probe

Usage::

    # HTTP mode (default, used by gateway in config.yaml)
    PLUGINS_SERVER_PORT=8100 python -m plugins.container_scanner.server

    # STDIO mode (for local testing with MCP inspector)
    PLUGINS_TRANSPORT=stdio python -m plugins.container_scanner.server
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import logging
import os
import sys
from typing import Any, Dict

# Third-Party
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

# First-Party
from mcpgateway.plugins.framework import ExternalPluginServer
from mcpgateway.plugins.framework.constants import (
    GET_PLUGIN_CONFIG,
    GET_PLUGIN_CONFIGS,
    INVOKE_HOOK,
    MCP_SERVER_INSTRUCTIONS,
    MCP_SERVER_NAME,
)
from mcpgateway.plugins.framework.external.mcp.server.runtime import SSLCapableFastMCP

logger = logging.getLogger(__name__)

# Module-level server instance — set once during run() and shared by tool handlers.
_server: ExternalPluginServer | None = None

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "plugin_config.yaml")
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


# ---------------------------------------------------------------------------
# MCP tool handlers (thin wrappers — all logic lives in ExternalPluginServer)
# ---------------------------------------------------------------------------


async def get_plugin_configs() -> list[dict]:
    """Return all plugin configurations loaded on this server."""
    if not _server:
        raise RuntimeError("Plugin server not initialized")
    return await _server.get_plugin_configs()


async def get_plugin_config(name: str) -> dict:
    """Return the configuration for a specific plugin by name."""
    if not _server:
        raise RuntimeError("Plugin server not initialized")
    result = await _server.get_plugin_config(name)
    return result if result is not None else {}


async def invoke_hook(
    hook_type: str,
    plugin_name: str,
    payload: Dict[str, Any],
    context: Dict[str, Any],
) -> dict:
    """Dispatch a hook invocation to the ContainerScannerPlugin."""
    if not _server:
        raise RuntimeError("Plugin server not initialized")
    return await _server.invoke_hook(hook_type, plugin_name, payload, context)


# ---------------------------------------------------------------------------
# UI / REST route handlers
# ---------------------------------------------------------------------------


async def _health(_request: Request) -> JSONResponse:
    """Liveness probe."""
    return JSONResponse({"status": "healthy"})


async def _list_scans(_request: Request) -> JSONResponse:
    """Return recent scan results as JSON."""
    from plugins.container_scanner.storage.repository import container_scan_repo  # pylint: disable=import-outside-toplevel

    results = container_scan_repo.list_recent()
    return JSONResponse([r.model_dump(mode="json") for r in results])


async def _serve_ui(_request: Request) -> HTMLResponse:
    """Serve the self-contained dashboard HTML."""
    template_path = os.path.join(_TEMPLATES_DIR, "ui.html")
    with open(template_path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


async def _trigger_scan(request: Request) -> JSONResponse:
    """Manually trigger a scan for a given image reference.

    Expects a JSON body::

        {"image_ref": "ghcr.io/org/app:v1", "image_digest": null}

    Returns the full ScanResult as JSON.
    """
    if not _server:
        return JSONResponse({"error": "Plugin server not initialized"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    image_ref: str = body.get("image_ref", "").strip()
    if not image_ref:
        return JSONResponse({"error": "image_ref is required"}, status_code=400)

    image_digest: str | None = body.get("image_digest") or None

    plugin = _server._plugin_manager.get_plugin("ContainerScannerPlugin")  # pylint: disable=protected-access
    if plugin is None:
        return JSONResponse({"error": "ContainerScannerPlugin not loaded"}, status_code=503)

    try:
        result = await plugin.scan(image_ref, image_digest)
        return JSONResponse(result.model_dump(mode="json"))
    except Exception as exc:
        logger.exception("Manual scan failed for %s", image_ref)
        return JSONResponse({"error": str(exc)}, status_code=500)


def _build_http_app(mcp: SSLCapableFastMCP) -> Any:
    """Attach UI and REST routes to the MCP server's Starlette app.

    ``streamable_http_app()`` returns the bare Starlette app that handles
    the /mcp endpoint.  We append our own routes before handing it to
    uvicorn so everything runs on a single port.
    """
    app = mcp.streamable_http_app()  # type: ignore[attr-defined]
    app.routes.extend(
        [
            Route("/", _serve_ui, methods=["GET"]),
            Route("/health", _health, methods=["GET"]),
            Route("/scans", _list_scans, methods=["GET"]),
            Route("/scan", _trigger_scan, methods=["POST"])
        ]
    )
    return app


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------


async def run() -> None:
    """Initialise the plugin server and start the MCP transport.

    Transport is selected via the PLUGINS_TRANSPORT environment variable:
        - ``http``  — StreamableHTTP on PLUGINS_SERVER_HOST:PLUGINS_SERVER_PORT
        - ``stdio`` — STDIO (useful for MCP inspector / local debugging)
        - (unset)   — auto-detect: stdio when stdin is not a TTY, else http
    """
    global _server  # pylint: disable=global-statement

    _server = ExternalPluginServer(config_path=_CONFIG_PATH)

    if not await _server.initialize():
        logger.error("Failed to initialize container scanner plugin server")
        return

    transport = os.environ.get("PLUGINS_TRANSPORT", None)
    if transport is None:
        if not sys.stdin.isatty():
            transport = "stdio"
            logger.info("Auto-detected stdio transport (stdin is not a TTY)")
        else:
            transport = "http"
    else:
        transport = transport.lower()

    try:
        if transport == "stdio":
            mcp = FastMCP(name=MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)
            mcp.tool(name=GET_PLUGIN_CONFIGS)(get_plugin_configs)  # type: ignore[attr-defined]
            mcp.tool(name=GET_PLUGIN_CONFIG)(get_plugin_config)  # type: ignore[attr-defined]
            mcp.tool(name=INVOKE_HOOK)(invoke_hook)  # type: ignore[attr-defined]
            logger.info("Starting container scanner plugin server (stdio)")
            await mcp.run_stdio_async()  # type: ignore[attr-defined]
        else:
            mcp = SSLCapableFastMCP(
                server_config=_server.get_server_config(),
                name=MCP_SERVER_NAME,
                instructions=MCP_SERVER_INSTRUCTIONS,
            )
            mcp.tool(name=GET_PLUGIN_CONFIGS)(get_plugin_configs)  # type: ignore[attr-defined]
            mcp.tool(name=GET_PLUGIN_CONFIG)(get_plugin_config)  # type: ignore[attr-defined]
            mcp.tool(name=INVOKE_HOOK)(invoke_hook)  # type: ignore[attr-defined]

            app = _build_http_app(mcp)
            ssl_config = mcp._get_ssl_config()  # type: ignore[attr-defined]  # pylint: disable=protected-access
            uvicorn_config = uvicorn.Config(
                app=app,
                host=mcp.settings.host,  # type: ignore[attr-defined]
                port=mcp.settings.port,  # type: ignore[attr-defined]
                log_level=mcp.settings.log_level.lower(),  # type: ignore[attr-defined]
                **ssl_config,
            )
            logger.info(
                "Starting container scanner plugin server (HTTP) on %s:%s",
                mcp.settings.host,  # type: ignore[attr-defined]
                mcp.settings.port,  # type: ignore[attr-defined]
            )
            await uvicorn.Server(uvicorn_config).serve()
    except Exception:
        logger.exception("Container scanner plugin server error")
        raise
    finally:
        await _server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
