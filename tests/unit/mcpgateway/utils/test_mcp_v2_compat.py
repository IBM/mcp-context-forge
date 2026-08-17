# -*- coding: utf-8 -*-
"""Unit tests for MCP SDK v2 compatibility helpers."""

# Future
from __future__ import annotations

# Standard
from contextlib import asynccontextmanager

# Third-Party
import httpx2 as httpx
import pytest

# First-Party
from mcpgateway.utils.mcp_v2_compat import install_mcp_v2_cpex_compat, streamablehttp_client


def test_install_mcp_v2_cpex_compat_installs_expected_aliases():
    """CPEX can import its MCP v1-era names after the explicit initializer runs."""
    # Third-Party
    import mcp
    from mcp.client import streamable_http
    from mcp.shared import exceptions as mcp_exceptions

    install_mcp_v2_cpex_compat()

    assert mcp.McpError is mcp.MCPError
    assert mcp_exceptions.McpError is mcp_exceptions.MCPError
    assert streamable_http.streamablehttp_client is streamable_http.streamable_http_client

    # Third-Party
    from cpex.framework import GlobalContext

    assert GlobalContext.__name__ == "GlobalContext"


@pytest.mark.asyncio
async def test_streamablehttp_client_preserves_v1_call_shape(monkeypatch):
    """Old kwargs are moved onto an httpx2 client and the wrapper yields three values."""
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        """Minimal async context manager returned by the factory."""

        async def __aenter__(self):
            captured["factory_entered"] = True
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            captured["factory_exited"] = True

    def fake_factory(headers=None, timeout=None, auth=None):
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["auth"] = auth
        return FakeAsyncClient()

    @asynccontextmanager
    async def fake_sdk_streamable_client(url, *, http_client=None, terminate_on_close=True):
        captured["url"] = url
        captured["http_client"] = http_client
        captured["terminate_on_close"] = terminate_on_close
        yield "read-stream", "write-stream"

    monkeypatch.setattr("mcpgateway.utils.mcp_v2_compat.mcp_streamable_http.streamable_http_client", fake_sdk_streamable_client)

    async with streamablehttp_client(
        "https://upstream.example/mcp",
        headers={"Authorization": "Bearer token"},
        timeout=7.5,
        httpx_client_factory=fake_factory,
        terminate_on_close=False,
    ) as streams:
        assert streams == ("read-stream", "write-stream", None)

    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["auth"] is None
    assert captured["url"] == "https://upstream.example/mcp"
    assert isinstance(captured["http_client"], FakeAsyncClient)
    assert captured["terminate_on_close"] is False
    assert captured["factory_entered"] is True
    assert captured["factory_exited"] is True
