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
from typing import Any, Callable, Literal, Optional

# Third-Party
import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp_types import CLIENT_CAPABILITIES_META_KEY

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.streamable_http_compat import ErrorResponseHook

logger = logging.getLogger(__name__)

__all__ = ["keep_caller_capabilities", "mcp_proxy_client"]

# Third-Party
# Re-export for use by transport code that still references streamable_http_client
# from the SDK directly when needed.
from mcp.client.streamable_http import streamable_http_client  # noqa: E402  # SDK-only re-export for this module.


# Capabilities the gateway carries upstream on the caller's behalf: the three kinds of
# question a 2026 upstream can ask through an ``input_required`` result, which the gateway
# relays to the end client untouched. Extensions stay out: they can change result shapes
# that this client still has to parse itself.
_RELAYED_CAPABILITY_KEYS = ("elicitation", "sampling", "roots")


def _relayed_capabilities(params: Any) -> Optional[dict[str, Any]]:
    """Return the slice of the caller's declared capabilities that the gateway relays.

    Args:
        params: Serialized request params, possibly carrying the caller's ``_meta``.

    Returns:
        The caller's relayable capabilities, or ``None`` when the caller declared none.
    """
    meta = params.get("_meta") if isinstance(params, dict) else None
    declared = meta.get(CLIENT_CAPABILITIES_META_KEY) if isinstance(meta, dict) else None
    if not isinstance(declared, dict):
        return None
    return {key: value for key, value in declared.items() if key in _RELAYED_CAPABILITY_KEYS}


def keep_caller_capabilities(client: Client) -> None:
    """Make ``client`` advertise the caller's capabilities upstream instead of its own.

    Requests that carry no caller-declared capabilities (legacy callers) and legacy
    upstreams (whose handshake stamp writes no capabilities key) are left untouched.

    Args:
        client: A connected ``mcp.Client``.
    """
    session = client.session
    sdk_stamp = session._stamp  # pylint: disable=protected-access

    def stamp(data: dict[str, Any], opts: Any) -> None:
        """Run the SDK stamp, then restore the caller's relayable capabilities.

        Args:
            data: The serialized request about to be sent.
            opts: The SDK's per-call options, passed through untouched.
        """
        caller = _relayed_capabilities(data.get("params"))
        sdk_stamp(data, opts)
        meta = (data.get("params") or {}).get("_meta")
        if caller is not None and isinstance(meta, dict) and CLIENT_CAPABILITIES_META_KEY in meta:
            meta[CLIENT_CAPABILITIES_META_KEY] = caller

    session._stamp = stamp  # pylint: disable=protected-access


@contextlib.asynccontextmanager
async def mcp_proxy_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    httpx_client_factory: Callable[..., httpx2.AsyncClient] | None = None,
    transport: Literal["streamablehttp", "sse"] = "streamablehttp",
    mode: str | None = None,
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
        mode: MCP connect mode passed to ``Client``.  ``None`` (default)
            resolves to ``settings.mcp_client_connect_mode``.

    Yields:
        An ``mcp.Client`` instance with an established transport.

    Raises:
        RuntimeError: If the transport initialization fails.
    """
    resolved_mode = settings.mcp_client_connect_mode if mode is None else mode

    if transport == "sse":
        # sse_client owns its httpx client lifecycle internally.
        if httpx_client_factory is not None:
            sse_acm = sse_client(url, headers=headers, timeout=timeout, httpx_client_factory=httpx_client_factory)
        else:
            sse_acm = sse_client(url, headers=headers, timeout=timeout)
        async with Client(sse_acm, mode=resolved_mode) as client:
            keep_caller_capabilities(client)
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

    error_hook = ErrorResponseHook().install(http_client)
    async with http_client:
        # SDK b1: Client takes the transport context manager directly.
        # It owns the transport lifecycle and performs auto-initialization.
        transport_acm = streamable_http_client(url, http_client=http_client)
        try:
            async with Client(transport_acm, mode=resolved_mode) as client:
                keep_caller_capabilities(client)
                yield client
        except BaseException as exc:  # noqa: BLE001 — re-raised below unless translated
            # an error the SDK made up stands for a transport failure: surface that instead
            transport_error = error_hook.to_transport_error(exc)
            if transport_error is None:
                raise
            raise transport_error from exc
