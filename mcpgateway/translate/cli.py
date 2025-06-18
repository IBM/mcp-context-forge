# -*- coding: utf-8 -*-
"""MCP Gateway Transport-Translation Bridge CLI.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

This module implements the command-line interface for the transport-translation bridge
that allows MCP stdio-based servers and remote SSE/Streamable-HTTP endpoints to 
communicate over different transport protocols through a single CLI command.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Optional

from .bridge import TranslateBridge

# Default configuration
DEFAULT_PORT = 8000
DEFAULT_SSE_PATH = "/sse"
DEFAULT_MESSAGE_PATH = "/message"
DEFAULT_HEALTH_ENDPOINT = "/healthz"


def setup_logging(log_level: str) -> None:
    """Setup logging configuration.
    
    Args:
        log_level: Logging level (debug, info, none)
    """
    if log_level == "none":
        logging.disable(logging.CRITICAL)
        return
    
    level = logging.DEBUG if log_level == "debug" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def parse_headers(header_list: List[str]) -> Dict[str, str]:
    """Parse header list into dictionary.
    
    Args:
        header_list: List of header strings in format "key:value"
        
    Returns:
        Dictionary of headers
        
    Raises:
        ValueError: If header format is invalid
    """
    headers = {}
    for header in header_list:
        if ":" not in header:
            raise ValueError(f"Invalid header format: {header}. Expected 'key:value'")
        key, value = header.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def validate_args(args: argparse.Namespace) -> None:
    """Validate command line arguments.
    
    Args:
        args: Parsed arguments
        
    Raises:
        ValueError: If arguments are invalid
    """
    # Check for conflicting input transports
    input_count = sum([
        bool(args.stdio),
        bool(args.sse),
        bool(args.streamableHttp)
    ])
    
    if input_count != 1:
        raise ValueError("Exactly one input transport must be specified")
    
    # Validate port range
    if not (1 <= args.port <= 65535):
        raise ValueError("Port must be between 1 and 65535")
    
    # Validate headers
    try:
        parse_headers(args.header)
    except ValueError as e:
        raise ValueError(f"Invalid header: {e}")


def determine_output_transport(args: argparse.Namespace) -> str:
    """Determine output transport based on input and explicit settings.
    
    Args:
        args: Parsed arguments
        
    Returns:
        Output transport type
    """
    if args.outputTransport:
        return args.outputTransport
    
    # Auto-detect based on input
    if args.stdio:
        return "sse"  # stdio -> SSE for browser clients
    elif args.sse:
        return "stdio"  # SSE -> stdio for command-line tools
    elif args.streamableHttp:
        return "stdio"  # HTTP -> stdio for command-line tools
    
    return "sse"  # default fallback


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for the translate CLI.
    
    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="MCP Gateway Transport-Translation Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Expose stdio server over SSE
  mcpgateway-translate --stdio "uvx mcp-server-git" --port 9000

  # Bridge remote SSE to local stdio
  mcpgateway-translate --sse "https://corp.example.com/mcp"

  # Full configuration with CORS and health endpoint
  mcpgateway-translate --stdio "python -m mcp_server" --port 8080 \\
    --cors "https://app.example.com" --healthEndpoint /health
        """
    )
    
    # Input transport (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--stdio",
        help="Command to run stdio MCP server (e.g., 'uvx mcp-server-git')"
    )
    input_group.add_argument(
        "--sse",
        help="Remote SSE endpoint URL (e.g., 'https://corp.example.com/mcp')"
    )
    input_group.add_argument(
        "--streamableHttp",
        help="Remote Streamable HTTP endpoint URL"
    )
    
    # Output transport
    parser.add_argument(
        "--outputTransport",
        choices=["stdio", "sse", "ws"],
        help="Output transport type (auto-detected if not specified)"
    )
    
    # Server configuration
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--baseUrl",
        help="Base URL for the server (auto-detected if not specified)"
    )
    parser.add_argument(
        "--ssePath",
        default=DEFAULT_SSE_PATH,
        help=f"SSE endpoint path (default: {DEFAULT_SSE_PATH})"
    )
    parser.add_argument(
        "--messagePath",
        default=DEFAULT_MESSAGE_PATH,
        help=f"Message endpoint path (default: {DEFAULT_MESSAGE_PATH})"
    )
    
    # Authentication and headers
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="HTTP header in format 'key:value' (can be used multiple times)"
    )
    parser.add_argument(
        "--oauth2Bearer",
        help="OAuth2 Bearer token for authentication"
    )
    
    # Logging
    parser.add_argument(
        "--logLevel",
        choices=["debug", "info", "none"],
        default="info",
        help="Logging level (default: info)"
    )
    
    # CORS and health
    parser.add_argument(
        "--cors",
        nargs="*",
        help="CORS allowed origins (e.g., --cors https://app.example.com)"
    )
    parser.add_argument(
        "--healthEndpoint",
        help="Health check endpoint path (e.g., /healthz)"
    )
    
    return parser


async def run_bridge_async(args: argparse.Namespace) -> None:
    """Run the transport bridge asynchronously.
    
    Args:
        args: Parsed command line arguments
    """
    # Parse headers
    headers = parse_headers(args.header)
    
    # Add OAuth2 bearer token if provided
    if args.oauth2Bearer:
        headers["Authorization"] = f"Bearer {args.oauth2Bearer}"
    
    # Create bridge configuration
    bridge_config = {
        "stdio_command": args.stdio,
        "sse_url": args.sse,
        "streamable_http_url": args.streamableHttp,
        "output_transport": determine_output_transport(args),
        "port": args.port,
        "base_url": args.baseUrl,
        "sse_path": args.ssePath,
        "message_path": args.messagePath,
        "headers": headers,
        "cors_origins": args.cors or [],
        "health_endpoint": args.healthEndpoint,
        "log_level": args.logLevel,
    }
    
    # Create and run bridge
    bridge = TranslateBridge(bridge_config)
    await bridge.run()


def main() -> None:
    """Main entry point for the mcpgateway.translate console script."""
    parser = create_parser()
    args = parser.parse_args()
    
    try:
        # Setup logging
        setup_logging(args.logLevel)
        
        # Validate arguments
        validate_args(args)
        
        # Run the bridge
        asyncio.run(run_bridge_async(args))
        
    except KeyboardInterrupt:
        logging.info("Bridge interrupted by user")
        sys.exit(0)
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        if args.logLevel == "debug":
            logging.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
