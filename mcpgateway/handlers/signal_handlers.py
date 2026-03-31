# -*- coding: utf-8 -*-
"""Signal handlers for ContextForge Gateway.

Provides SIGHUP handling for certificate rotation without restart.
"""

# Standard
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def sighup_reload() -> None:
    """Clear SSL context cache and drain MCP session pool on SIGHUP for certificate rotation.

    Clears the SSL context cache to force recreation of SSL contexts
    with potentially updated certificates, and drains the MCP session
    pool so pooled connections reconnect with new TLS state.
    """
    try:
        # First-Party
        from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache  # pylint: disable=import-outside-toplevel

        clear_ssl_context_cache()
        logger.info("SIGHUP: SSL context cache cleared")
    except Exception as exc:
        logger.error(f"SIGHUP handler failed to clear SSL context cache: {exc}")

    try:
        # First-Party
        from mcpgateway.services.mcp_session_pool import drain_mcp_session_pool  # pylint: disable=import-outside-toplevel

        await drain_mcp_session_pool()
        logger.info("SIGHUP: MCP session pool drained for TLS rotation")
    except Exception as exc:
        logger.debug(f"SIGHUP: MCP session pool drain skipped: {exc}")


def sighup_handler(_signum: int, _frame: Any) -> None:
    """Handle SIGHUP signal by scheduling async SSL cache reload.

    Signal handler that safely schedules an asynchronous task to clear
    the SSL context cache. Uses the running event loop to create a task
    for the async reload operation.

    Args:
        _signum: Signal number (unused but required by signal handler signature)
        _frame: Current stack frame (unused but required by signal handler signature)
    """
    logger.info("Received SIGHUP signal, scheduling SSL context cache refresh")
    try:
        event_loop = asyncio.get_running_loop()
        event_loop.create_task(sighup_reload())
    except RuntimeError:
        logger.warning("SIGHUP received but event loop not running; skipping async reload")
