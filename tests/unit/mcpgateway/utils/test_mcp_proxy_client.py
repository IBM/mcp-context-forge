# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_mcp_proxy_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project.
SPDX-License-Identifier: Apache-2.0

Unit tests for ``mcpgateway.utils.mcp_proxy_client``.

All transports are mocked at the module-under-test boundary — no network,
no live handshake.  ``sse_client`` is patched with a plain Mock returning a
mock async context manager because the real SDK function is an
``@asynccontextmanager`` that performs HTTP on entry.

Run:
    uv run --extra runtime pytest tests/unit/mcpgateway/utils/test_mcp_proxy_client.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcpgateway.config import settings
from mcpgateway.utils.mcp_proxy_client import mcp_proxy_client

_URL = "http://upstream.example.com/mcp"
_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_default_transport_is_streamablehttp_and_mode_comes_from_settings() -> None:
    """Given no transport/mode arguments, when the client is built, then the
    streamable-http ACM is used and Client receives
    ``settings.mcp_client_connect_mode``."""
    client_cls = MagicMock(name="Client")
    transport_acm = MagicMock(name="streamable_http_acm")

    with (
        patch("mcpgateway.utils.mcp_proxy_client.streamable_http_client", return_value=transport_acm) as shc,
        patch("mcpgateway.utils.mcp_proxy_client.Client", client_cls),
    ):
        async with mcp_proxy_client(_URL, headers=_HEADERS) as client:
            assert client is client_cls.return_value.__aenter__.return_value

    shc.assert_called_once()
    assert shc.call_args.args[0] == _URL
    assert "http_client" in shc.call_args.kwargs
    client_cls.assert_called_once()
    assert client_cls.call_args.args[0] is transport_acm
    assert client_cls.call_args.kwargs["mode"] == settings.mcp_client_connect_mode


@pytest.mark.asyncio
async def test_explicit_mode_is_threaded_into_client() -> None:
    """Given mode="legacy", when the client is built, then Client receives
    mode="legacy" instead of the settings default."""
    client_cls = MagicMock(name="Client")

    with (
        patch("mcpgateway.utils.mcp_proxy_client.streamable_http_client", return_value=MagicMock()),
        patch("mcpgateway.utils.mcp_proxy_client.Client", client_cls),
    ):
        async with mcp_proxy_client(_URL, mode="legacy"):
            pass

    client_cls.assert_called_once()
    assert client_cls.call_args.kwargs["mode"] == "legacy"


@pytest.mark.asyncio
async def test_sse_transport_builds_client_from_sse_client() -> None:
    """Given transport="sse", when the client is built, then sse_client is
    called with the url and headers, its ACM is handed to Client, and the
    streamable-http path is not touched."""
    client_cls = MagicMock(name="Client")
    sse_acm = MagicMock(name="sse_acm")

    with (
        patch("mcpgateway.utils.mcp_proxy_client.sse_client", return_value=sse_acm) as sse_mock,
        patch("mcpgateway.utils.mcp_proxy_client.streamable_http_client") as shc,
        patch("mcpgateway.utils.mcp_proxy_client.Client", client_cls),
    ):
        async with mcp_proxy_client(_URL, headers=_HEADERS, transport="sse"):
            pass

    sse_mock.assert_called_once()
    assert sse_mock.call_args.args[0] == _URL
    assert sse_mock.call_args.kwargs["headers"] == _HEADERS
    shc.assert_not_called()
    client_cls.assert_called_once()
    assert client_cls.call_args.args[0] is sse_acm
    assert client_cls.call_args.kwargs["mode"] == settings.mcp_client_connect_mode


@pytest.mark.asyncio
async def test_explicit_streamablehttp_transport_matches_default_path() -> None:
    """Given transport="streamablehttp" explicitly, when the client is built,
    then the streamable-http path is used and sse_client is not touched."""
    client_cls = MagicMock(name="Client")
    transport_acm = MagicMock(name="streamable_http_acm")

    with (
        patch("mcpgateway.utils.mcp_proxy_client.streamable_http_client", return_value=transport_acm) as shc,
        patch("mcpgateway.utils.mcp_proxy_client.sse_client") as sse_mock,
        patch("mcpgateway.utils.mcp_proxy_client.Client", client_cls),
    ):
        async with mcp_proxy_client(_URL, transport="streamablehttp"):
            pass

    shc.assert_called_once()
    sse_mock.assert_not_called()
    client_cls.assert_called_once()
    assert client_cls.call_args.args[0] is transport_acm


@pytest.mark.asyncio
async def test_default_factory_path_constructs_valid_four_param_timeout() -> None:
    """Given no httpx_client_factory, when the client is built, then the
    default httpx2.AsyncClient is constructed with a fully-specified
    four-parameter httpx2.Timeout (httpx2 rejects partial Timeouts)."""
    client_cls = MagicMock(name="Client")
    transport_acm = MagicMock(name="streamable_http_acm")

    with (
        patch("mcpgateway.utils.mcp_proxy_client.streamable_http_client", return_value=transport_acm) as shc,
        patch("mcpgateway.utils.mcp_proxy_client.Client", client_cls),
    ):
        async with mcp_proxy_client(_URL, timeout=30.0):
            pass

    shc.assert_called_once()
    http_client = shc.call_args.kwargs["http_client"]
    timeout = http_client.timeout
    assert timeout.connect == 10.0  # min(30.0, 10.0)
    assert timeout.read == 30.0  # max(30.0, 30.0)
    assert timeout.write == settings.httpx_write_timeout
    assert timeout.pool == settings.httpx_pool_timeout
