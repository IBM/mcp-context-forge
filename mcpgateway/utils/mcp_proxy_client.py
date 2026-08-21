# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/mcp_proxy_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

MCP v2 proxy client for direct-proxy calls.

Replaces the old ``streamable_http_client`` + ``ClientSession`` pattern with
the MCP v2 ``Client`` class.

Usage::

    async with mcp_proxy_client(url, headers, timeout) as client:
        tools = await client.list_tools(meta=meta)
        resources = await client.list_resources()
        result = await client.read_resource(uri, meta=meta)
        result = await client.call_tool(name, arguments, meta=meta)

    # Legacy SSE upstream:
    async with mcp_proxy_client(url, headers, transport="sse") as client:
        tools = await client.list_tools()
"""

# Future
from __future__ import annotations

# Standard
import contextlib
import logging
from typing import Callable, Literal

# Third-Party
import httpx2
from mcp import Client
from mcp.client.sse import sse_client

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

__all__ = ["mcp_proxy_client"]

# Third-Party
# Use the SDK v2 transport with the project-configured httpx2 client.
from mcp.client.streamable_http import streamable_http_client  # noqa: E402  # SDK-only import for this module.


@contextlib.asynccontextmanager
async def mcp_proxy_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    httpx_client_factory: Callable[..., httpx2.AsyncClient] | None = None,
    transport: Literal["streamablehttp", "sse"] = "streamablehttp",

) -> "Client":  # type: ignore[misc]
    """Yield an MCP v2 ``Client`` connected via streamable-http transport.

    The ``Client`` auto-initializes (via ``initialize()`` or auto-negotiation)
    before ``yield`` returns.  No manual ``session.initialize()`` call needed.

    The underlying ``httpx2.AsyncClient`` stays alive for the transport's
    lifetime because the transport holds a reference to it.

    Args:
        url: Gateway or server URL to connect to.
        headers: HTTP headers to include in the request.
        timeout: Overall timeout for operations (passed through to factory).
        httpx_client_factory: Optional callable returning a configured
            ``httpx2.AsyncClient``.  Receives keyword args
            ``(headers, timeout, auth)`` matching the compat wrapper.
        transport: Upstream transport — ``"streamablehttp"`` (default) or
            ``"sse"`` for legacy SSE-only servers.


    Yields:
        An ``mcp.Client`` instance with an established transport.

    Raises:
        RuntimeError: If the transport initialization fails.
    """

    if transport == "sse":
        # sse_client owns its httpx client lifecycle internally.
        if httpx_client_factory is not None:
            sse_acm = sse_client(url, headers=headers, timeout=timeout, httpx_client_factory=httpx_client_factory)
        else:
            sse_acm = sse_client(url, headers=headers, timeout=timeout)
        async with Client(sse_acm) as client:
            yield client
        return

    if httpx_client_factory is not None:
        try:
            http_client = httpx_client_factory(headers=headers, timeout=timeout, auth=None)
        except Exception as exc:
            raise RuntimeError(f"Failed to create httpx2.AsyncClient: {exc}") from exc
    else:
        # Use sensible timeout defaults for MCP transport.
        # Connect: keep short to fail fast.  Read: must cover the full RPC.
        connect_timeout = min(timeout, 10.0)
        read_timeout = max(timeout, 30.0)
        http_client = httpx2.AsyncClient(
            headers=headers or {},
            timeout=httpx2.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=settings.httpx_write_timeout,
                pool=settings.httpx_pool_timeout,
            ),
        )

    async with http_client:
        # MCP v2 Client owns the transport lifecycle and auto-initializes.
        transport_acm = streamable_http_client(url, http_client=http_client)
        async with Client(transport_acm) as client:
            yield client
