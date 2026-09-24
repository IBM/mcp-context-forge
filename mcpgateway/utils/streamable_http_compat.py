# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/streamable_http_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Backwards-compat wrapper for the mcp v1→v2 streamable HTTP client transition.

The v1 ``streamable_http_client(url, headers=, timeout=, httpx_client_factory=)``
function was removed in mcp 2.x in favor of
``streamable_http_client(url, http_client=)`` where headers/timeout/auth are
configured on the supplied ``httpx2.AsyncClient``. The v2 function also returns
a 2-tuple ``(read_stream, write_stream)`` instead of v1's 3-tuple
``(read_stream, write_stream, get_session_id)``.

This shim preserves the v1 keyword arguments so call sites only need to:

1. Switch the import:
   ``from mcpgateway.utils.streamable_http_compat import streamable_http_client``
2. Drop the third tuple element from ``async with ... as (r, w, _gsid):`` to
   ``as (r, w):``.

If a call site needs the session id (none in mcpgateway do — every existing
site destructures the third element to ``_get_session_id``), capture it via
an httpx2 event hook instead, per the migration guide.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional

# Third-Party
import httpx2
from mcp.client.streamable_http import streamable_http_client as _sdk_streamable_http_client
from mcp.shared.exceptions import MCPError


class ErrorResponseHook:
    """
    Keeps the last POST response seen on an httpx2 client, because the
    mcp 2.x transport drops the HTTP status when a handshake or call fails.
    Only POST carries JSON-RPC; the transport's GET stream and DELETE on close
    may get a tolerated 405, so their responses are ignored.
    """

    def __init__(self) -> None:
        """Start with no response."""
        self.response: Optional[httpx2.Response] = None

    def install(self, http_client: httpx2.AsyncClient) -> "ErrorResponseHook":
        """Register the response hook on ``http_client`` and return self"""
        http_client.event_hooks.setdefault("response", []).append(self._get_error)
        return self

    async def _get_error(self, response: httpx2.Response) -> None:
        """Keep ``response`` if it answers a POST, whatever its status"""
        if response.request.method == "POST":
            self.response = response

    def to_http_status_error(self, exc: BaseException) -> Optional[httpx2.HTTPStatusError]:
        """Translate a failed handshake into an ``httpx2.HTTPStatusError``"""
        response = self.response
        if response is None or response.status_code < 400:
            return None
        root: BaseException = exc
        while isinstance(root, BaseExceptionGroup) and root.exceptions:  # pylint: disable=no-member
            root = root.exceptions[0]  # pylint: disable=no-member
        if not isinstance(root, MCPError):
            return None
        return httpx2.HTTPStatusError(
            f"{response.status_code} {response.reason_phrase} for url '{response.request.url}'",
            request=response.request,
            response=response,
        )


@asynccontextmanager
async def streamable_http_client(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    httpx_client_factory: Callable[..., httpx2.AsyncClient] | None = None,
) -> AsyncIterator[Any]:
    """Yield ``(read_stream, write_stream)`` from the mcp 2.x streamable transport.

    Preserves the v1 keyword surface (``headers``/``timeout``/``auth``/
    ``httpx_client_factory``) by routing all configuration onto an
    ``httpx2.AsyncClient`` before delegating to ``streamable_http_client``.

    Args:
        url: MCP server endpoint URL.
        headers: Optional HTTP headers applied to the underlying ``httpx2.AsyncClient``.
        timeout: Optional timeout in seconds OR a pre-built ``httpx2.Timeout``.
        auth: Optional httpx2 auth helper (e.g. for bearer tokens).
        httpx_client_factory: Optional factory returning a configured
            ``httpx2.AsyncClient``. When supplied, ``headers``/``timeout``/``auth``
            are forwarded as keyword arguments to the factory; otherwise a fresh
            ``httpx2.AsyncClient`` is created here with ``follow_redirects=True``
            (matching v1's internal client behavior).

    Yields:
        2-tuple of ``(read_stream, write_stream)``.
    """
    if httpx_client_factory is not None:
        http_client = httpx_client_factory(headers=headers, timeout=timeout, auth=auth)
    else:
        kwargs: dict[str, Any] = {"follow_redirects": True}
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout if isinstance(timeout, httpx2.Timeout) else httpx2.Timeout(timeout)
        if auth is not None:
            kwargs["auth"] = auth
        http_client = httpx2.AsyncClient(**kwargs)

    error_hook = ErrorResponseHook().install(http_client)
    async with http_client:
        try:
            async with _sdk_streamable_http_client(url=url, http_client=http_client) as streams:
                yield streams
        except BaseException as exc:  # noqa: BLE001 — re-raised below unless translated
            # upstream error status surfaced as httpx2.HTTPStatusError
            status_error = error_hook.to_http_status_error(exc)
            if status_error is None:
                raise
            raise status_error from exc
