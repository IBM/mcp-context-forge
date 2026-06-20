# -*- coding: utf-8 -*-
"""A2A virtual-server path-rewrite ASGI middleware (Plan T16).

Location: ./mcpgateway/middleware/a2a_path_rewrite.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Rewrites incoming ``/servers/{server_id}/a2a/{agent_name}[/...]`` requests
to the canonical per-agent path ``/a2a/{agent_name}[/...]`` and stamps
``request.scope["a2a_server_id"] = server_id`` so the existing T11 + T12
handlers can enforce v-server membership without a duplicate route
decorator.

Design (mirrors ``MCPPathRewriteMiddleware`` shape per plan F2):

- Pure ASGI middleware (NOT ``BaseHTTPMiddleware``) for low overhead and
  full scope mutability.
- Only HTTP scope is considered; WebSocket / lifespan scope is passed
  through untouched.
- Strips ``root_path`` (reverse-proxy prefix) before regex matching so
  the same logic works behind a path-rewriting reverse proxy.
- Regex ``^/servers/([^/]+)/a2a/([^/]+)(/.*)?$`` matches BOTH the base
  dispatch URL ``/servers/X/a2a/Y`` AND any suffix (e.g.
  ``/.well-known/agent-card.json``). The trailing group is OPTIONAL —
  this is Oracle #14's fix; requiring ``/.*`` would miss the base
  dispatch URL.

Plan invariants enforced here:

- MUST NOT enforce v-server membership (handler's job per T2 + T3 +
  T11 + T12; D14).
- MUST NOT match outside ``/servers/{id}/a2a/...``.
- MUST NOT require a trailing ``/`` (Oracle #14).
- Preserves ``scope["modified_path"]`` so downstream middleware that
  reads the original path keeps its contract.
"""

from __future__ import annotations

import logging
import re

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


# Captures: ``server_id`` (1), ``agent_name`` (2), optional ``suffix`` (3).
# The third group is intentionally optional (``?``) so the base dispatch
# URL ``/servers/X/a2a/Y`` (NO trailing slash) is matched along with
# every suffix-bearing URL like ``/.well-known/agent-card.json``.
_A2A_VSERVER_PATH_RE = re.compile(r"^/servers/([^/]+)/a2a/([^/]+)(/.*)?$")


class A2APathRewriteMiddleware:
    """ASGI middleware that rewrites v-server-scoped A2A paths.

    Inbound: ``/servers/{server_id}/a2a/{agent_name}[/suffix]``
    Rewritten: ``/a2a/{agent_name}[/suffix]``
    Side effect: ``scope["a2a_server_id"] = server_id``

    The T11 (card) and T12 (dispatch) handlers already read
    ``request.scope.get("a2a_server_id")`` and pass it to
    :py:meth:`A2AAgentService.synthesize_agent_card` /
    :py:meth:`A2AAgentService.resolve_agent_for_dispatch` so v-server
    membership is checked at the service layer.

    Non-A2A paths (including ``/a2a/...`` direct per-agent URLs and
    ``/servers/{id}/mcp`` MCP transport URLs) pass through unchanged.
    """

    def __init__(self, application: ASGIApp) -> None:
        """Wrap an ASGI ``application`` with the v-server path rewrite.

        Args:
            application: The next ASGI app in the middleware chain.
        """
        self.application: ASGIApp = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Intercept HTTP requests and rewrite v-server-scoped A2A paths.

        Args:
            scope: The ASGI connection scope.
            receive: Awaitable that yields events from the client.
            send: Awaitable used to send events to the client.
        """
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        original_path = scope.get("path", "")

        # Reverse-proxy prefix handling: strip ``root_path`` before
        # matching so paths like ``/proxy/servers/X/a2a/Y`` match the
        # same regex as ``/servers/X/a2a/Y``.
        root_path = (scope.get("root_path") or "").rstrip("/")
        if root_path and original_path.startswith(root_path + "/"):
            app_path = original_path[len(root_path) :]
        else:
            app_path = original_path

        # Preserve modified_path for downstream middleware that reads
        # the canonical app-relative path (matches MCPPathRewriteMiddleware
        # convention at main.py:3021).
        scope["modified_path"] = app_path

        match = _A2A_VSERVER_PATH_RE.match(app_path)
        if not match:
            await self.application(scope, receive, send)
            return

        server_id = match.group(1)
        agent_name = match.group(2)
        suffix = match.group(3) or ""

        # Rewrite path. Preserve ``root_path`` prefix when present.
        new_app_path = f"/a2a/{agent_name}{suffix}"
        new_path = f"{root_path}{new_app_path}" if root_path else new_app_path

        scope["path"] = new_path
        scope["modified_path"] = new_app_path
        scope["a2a_server_id"] = server_id

        # Keep ``raw_path`` aligned so downstream consumers that read it
        # see the rewritten form. ASGI raw_path stores raw octets; latin-1
        # preserves a 1:1 byte mapping for valid values.
        if "raw_path" in scope:
            try:
                scope["raw_path"] = new_path.encode("latin-1")
            except (UnicodeEncodeError, ValueError):
                logger.warning("A2APathRewriteMiddleware: non-latin-1 raw_path skipped for %s", new_path)

        logger.debug("A2APathRewriteMiddleware: %s -> %s (server_id=%s)", original_path, new_path, server_id)

        await self.application(scope, receive, send)
