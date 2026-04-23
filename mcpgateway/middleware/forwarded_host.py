# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/forwarded_host.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Forwarded Host Middleware.

Rewrites the ASGI ``host`` header and ``scope["server"]`` tuple from the
``X-Forwarded-Host`` header when the request originates from a trusted proxy.

Uvicorn's ``ProxyHeadersMiddleware`` handles ``X-Forwarded-Proto`` (scheme)
and ``X-Forwarded-For`` (client IP) but does **not** handle
``X-Forwarded-Host`` (upstream issue encode/uvicorn#965, open PR #2811).

This middleware fills that gap so that ``request.base_url`` (used in admin UI
hints, OAuth redirect_uri display, well-known URLs, etc.) reflects the
proxy's public host rather than the gateway's internal address.

Register this middleware **after** ``ProxyHeadersMiddleware`` in the
``add_middleware`` stack (which means it executes **before** it in the ASGI
call chain, ensuring the scheme is already corrected when we derive the
default port).

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

    Only acts when ``trusted_hosts="*"`` (trust all proxies).  Per-IP trust
    checking is not implemented — for non-wildcard values the middleware is a
    no-op.  This is intentional: the gateway registers both this and
    ``ProxyHeadersMiddleware`` with ``trusted_hosts="*"`` via a shared variable,
    and this middleware is temporary until Uvicorn merges upstream support.

    Default port values (80 for http/ws, 443 for https/wss) follow RFC 2616
    and match the convention in Uvicorn PR #2811.  They populate
    ``scope["server"]`` only when the ``X-Forwarded-Host`` header omits a port.
    """

    def __init__(
        self,
        app: ASGI3Application,
        trusted_hosts: list[str] | str = "127.0.0.1",
    ) -> None:
        """Initialise middleware with the inner ASGI app and trusted hosts."""
        self.app = app
        if isinstance(trusted_hosts, str):
            self.always_trust = trusted_hosts == "*"
        else:
            self.always_trust = trusted_hosts == ["*"]

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        """Rewrite host header from X-Forwarded-Host if present and trusted."""
        if scope["type"] in ("http", "websocket") and self.always_trust:
            headers = dict(scope["headers"])  # type: ignore[arg-type]

            if b"x-forwarded-host" in headers:
                raw = headers[b"x-forwarded-host"].decode("latin1")
                # Take only the first value if comma-separated (leftmost =
                # client-facing hop).
                x_forwarded_host = raw.split(",")[0].strip()

                if x_forwarded_host:
                    # Determine default port from the (already-corrected) scheme.
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
