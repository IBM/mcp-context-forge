#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hybrid server that runs both MCP (stdio) and REST API simultaneously.

This module creates a server that can handle both:
1. MCP protocol over stdio (for Claude Desktop, MCP clients)
2. REST API over HTTP (for direct HTTP integration)

This allows maximum flexibility for different integration needs.
"""

# Standard
import argparse
import asyncio
import logging
import sys

# Load .env file if it exists
try:
    # Third-Party
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    # Third-Party
    import uvicorn
except ImportError:
    print("❌ FastAPI dependencies not installed!")
    print("💡 Install with: pip install fastapi uvicorn")
    sys.exit(1)

# Third-Party
from mcp.server.models import InitializationOptions

# MCP imports
from mcp.server.stdio import stdio_server

# Local
from .rest_server import app as rest_app

# Local imports
from .server import server as mcp_server

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class HybridServer:
    """Server that runs both MCP and REST API simultaneously."""

    def __init__(self, rest_host: str = "127.0.0.1", rest_port: int = 8080):
        self.rest_host = rest_host
        self.rest_port = rest_port
        self.rest_server_task = None
        self.mcp_server_task = None

    async def start_rest_server(self):
        """Start the REST API server."""
        logger.info(f"🌐 Starting REST API server on http://{self.rest_host}:{self.rest_port}")
        logger.info(f"📚 API Documentation: http://{self.rest_host}:{self.rest_port}/docs")

        config = uvicorn.Config(rest_app, host=self.rest_host, port=self.rest_port, log_level="info", access_log=True)
        server = uvicorn.Server(config)
        await server.serve()

    async def start_mcp_server(self):
        """Start the MCP server."""
        logger.info("📡 Starting MCP server (stdio protocol)")
        logger.info("🔌 Ready for MCP client connections")

        # Import the main function from the MCP server module
        # Run MCP server in stdio mode
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(read_stream, write_stream, InitializationOptions(server_name="mcp-eval-server", server_version="0.1.0", capabilities={}))

    async def run(self):
        """Run both servers simultaneously.

        Raises:
            Exception: If server startup fails or encounters runtime errors.
        """
        logger.info("🚀 Starting MCP Evaluation Server in Hybrid Mode")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🎯 Dual Protocol Support:")
        logger.info("   📡 MCP Protocol: stdio (Model Context Protocol)")
        logger.info("   🌐 REST API: http://%s:%d", self.rest_host, self.rest_port)
        logger.info("   📚 API Docs: http://%s:%d/docs", self.rest_host, self.rest_port)
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        try:
            # Start both servers concurrently
            await asyncio.gather(self.start_rest_server(), self.start_mcp_server(), return_exceptions=True)
        except KeyboardInterrupt:
            logger.info("🛑 Hybrid server shutdown requested")
        except Exception as e:
            logger.error("❌ Error in hybrid server: %s", e)
            raise


def run_mcp_in_thread():
    """Run MCP server in a separate thread."""
    # This function will be called in a thread to handle stdio
    # Since stdio can only be used once, we'll modify this approach
    logger.info("📡 MCP server thread started")

    # We can't easily run MCP stdio in a thread alongside FastAPI
    # Instead, we'll document this limitation and recommend separate processes
    logger.warning("⚠️  MCP stdio server cannot run simultaneously with FastAPI in the same process")
    logger.info("💡 Recommendation: Run MCP and REST servers in separate processes")
    logger.info("   🔹 Process 1: python -m mcp_eval_server.server (MCP stdio)")
    logger.info("   🔹 Process 2: python -m mcp_eval_server.rest_server (REST API)")


async def main():
    """Main function for hybrid server."""
    parser = argparse.ArgumentParser(description="MCP Evaluation Server - Hybrid Mode")
    parser.add_argument("--rest-host", default="127.0.0.1", help="REST API host")
    parser.add_argument("--rest-port", type=int, default=8080, help="REST API port")
    parser.add_argument("--mode", choices=["rest-only", "info"], default="rest-only", help="Server mode: rest-only (default), info (show guidance)")

    args = parser.parse_args()

    if args.mode == "info":
        print("🎯 MCP Evaluation Server - Dual Protocol Guide")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("")
        print("📡 MCP Protocol (stdio) - For Claude Desktop, MCP clients:")
        print("   Command: python -m mcp_eval_server.server")
        print("   Port: none (stdio)")
        print("   Usage: Configure in MCP client as stdio server")
        print("")
        print("🌐 REST API (HTTP) - For direct HTTP integration:")
        print(f"   Command: python -m mcp_eval_server.rest_server --host {args.rest_host} --port {args.rest_port}")
        print(f"   URL: http://{args.rest_host}:{args.rest_port}")
        print(f"   Docs: http://{args.rest_host}:{args.rest_port}/docs")
        print("")
        print("🚀 Quick Start - Both Protocols:")
        print("   # Terminal 1 - MCP Server")
        print("   python -m mcp_eval_server.server")
        print("")
        print("   # Terminal 2 - REST API Server")
        print(f"   python -m mcp_eval_server.rest_server --host {args.rest_host} --port {args.rest_port}")
        print("")
        print("🔧 Make Commands:")
        print("   make dev                    # Start MCP server")
        print("   make serve-rest             # Start REST API server")
        print("   make test-mcp               # Test MCP protocol")
        print("   make test-rest              # Test REST API")
        print("")
        print("💡 Both servers can run simultaneously in separate terminals!")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return

    # For now, we'll just run the REST server with helpful info
    logger.info("🎯 Running in REST-only mode")
    logger.info("💡 To run MCP server simultaneously, use a separate terminal:")
    logger.info("   python -m mcp_eval_server.server")

    # Start REST server
    server = HybridServer(args.rest_host, args.rest_port)
    await server.start_rest_server()


if __name__ == "__main__":
    asyncio.run(main())
