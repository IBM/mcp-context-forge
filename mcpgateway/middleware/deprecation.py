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

**IMPORTANT: _LEGACY_PREFIXES Synchronization**

The ``_LEGACY_PREFIXES`` set below MUST be kept in sync with the routers
assembled by ``_assemble_routers()`` in ``mcpgateway/api/v1/__init__.py``.

When adding a new router to ``_assemble_routers()``, you MUST also add its
prefix to ``_LEGACY_PREFIXES`` to ensure deprecation headers are applied
to the legacy (unversioned) routes.

A unit test (``tests/unit/mcpgateway/test_api_versioning_parity.py``) validates
this synchronization and will fail if prefixes diverge.

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
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Optional

# Third-Party
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
        # Core routers (always mounted)
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
        # Feature-flagged routers (conditionally mounted)
        "/a2a",  # MCPGATEWAY_A2A_ENABLED
        "/observability",  # OBSERVABILITY_ENABLED
        "/reverse-proxy",  # MCPGATEWAY_REVERSE_PROXY_ENABLED
        "/cancellation",  # MCPGATEWAY_TOOL_CANCELLATION_ENABLED
        "/toolops",  # TOOLOPS_ENABLED
        "/auth",  # EMAIL_AUTH_ENABLED
        "/teams",  # EMAIL_AUTH_ENABLED
        "/tokens",  # EMAIL_AUTH_ENABLED
        "/rbac",  # EMAIL_AUTH_ENABLED
        "/compliance",  # MCPGATEWAY_ADMIN_API_ENABLED
        "/admin",  # MCPGATEWAY_ADMIN_API_ENABLED
        "/llmchat",  # MCPGATEWAY_LLM_CHAT_ENABLED
        "/llm",  # MCPGATEWAY_LLM_CHAT_ENABLED
    ]
)


def _is_legacy_path(path: str) -> bool:
    """Return True when *path* belongs to a deprecated (unversioned) shim route.

    Exclusions (return False):
    - Paths already under /v1 — never stamp the canonical routes.
    - Paths containing /.well-known — permanently unversioned per RFC 9116.
    - Any path NOT in the explicit legacy prefix set.
    - Invalid paths (empty, non-absolute, containing null bytes or control chars).

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
        >>> _is_legacy_path("")
        False
        >>> _is_legacy_path("tools")
        False
    """
    # Validate path structure
    if not path or not isinstance(path, str):
        return False
    if not path.startswith("/"):
        return False

    # Fast-exit for versioned routes — majority of post-migration traffic hits
    # /v1/** and never needs the O(N) control-char scan below.
    if path.startswith("/v1"):
        return False

    # Control-char validation (only runs for unversioned paths)
    if "\x00" in path or any(ord(c) < 32 and c not in ("\t", "\n", "\r") for c in path):
        logger.warning("Invalid path with control characters rejected: %r", path[:100])
        return False

    # Exclude permanently unversioned routes
    if "/.well-known" in path:
        return False

    # Check against legacy prefix set
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

    def __init__(self, app: ASGIApp, *, sunset_date: str) -> None:
        """Initialise the middleware.

        Args:
            app: The next ASGI application in the middleware stack.
            sunset_date: RFC 8594 / HTTP-date string for the ``Sunset`` header,
                         e.g. ``"Wed, 13 May 2026 00:00:00 GMT"``.
        """
        self.app = app
        self._sunset_date: Optional[str] = None

        if not sunset_date or not sunset_date.strip():
            logger.error("LEGACY_API_SUNSET_DATE is empty or whitespace; Sunset deprecation headers will be omitted.")
            return

        # Parse and re-serialise to canonical HTTP-date — strips any CR/LF that
        # could be injected via a misconfigured env var or secrets-manager value.
        try:
            sunset_dt = parsedate_to_datetime(sunset_date)
            self._sunset_date = format_datetime(sunset_dt, usegmt=True)
            now = datetime.now(sunset_dt.tzinfo)
            days_until_sunset = (sunset_dt - now).days

            if days_until_sunset < 0:
                logger.warning(
                    "LEGACY API SUNSET DATE HAS PASSED! Legacy routes are %d days overdue for removal. Set LEGACY_API_ENABLED=false to disable legacy routes. Sunset date: %s",
                    abs(days_until_sunset),
                    self._sunset_date,
                )
            elif days_until_sunset <= 30:
                logger.warning(
                    "Legacy API sunset approaching: %d days remaining until %s. Prepare to migrate clients to /v1 routes. Set LEGACY_API_ENABLED=false to disable legacy routes now.",
                    days_until_sunset,
                    self._sunset_date,
                )
            else:
                logger.info(
                    "Legacy API deprecation active. Sunset date: %s (%d days remaining)",
                    self._sunset_date,
                    days_until_sunset,
                )
        except (ValueError, TypeError) as e:
            logger.error("Failed to parse sunset date '%s': %s — Sunset deprecation headers will be omitted.", sunset_date, e)
            self._sunset_date = None

        logger.debug("DeprecationHeadersMiddleware initialised (sunset=%s)", sunset_date)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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
        if not _is_legacy_path(path) or self._sunset_date is None:
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
                (f"This endpoint is deprecated. Use {canonical} instead. It will be removed after {sunset}.").encode(),
            ),
        ]

        async def _send_with_deprecation(message: Message) -> None:
            """Intercept ``http.response.start`` to inject deprecation headers.

            Args:
                message: Outgoing ASGI message.
            """
            if message.get("type") == "http.response.start":
                headers: list = list(message.get("headers") or [])
                # Only stamp deprecation headers on non-error responses — a
                # Sunset header on a 401/403 can mislead clients into thinking
                # the route exists and is merely deprecated.
                if message.get("status", 200) < 400:
                    headers.extend(extra_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_deprecation)
