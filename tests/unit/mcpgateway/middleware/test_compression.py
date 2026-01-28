# -*- coding: utf-8 -*-
"""Tests for SSE-aware compression middleware."""

# Third-Party
import pytest
from unittest.mock import AsyncMock

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.compression import SSEAwareCompressMiddleware


@pytest.mark.asyncio
async def test_non_http_goes_through_compress_app():
    app = AsyncMock()
    middleware = SSEAwareCompressMiddleware(app)
    middleware.compress_app = AsyncMock()

    scope = {"type": "websocket"}
    await middleware(scope, AsyncMock(), AsyncMock())

    middleware.compress_app.assert_awaited_once()
    app.assert_not_called()


@pytest.mark.asyncio
async def test_sse_mode_bypasses_compression(monkeypatch: pytest.MonkeyPatch):
    app = AsyncMock()
    middleware = SSEAwareCompressMiddleware(app)
    middleware.compress_app = AsyncMock()

    monkeypatch.setattr(settings, "json_response_enabled", False)

    scope = {"type": "http", "path": "/mcp"}
    await middleware(scope, AsyncMock(), AsyncMock())

    app.assert_awaited_once()
    middleware.compress_app.assert_not_called()


@pytest.mark.asyncio
async def test_json_mode_uses_compression(monkeypatch: pytest.MonkeyPatch):
    app = AsyncMock()
    middleware = SSEAwareCompressMiddleware(app)
    middleware.compress_app = AsyncMock()

    monkeypatch.setattr(settings, "json_response_enabled", True)

    scope = {"type": "http", "path": "/mcp"}
    await middleware(scope, AsyncMock(), AsyncMock())

    middleware.compress_app.assert_awaited_once()
    app.assert_not_called()


def test_is_mcp_path_variants():
    app = AsyncMock()
    middleware = SSEAwareCompressMiddleware(app)

    assert middleware._is_mcp_path("/mcp") is True
    assert middleware._is_mcp_path("/mcp/") is True
    assert middleware._is_mcp_path("/servers/123/mcp") is True
    assert middleware._is_mcp_path("/servers/123/mcp/") is True
    assert middleware._is_mcp_path("/tools") is False
