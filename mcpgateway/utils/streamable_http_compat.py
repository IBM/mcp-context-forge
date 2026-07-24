# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/streamable_http_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Backwards-compat wrapper for the mcp v1→v2 streamable HTTP client transition.

The v1 ``streamable_http_client(url, headers=, timeout=, httpx_client_factory=)``
function was removed in mcp 2.x in favor of
``streamable_http_client(url, http_client=)`` where headers/timeout/auth are
configured on the supplied ``httpx.AsyncClient``. The v2 function also returns
a 2-tuple ``(read_stream, write_stream)`` instead of v1's 3-tuple
``(read_stream, write_stream, get_session_id)``.

This shim preserves the v1 keyword arguments so call sites only need to:

1. Switch the import:
   ``from mcpgateway.utils.streamable_http_compat import streamable_http_client``
2. Drop the third tuple element from ``async with ... as (r, w, _gsid):`` to
   ``as (r, w):``.

If a call site needs the session id (none in mcpgateway do — every existing
site destructures the third element to ``_get_session_id``), capture it via
an httpx event hook instead, per the migration guide.
"""

from __future__ import annotations

# Standard
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

# Third-Party
import httpx
from mcp.client.streamable_http import streamable_http_client as _sdk_streamable_http_client


@asynccontextmanager
async def streamable_http_client(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    httpx_client_factory: Callable[..., httpx.AsyncClient] | None = None,
) -> AsyncIterator[Any]:
    """Yield ``(read_stream, write_stream)`` from the mcp 2.x streamable transport.

    Preserves the v1 keyword surface (``headers``/``timeout``/``auth``/
    ``httpx_client_factory``) by routing all configuration onto an
    ``httpx.AsyncClient`` before delegating to ``streamable_http_client``.

    Args:
        url: MCP server endpoint URL.
        headers: Optional HTTP headers applied to the underlying ``httpx.AsyncClient``.
        timeout: Optional timeout in seconds OR a pre-built ``httpx.Timeout``.
        auth: Optional httpx auth helper (e.g. for bearer tokens).
        httpx_client_factory: Optional factory returning a configured
            ``httpx.AsyncClient``. When supplied, ``headers``/``timeout``/``auth``
            are forwarded as keyword arguments to the factory; otherwise a fresh
            ``httpx.AsyncClient`` is created here with ``follow_redirects=True``
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
            kwargs["timeout"] = timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
        if auth is not None:
            kwargs["auth"] = auth
        http_client = httpx.AsyncClient(**kwargs)

    async with http_client:
        async with _sdk_streamable_http_client(url=url, http_client=http_client) as streams:
            yield streams
