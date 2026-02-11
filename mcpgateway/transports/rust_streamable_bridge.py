# -*- coding: utf-8 -*-
"""Bridge for optional experimental Rust streamable HTTP transport backend."""

from __future__ import annotations

# Standard
from dataclasses import dataclass
import inspect
import os
import re
from typing import Any, Awaitable, Callable, Dict, Optional

# First-Party
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


@dataclass(slots=True)
class RustStreamableRequestContext:
    """Normalized request context produced by the Rust backend."""

    path: str
    headers: Dict[str, str]
    server_id: Optional[str]
    is_mcp_path: bool


def _extract_server_id(path: str) -> Optional[str]:
    match = re.search(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp", path)
    if not match:
        return None
    return match.group("server_id")


class RustStreamableHTTPTransportBridge:
    """Adapter around the optional Rust streamable HTTP backend.

    This bridge keeps Python as fallback while allowing Rust to pre-process
    ASGI scope data for streamable HTTP request handling.
    """

    def __init__(
        self,
        enabled: bool,
        context_fn: Callable[[Dict[str, Any]], Dict[str, Any]] | None,
        request_handler_fn: Callable[[Dict[str, Any], Any, Any], Awaitable[bool] | bool] | None,
    ) -> None:
        self.enabled = enabled
        self._context_fn = context_fn
        self._request_handler_fn = request_handler_fn

    @classmethod
    def from_env(cls) -> "RustStreamableHTTPTransportBridge":
        """Create bridge based on MCP_USE_RUST_TRANSPORT feature toggle."""
        enabled = os.getenv("MCP_USE_RUST_TRANSPORT", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return cls(enabled=False, context_fn=None, request_handler_fn=None)

        try:
            # First-Party
            from mcpgateway_transport_rs import prepare_streamable_http_context  # type: ignore[import-not-found]
            from mcpgateway_transport_rs import start_streamable_http_transport

            logger.info("🦀 Experimental Rust streamable HTTP transport enabled")
            return cls(enabled=True, context_fn=prepare_streamable_http_context, request_handler_fn=start_streamable_http_transport)
        except Exception as exc:  # pragma: no cover - env specific import behavior
            logger.warning("Rust transport requested but unavailable, using Python streamable HTTP context: %s", exc)
            return cls(enabled=False, context_fn=None, request_handler_fn=None)

    async def prepare_request_context(self, scope: Dict[str, Any]) -> RustStreamableRequestContext:
        """Build normalized request context from Rust or Python fallback."""
        fallback_path = str(scope.get("modified_path") or scope.get("path") or "")
        fallback_headers = {str(k).lower(): str(v) for k, v in dict(scope.get("headers_dict") or {}).items()}
        context = RustStreamableRequestContext(
            path=fallback_path,
            headers=fallback_headers,
            server_id=_extract_server_id(fallback_path),
            is_mcp_path=fallback_path.endswith("/mcp") or fallback_path.endswith("/mcp/"),
        )

        if not self.enabled or self._context_fn is None:
            return context

        try:
            result = self._context_fn(scope)
            return RustStreamableRequestContext(
                path=str(result.get("path") or fallback_path),
                headers={str(k).lower(): str(v) for k, v in dict(result.get("headers") or {}).items()},
                server_id=(str(result["server_id"]) if result.get("server_id") else None),
                is_mcp_path=bool(result.get("is_mcp_path", context.is_mcp_path)),
            )
        except Exception as exc:
            logger.warning("Rust streamable HTTP context prep failed, using Python fallback: %s", exc)
            return context

    async def handle_request(self, scope: Dict[str, Any], receive: Any, send: Any) -> bool:
        """Attempt Rust-native request handling and return whether request was handled.
        Returns False whenever the Rust backend is disabled, unavailable, or fails.
        """
        if not self.enabled or self._request_handler_fn is None:
            return False

        try:
            result = self._request_handler_fn(scope, receive, send)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.warning("Rust streamable HTTP request handler failed, using Python fallback: %s", exc)
            return False

__all__ = ["RustStreamableHTTPTransportBridge", "RustStreamableRequestContext"]