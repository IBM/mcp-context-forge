# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/deprecation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Deprecation headers middleware for ContextForge.

Injects ``Sunset``, ``Deprecation``, ``Link``, and
``X-Deprecated-Endpoint`` headers on responses from the legacy
(unversioned) route shims that were moved under ``/v1`` in PR #4403.

This middleware is a pure-ASGI implementation (not ``BaseHTTPMiddleware``)
to avoid the response-buffering issues that affect SSE / streaming routes.

Intentionally skipped paths (permanently unversioned):
- /v1/** (already versioned — never double-stamp)
- /health, /ready, /health/security
- /mcp, /_internal/**
- /oauth/**
- /.well-known/**, /servers/{id}/.well-known/**
- /version, /static/**, /
- /api/logs/**, /api/metrics/**
- /favicon.ico
"""

# Future
from __future__ import annotations

# Standard
from typing import Callable

# First-Party
from mcpgateway.services.logging_service import LoggingService

_logging_service = LoggingService()
logger = _logging_service.get_logger(__name__)

# ---------------------------------------------------------------------------
# Path-prefix set — mirrors build_legacy_router / _assemble_routers content.
# Every prefix listed here must correspond to a router that is dual-mounted.
# ---------------------------------------------------------------------------
_LEGACY_PREFIXES: frozenset[str] = frozenset(
    [
        "/protocol",
        "/tools",
        "/resources",
        "/prompts",
        "/gateways",
        "/roots",
        "/servers",
        "/metrics",
        "/tags",
        "/export",
        "/import",
        "/admin",
        "/a2a",
        "/observability",
        "/reverse-proxy",
        "/cancellation",
        "/toolops",
        "/auth",
        "/teams",
        "/tokens",
        "/rbac",
        "/llmchat",
        "/llm",
    ]
)


def _is_legacy_path(path: str) -> bool:
    """Return True when *path* belongs to a deprecated (unversioned) shim route.

    Exclusions (return False):
    - Paths already under /v1 — never stamp the canonical routes.
    - Paths containing /.well-known — permanently unversioned per RFC 9116.
    - Any path NOT in the explicit legacy prefix set.

    Args:
        path: The HTTP request path (may include query string — caller should
              pass ``scope["path"]`` which is already stripped of query).

    Returns:
        bool: True if deprecation headers should be added.

    Examples:
        >>> _is_legacy_path("/tools")
        True
        >>> _is_legacy_path("/tools/123")
        True
        >>> _is_legacy_path("/v1/tools")
        False
        >>> _is_legacy_path("/health")
        False
        >>> _is_legacy_path("/.well-known/security.txt")
        False
        >>> _is_legacy_path("/servers/abc/.well-known/agent.json")
        False
        >>> _is_legacy_path("/oauth/token")
        False
        >>> _is_legacy_path("/mcp")
        False
    """
    if path.startswith("/v1"):
        return False
    if "/.well-known" in path:
        return False
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _LEGACY_PREFIXES)


class DeprecationHeadersMiddleware:
    """Pure-ASGI middleware that stamps deprecation headers on legacy route responses.

    Responses served from the backward-compat unversioned shim routes (e.g.
    ``/tools``, ``/servers``) receive:

    * ``Sunset`` — RFC 8594 date after which the endpoint will be removed.
    * ``Deprecation: true`` — signals the endpoint is deprecated.
    * ``Link`` — points to the canonical ``/v1`` equivalent.
    * ``X-Deprecated-Endpoint`` — human-readable advisory message.

    No headers are added to:
    * Versioned ``/v1/*`` routes.
    * Permanently unversioned routes (health, mcp transport, oauth, well-known,
      static files, etc.).
    * Non-HTTP ASGI events (e.g. WebSocket handshakes, lifespan).

    Examples:
        >>> from starlette.testclient import TestClient
        >>> from starlette.applications import Starlette
        >>> from starlette.responses import PlainTextResponse
        >>> from starlette.routing import Route
        >>> def _home(req): return PlainTextResponse("ok")
        >>> app = Starlette(routes=[Route("/tools", _home)])
        >>> app.add_middleware(DeprecationHeadersMiddleware, sunset_date="Wed, 13 May 2026 00:00:00 GMT")
        >>> client = TestClient(app, raise_server_exceptions=True)
        >>> r = client.get("/tools")
        >>> r.status_code
        200
        >>> "Sunset" in r.headers
        True
    """

    def __init__(self, app: Callable, *, sunset_date: str) -> None:
        """Initialise the middleware.

        Args:
            app: The next ASGI application in the middleware stack.
            sunset_date: RFC 8594 / HTTP-date string for the ``Sunset`` header,
                         e.g. ``"Wed, 13 May 2026 00:00:00 GMT"``.
        """
        self.app = app
        self._sunset_date = sunset_date
        logger.debug("DeprecationHeadersMiddleware initialised (sunset=%s)", sunset_date)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Process one ASGI event.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] != "http":
            # Pass through WebSocket / lifespan unchanged.
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not _is_legacy_path(path):
            await self.app(scope, receive, send)
            return

        # Build the canonical /v1 link once per request.
        canonical = f"/v1{path}"
        sunset = self._sunset_date
        extra_headers: list[tuple[bytes, bytes]] = [
            (b"sunset", sunset.encode()),
            (b"deprecation", b"true"),
            (b"link", f'<{canonical}>; rel="successor-version"'.encode()),
            (
                b"x-deprecated-endpoint",
                (f"This endpoint is deprecated. " f"Use {canonical} instead. " f"It will be removed after {sunset}.").encode(),
            ),
        ]

        async def _send_with_deprecation(message: dict) -> None:
            """Intercept ``http.response.start`` to inject deprecation headers.

            Args:
                message: Outgoing ASGI message.
            """
            if message.get("type") == "http.response.start":
                headers: list = list(message.get("headers") or [])
                headers.extend(extra_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_deprecation)
