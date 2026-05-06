# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/mcp_ingress_mount.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Swappable mount point for the public ``/mcp`` ingress.

The mount itself owns no routing policy. It holds a registry of named
ingress ASGI apps and a callable that returns the name of whichever one
should serve the current request. Adding a new ingress (rust-public-proxy,
shadow-comparison, percentage-traffic-split, …) is a one-line
``register()`` call; selection policy is one function.

This replaces the role of the prior ``MCPStreamableHTTPModeDispatcher``
(which was hard-coded to a Python transport plus a single Rust transport,
with the per-request choice baked into its ``handle_streamable_http``
method). See
``docs/docs/architecture/adr/051-swappable-mcp-ingress-mount.md`` for
the design decision and migration notes.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Awaitable, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class ASGIApp(Protocol):
    """ASGI 3.0 callable. Any ingress registered with the mount must satisfy this."""

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
        """ASGI 3.0 entry point. Implementations consume ``receive`` and emit via ``send``."""


# An ``IngressSelector`` returns the registered ingress name to serve THIS
# request. It receives the ASGI scope so policies can inspect method, path,
# headers, query — useful for routing GET /mcp (SSE) differently from POST.
IngressSelector = Callable[[dict], str]


class MCPIngressMount:
    """Indirection at /mcp that delegates to a swappable inner ASGI app.

    Lifecycle:
      1. Construct with a selector and (optionally) a fallback ingress.
      2. Register every ingress this build supports.
      3. Mount once at /mcp via ``app.mount("/mcp", mount.dispatch)``.
      4. Add/replace ingresses or swap the selector at runtime; the mount
         picks them up on the next request.

    Concurrency: ingress lookup is a single dict read on the request hot
    path, no locks. Registration writes are not synchronized — the
    assumption is that ingresses are registered at startup and changed
    only via admin actions that already go through their own coordination
    (e.g. the runtime override coordinator). If you need atomic policy
    swaps mid-flight, swap the selector via :meth:`set_selector` rather
    than rewriting registrations.

    Drain semantics: an ingress that owns long-lived connections (SSE,
    chunked POST) keeps serving them even after it is unregistered or
    selected away from. The next request just routes to the new ingress.
    This matches the prior dispatcher's "natural drain" property.
    """

    def __init__(
        self,
        *,
        selector: IngressSelector,
        fallback: Optional[ASGIApp] = None,
    ) -> None:
        """Initialize the mount with a selection policy and optional fallback.

        Args:
            selector: Function that returns the registered ingress name to
                serve a given ASGI scope.
            fallback: ASGI app used when the selector returns a name that
                isn't registered. ``None`` means "send a 503 naming the
                missing ingress" — useful in dev to fail loudly; production
                deployments typically pass the Python transport here.
        """
        self._ingresses: Dict[str, ASGIApp] = {}
        self._selector = selector
        self._fallback = fallback

    # ── registry -----------------------------------------------------------

    def register(self, name: str, app: ASGIApp) -> None:
        """Register an ingress under ``name``.

        Idempotent — calling ``register("x", app1)`` then
        ``register("x", app2)`` replaces ``app1``.

        Args:
            name: Identifier the selector will return to pick this app.
            app: ASGI 3.0 callable.
        """
        self._ingresses[name] = app

    def unregister(self, name: str) -> Optional[ASGIApp]:
        """Remove an ingress; returns the prior app for graceful shutdown.

        Args:
            name: Ingress identifier.

        Returns:
            The previously-registered ASGI app, or ``None`` if the name
            wasn't registered. Caller is responsible for any drain or
            cleanup on the returned app.
        """
        return self._ingresses.pop(name, None)

    def names(self) -> List[str]:
        """Return the sorted list of currently-registered ingress names.

        Returns:
            Sorted list of ingress names. Useful for diagnostics, /health,
            and the 503 body when a selector returns an unknown name.
        """
        return sorted(self._ingresses)

    # ── policy ------------------------------------------------------------

    def set_selector(self, selector: IngressSelector) -> None:
        """Atomically swap the selection policy.

        Args:
            selector: New selector function. Takes effect on the next
                request — in-flight requests already inside an ingress
                continue under the old selection.
        """
        self._selector = selector

    def set_fallback(self, app: Optional[ASGIApp]) -> None:
        """Update the fallback app used when the selector misses.

        Args:
            app: New fallback ASGI app, or ``None`` to restore the
                503-on-miss behavior.
        """
        self._fallback = app

    # ── ASGI app ---------------------------------------------------------

    async def dispatch(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI entry point. Picks an ingress per request and delegates.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        name = self._selector(scope)
        app = self._ingresses.get(name)
        if app is None:
            # Selector miss is an invariant violation — the registered set
            # and the policy are out of sync. Either path (fallback or
            # 503) deserves a warning, not debug, so a misconfigured
            # selector doesn't silently route auth-sensitive traffic to
            # the wrong handler.
            if self._fallback is None:
                logger.warning(
                    "MCPIngressMount: selector returned %r but no ingress is registered under that name; available=%s. Returning 503.",
                    name,
                    self.names(),
                )
                await self._send_503(send, name)
                return
            logger.warning(
                "MCPIngressMount: selector returned %r which is not registered; available=%s. Falling back to the configured fallback app.",
                name,
                self.names(),
            )
            app = self._fallback
        await app(scope, receive, send)

    async def _send_503(self, send: Callable, missing_name: str) -> None:
        """Emit a 503 response naming the missing ingress.

        Args:
            send: ASGI send callable.
            missing_name: The ingress name the selector returned.
        """
        body = (f"MCP ingress {missing_name!r} is not registered for this build; " f"available: {self.names() or '[]'}").encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
