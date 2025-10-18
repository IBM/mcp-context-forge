# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pptx_server/src/pptx_server/combined_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Combined MCP and HTTP server for PowerPoint automation with downloads.
"""

# Standard
import asyncio
import threading

# Local
from .server import config
from .server import main as mcp_main


def start_http_server_thread(host: str, port: int):
    """Start HTTP server in a separate thread."""
    try:
        # Third-Party
        import uvicorn

        # Local
        from .http_server import app

        print(f"🌐 Starting HTTP download server on {host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except Exception as e:
        print(f"❌ HTTP server error: {e}")


async def start_combined_server(
    http_host: str | None = None, http_port: int | None = None, enable_http: bool = True
):
    """Start both MCP server (stdio) and HTTP download server."""

    print("🚀 PowerPoint MCP Server with HTTP Downloads")
    print("=" * 50)

    if enable_http:
        # Start HTTP server in background thread
        host = http_host or config.server_host
        port = http_port or config.server_port

        http_thread = threading.Thread(
            target=start_http_server_thread, args=(host, port), daemon=True
        )
        http_thread.start()

        # Give HTTP server time to start
        await asyncio.sleep(1)
        print(f"✅ HTTP download server: http://{host}:{port}")
        print(f"📥 Download endpoint: http://{host}:{port}/download/{{token}}")
        print(f"❤️  Health check: http://{host}:{port}/health")
        print()

    # Start MCP server (stdio)
    print("🔌 Starting MCP server (stdio)...")
    print("📡 Ready for MCP client connections")
    print("-" * 50)

    # Run MCP server
    await mcp_main()


if __name__ == "__main__":
    # Default to enable HTTP downloads
    asyncio.run(start_combined_server(enable_http=True))
