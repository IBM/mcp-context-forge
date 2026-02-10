# -*- coding: utf-8 -*-
"""Bridge for optional experimental Rust streamable HTTP transport backend."""

from __future__ import annotations

# Standard
import os
from typing import Any, Callable

# First-Party
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class RustStreamableHTTPTransportBridge:
    """Thin adapter around an optional Rust streamable HTTP backend."""

    def __init__(self, enabled: bool, start_fn: Callable[[dict[str, Any]], bool] | None) -> None:
        self.enabled = enabled
        self._start_fn = start_fn

    @classmethod
    def from_env(cls) -> "RustStreamableHTTPTransportBridge":
        """Create bridge based on MCP_USE_RUST_TRANSPORT feature toggle."""
        enabled = os.getenv("MCP_USE_RUST_TRANSPORT", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return cls(enabled=False, start_fn=None)

        try:
            # First-Party
            from mcpgateway_transport_rs import start_streamable_http_transport  # type: ignore[import-not-found]

            logger.info("🦀 Experimental Rust streamable HTTP transport enabled")
            return cls(enabled=True, start_fn=start_streamable_http_transport)
        except Exception as exc:  # pragma: no cover - environment specific import
            logger.warning("Rust transport requested but unavailable, falling back to Python streamable HTTP: %s", exc)
            return cls(enabled=False, start_fn=None)

    async def handle_request(self, scope: Any, _receive: Any, _send: Any) -> bool:
        """Attempt to process the request in Rust.

        Returns True only when Rust handled the request. For the initial scaffold,
        Rust returns False, so Python handling remains active.
        """
        if not self.enabled or self._start_fn is None:
            return False

        try:
            return bool(self._start_fn(scope))
        except Exception as exc:
            logger.warning("Rust streamable HTTP backend failed, using Python fallback: %s", exc)
            return False


__all__ = ["RustStreamableHTTPTransportBridge"]