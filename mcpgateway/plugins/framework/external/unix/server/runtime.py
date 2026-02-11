# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/unix/server/runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Entry point for running the Unix socket plugin server.

Usage:
    python -m mcpgateway.plugins.framework.external.unix.server.runtime

Environment variables:
    PLUGINS_CONFIG_PATH: Path to plugin configuration file
    UNIX_SOCKET_PATH: Path for Unix socket (default: /tmp/mcpgateway-plugins.sock)

Examples:
    Run with default settings:

    $ PLUGINS_CONFIG_PATH=plugins/config.yaml python -m mcpgateway.plugins.framework.external.unix.server.runtime

    Run with custom socket path:

    $ UNIX_SOCKET_PATH=/tmp/my-plugins.sock python -m mcpgateway.plugins.framework.external.unix.server.runtime
"""

# Standard
import asyncio
import logging
import os
import sys

# First-Party
from mcpgateway.plugins.framework.external.unix.server.server import run_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # Log to stderr to keep stdout clean for coordination
)

logger = logging.getLogger(__name__)


async def run() -> None:
    """Main entry point for the Unix socket server."""
    # First-Party
    from mcpgateway.plugins.framework.settings import PluginsSettings

    s = PluginsSettings()
    config_path = s.config_path or os.path.join(".", "resources", "plugins", "config.yaml")
    socket_path = s.unix_socket_path or "/tmp/mcpgateway-plugins.sock"  # nosec B108 - configurable via env var

    logger.info("Starting Unix socket plugin server")
    logger.info("  Config: %s", config_path)
    logger.info("  Socket: %s", socket_path)

    await run_server(config_path=config_path, socket_path=socket_path)


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Server interrupted")
    except Exception as e:
        logger.exception("Server error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
