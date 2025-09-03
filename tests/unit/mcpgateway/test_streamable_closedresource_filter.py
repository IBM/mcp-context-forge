# -*- coding: utf-8 -*-
"""Tests for suppressing ClosedResourceError logs from streamable HTTP.

These tests validate that normal client disconnects (anyio.ClosedResourceError)
do not spam ERROR logs via the upstream MCP logger.
"""

# Standard
import logging

# Third-Party
import anyio

# First-Party
from mcpgateway.services.logging_service import LoggingService


def test_closed_resource_error_is_suppressed(monkeypatch):
    service = LoggingService()
    # Initialize logging (installs filter)
    anyio.run(service.initialize)  # type: ignore[arg-type]

    emitted = []

    class Collector(logging.Handler):
        def emit(self, record):  # noqa: D401
            emitted.append(record)

    collector = Collector()
    collector.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(collector)
    root.setLevel(logging.DEBUG)

    logger = logging.getLogger("mcp.server.streamable_http")
    logger.setLevel(logging.DEBUG)

    # Emit a ClosedResourceError and ensure it's filtered
    try:
        raise anyio.ClosedResourceError
    except anyio.ClosedResourceError:
        logger.error("Error in message router", exc_info=True)

    # No records should be collected for the ClosedResourceError
    assert len(emitted) == 0

    # Emit a different error to ensure logging still works
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.error("Some real error", exc_info=True)

    assert len(emitted) == 1

    # Cleanup
    root.removeHandler(collector)
    anyio.run(service.shutdown)  # type: ignore[arg-type]
