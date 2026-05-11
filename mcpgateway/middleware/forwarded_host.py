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

Register this middleware **before** ``ProxyHeadersMiddleware`` in the
``add_middleware`` stack (which means it is inner / executes **after**
``ProxyHeadersMiddleware`` in the ASGI call chain, ensuring the scheme is
already corrected when we derive the default port for ``scope["server"]``).

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
from typing import Any, Awaitable, Callable, MutableMapping

logger = logging.getLogger(__name__)


def _parse_forwarded_host(value: str, scheme: str) -> tuple[str, int, str] | None:
    """Parse an X-Forwarded-Host value into (server_host, port, host_header_value).

    Returns *None* if the value is malformed or the port is out of range.

    * ``server_host`` is the unbracketed host literal for ``scope["server"]``.
    * ``host_header_value`` is the full host (with port if present) for the
      rewritten HTTP ``Host`` header.

    Handles:
    * Plain hostnames: ``proxy.example.com``
    * Host:port: ``proxy.example.com:8443``
    * Bracketed IPv6: ``[2001:db8::1]``
    * Bracketed IPv6 with port: ``[2001:db8::1]:8080``
    * Unbracketed IPv6 without port: ``2001:db8::1``
    * Comma-separated list (only the first value is used)
    """
    # Take only the first value if comma-separated (leftmost = client-facing hop).
    host_value = value.split(",", 1)[0].strip()
    if not host_value:
        return None

    # Reject obviously invalid characters in the host portion.
    if " " in host_value or "\t" in host_value or "\n" in host_value or "\r" in host_value:
        logger.debug("Ignoring X-Forwarded-Host with whitespace characters: %r", host_value)
        return None

    default_port = 443 if scheme in ("https", "wss") else 80

    # Bracketed IPv6 – may include a trailing port.
    if host_value.startswith("["):
        if "]:" in host_value:
            bracketed, _colon, port_str = host_value.rpartition(":")
            if not bracketed.endswith("]"):
                # e.g. "[::1]junk:8080" – malformed
                logger.debug("Ignoring malformed bracketed IPv6: %r", host_value)
                return None
            if not port_str.isdigit():
                logger.debug("Ignoring X-Forwarded-Host with invalid port: %r", host_value)
                return None
            port = int(port_str)
            server_host = bracketed[1:-1]  # strip brackets
        else:
            if not host_value.endswith("]"):
                logger.debug("Ignoring malformed bracketed IPv6: %r", host_value)
                return None
            server_host = host_value[1:-1]  # strip brackets
            port = default_port
    elif ":" in host_value:
        # Could be host:port or unbracketed IPv6.
        # Unbracketed IPv6 has more than one colon and no port suffix.
        if host_value.count(":") > 1:
            server_host = host_value
            port = default_port
        else:
            server_host, port_str = host_value.rsplit(":", 1)
            if not port_str.isdigit():
                logger.debug("Ignoring X-Forwarded-Host with invalid port: %r", host_value)
                return None
            port = int(port_str)
    else:
        server_host = host_value
        port = default_port

    # Validate port range.
    if not 1 <= port <= 65535:
        logger.debug("Ignoring X-Forwarded-Host with out-of-range port: %r", host_value)
        return None

    # Reject paths or other invalid host syntax, and empty hosts.
    if not server_host or "/" in server_host:
        logger.debug("Ignoring X-Forwarded-Host with empty or invalid host: %r", host_value)
        return None

    return server_host, port, host_value


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

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        """Initialise middleware with the inner ASGI app."""
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        """Rewrite host header from X-Forwarded-Host if present."""
        if scope["type"] in ("http", "websocket"):
            # Use the first occurrence of X-Forwarded-Host (leftmost = client-facing hop).
            raw = next(
                (v.decode("latin1") for k, v in scope["headers"] if k == b"x-forwarded-host"),
                None,
            )

            if raw is not None:
                parsed = _parse_forwarded_host(raw, scope.get("scheme", "http"))
                if parsed is not None:
                    server_host, port, host_header_value = parsed

                    scope["server"] = (server_host, port)

                    # Replace the ``host`` header so Starlette sees the proxy host.
                    new_headers: list[tuple[bytes, bytes]] = [
                        (name, value) for name, value in scope["headers"] if name != b"host"
                    ]
                    new_headers.append((b"host", host_header_value.encode("latin1")))
                    scope["headers"] = new_headers

        return await self.app(scope, receive, send)
