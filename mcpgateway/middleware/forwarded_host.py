# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/forwarded_host.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Forwarded Host Middleware.

Rewrites the ASGI ``host`` header and ``scope["server"]`` tuple from the
``X-Forwarded-Host`` header set by a reverse proxy.

Uvicorn's ``ProxyHeadersMiddleware`` handles ``X-Forwarded-Proto`` (scheme)
and ``X-Forwarded-For`` (client IP) but does **not** handle
``X-Forwarded-Host`` (upstream issue encode/uvicorn#965, open PR #2811).

This middleware fills that gap so that ``request.base_url`` (used in admin UI
hints, OAuth redirect_uri display, well-known URLs, etc.) reflects the
proxy's public host rather than the gateway's internal address.

Starlette builds ``request.base_url`` from the ``host`` header, not from
``scope["server"]``.  The host header rewrite is therefore the critical
change; ``scope["server"]`` is updated as well for other ASGI consumers.

Register this middleware **after** ``ProxyHeadersMiddleware`` in the
``add_middleware`` stack (which means it executes **before** it in the ASGI
call chain, ensuring the scheme is already corrected when we derive the
default port for ``scope["server"]``).

Trust decisions (which upstream IPs may set forwarded headers) are the
responsibility of the caller — this middleware always acts when
``X-Forwarded-Host`` is present.  The gateway should only register it
when proxy headers are trusted (the same condition under which
``ProxyHeadersMiddleware`` is registered).

When Uvicorn merges upstream support, this middleware can be removed.
"""

# Future
from __future__ import annotations

# Standard
import logging

# Third-Party
from uvicorn._types import (
    ASGI3Application,
    ASGIReceiveCallable,
    ASGISendCallable,
    Scope,
)

logger = logging.getLogger(__name__)


class ForwardedHostMiddleware:
    """Rewrite the ASGI ``host`` header from ``X-Forwarded-Host``.

    Mirrors the approach in Uvicorn PR #2811:
    * Parses host and optional port from the header value.
    * Updates ``scope["server"]`` with ``(host, port)``.
    * Replaces the ``host`` entry in ``scope["headers"]`` so that
      Starlette's ``request.base_url`` returns the proxy origin.

    Proxies typically send just the hostname for standard ports
    (``X-Forwarded-Host: example.com``) and include the port only for
    non-standard ones (``X-Forwarded-Host: example.com:8443``).  When
    no port is present, ``scope["server"]`` is filled with the standard
    default for the scheme (80 for http/ws, 443 for https/wss).
    """

    def __init__(self, app: ASGI3Application) -> None:
        """Initialise middleware with the inner ASGI app."""
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        """Rewrite host header from X-Forwarded-Host if present."""
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope["headers"])  # type: ignore[arg-type]

            if b"x-forwarded-host" in headers:
                raw = headers[b"x-forwarded-host"].decode("latin1")
                # Take only the first value if comma-separated (leftmost =
                # client-facing hop).
                x_forwarded_host = raw.split(",")[0].strip()

                if x_forwarded_host:
                    # Default port for scope["server"] when the header omits one.
                    default_port = 443 if scope.get("scheme") in ("https", "wss") else 80

                    # Parse host and optional port.
                    # IPv6 addresses are bracketed, e.g. [::1]:8080.  A trailing
                    # "]" means IPv6 *without* a port suffix.
                    if ":" in x_forwarded_host and not x_forwarded_host.endswith("]"):
                        host_part, port_str = x_forwarded_host.rsplit(":", 1)
                        try:
                            port = int(port_str)
                        except ValueError:
                            port = default_port
                    else:
                        host_part = x_forwarded_host
                        port = default_port

                    scope["server"] = (host_part, port)

                    # Replace the ``host`` header so Starlette sees the proxy host.
                    new_headers: list[tuple[bytes, bytes]] = [(name, value) for name, value in scope["headers"] if name != b"host"]  # type: ignore[union-attr]
                    new_headers.append((b"host", x_forwarded_host.encode("latin1")))
                    scope["headers"] = new_headers  # type: ignore[typeddict-item]

        return await self.app(scope, receive, send)
