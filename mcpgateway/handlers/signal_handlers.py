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
    """Clear SSL context cache + drain upstream sessions on SIGHUP for certificate rotation.

    Three things have to happen in order for new TLS material to take effect
    on a worker without restart:
      1. Clear the SSL context cache so the next build uses new certs.
      2. Close every in-process upstream MCP session — they hold their TLS
         context on the socket and would keep using the old certs forever.
      3. Drain the session-affinity in-memory mapping so the next downstream
         request re-registers (Redis state survives; only the local fast-
         path cache is cleared).
    """
    try:
        # First-Party
        from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache  # pylint: disable=import-outside-toplevel

        clear_ssl_context_cache()
        logger.info("SIGHUP: SSL context cache cleared")
    except Exception as exc:
        logger.error(f"SIGHUP handler failed to clear SSL context cache: {exc}")

    # #4205: upstream MCP sessions live in the registry now — draining only
    # the affinity mapping was leaving stale TLS contexts pinned to registry-
    # held ClientSessions.
    try:
        # First-Party
        from mcpgateway.services.upstream_session_registry import (  # pylint: disable=import-outside-toplevel
            get_upstream_session_registry,
            RegistryNotInitializedError,
        )

        await get_upstream_session_registry().close_all()
        logger.info("SIGHUP: upstream session registry drained for TLS rotation")
    except RegistryNotInitializedError:
        logger.debug("SIGHUP: upstream session registry not initialised; skipping drain")
    except Exception as exc:
        logger.warning(f"SIGHUP: upstream session registry drain failed: {exc}")

    try:
        # First-Party
        from mcpgateway.services.session_affinity import drain_session_affinity  # pylint: disable=import-outside-toplevel

        await drain_session_affinity()
        logger.info("SIGHUP: session-affinity mapping drained")
    except Exception as exc:
        logger.debug(f"SIGHUP: session-affinity drain skipped: {exc}")


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
