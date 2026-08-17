# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/mcp_v2_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Small MCP SDK v2 compatibility helpers used during the migration.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Optional

# Third-Party
import httpx2 as httpx
import mcp
from mcp.client import streamable_http as mcp_streamable_http
from mcp.shared import exceptions as mcp_exceptions
from mcp.shared._httpx_utils import create_mcp_http_client, McpHttpClientFactory


def install_mcp_v2_cpex_compat() -> None:
    """Install temporary MCP v1 aliases expected by current CPEX releases.

    TODO(#6219): remove this once CPEX imports ``MCPError`` and
    ``streamable_http_client`` directly and declares MCP v2 support.
    """
    if not hasattr(mcp, "McpError") and hasattr(mcp, "MCPError"):
        mcp.McpError = mcp.MCPError  # type: ignore[attr-defined]
    if not hasattr(mcp_exceptions, "McpError") and hasattr(mcp_exceptions, "MCPError"):
        mcp_exceptions.McpError = mcp_exceptions.MCPError  # type: ignore[attr-defined]
    if not hasattr(mcp_streamable_http, "streamablehttp_client") and hasattr(mcp_streamable_http, "streamable_http_client"):
        mcp_streamable_http.streamablehttp_client = mcp_streamable_http.streamable_http_client  # type: ignore[attr-defined]


def _coerce_timeout(timeout: float | httpx.Timeout | None) -> httpx.Timeout | None:
    """Return an ``httpx2.Timeout`` for numeric timeout values."""
    if timeout is None or isinstance(timeout, httpx.Timeout):
        return timeout
    return httpx.Timeout(timeout)


@asynccontextmanager
async def streamablehttp_client(
    url: str,
    headers: Optional[Mapping[str, Any]] = None,
    timeout: float | httpx.Timeout | None = None,
    *,
    httpx_client_factory: Optional[McpHttpClientFactory] = None,
    auth: Optional[httpx.Auth] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    terminate_on_close: bool = True,
) -> AsyncIterator[tuple[Any, Any, None]]:
    """Compatibility wrapper for MCP v2 ``streamable_http_client``.

    MCP v2 moved ``headers``/``timeout``/``auth`` configuration onto a caller
    supplied ``httpx2.AsyncClient`` and changed the yielded transport from three
    values to two. This wrapper preserves the gateway's MCP v1 call shape while
    the broader streamable HTTP migration is split across follow-up work.
    """
    if http_client is not None:
        async with mcp_streamable_http.streamable_http_client(url, http_client=http_client, terminate_on_close=terminate_on_close) as streams:
            yield streams[0], streams[1], None
        return

    factory = httpx_client_factory or create_mcp_http_client
    timeout_arg = _coerce_timeout(timeout)
    headers_arg = dict(headers) if headers is not None else None

    async with factory(headers=headers_arg, timeout=timeout_arg, auth=auth) as client:
        async with mcp_streamable_http.streamable_http_client(url, http_client=client, terminate_on_close=terminate_on_close) as streams:
            yield streams[0], streams[1], None
