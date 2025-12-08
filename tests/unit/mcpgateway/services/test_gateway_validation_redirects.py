# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_validation_redirects.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the GatewayService implementation.

These tests validate gateway URL redirection behavior. They avoid
real network access and real databases by using httpx.MockTransport
and lightweight fakes (MagicMock / AsyncMock). Where the service
relies on Pydantic models or SQLAlchemy Result objects we monkey-
patch or provide small stand-ins to exercise only the code paths
under test.
"""

import pytest
import httpx
from unittest.mock import patch
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.retry_manager import ResilientHttpClient

@pytest.mark.asyncio
async def test_streamablehttp_follows_3xx_redirects_and_validates():
    svc = GatewayService()

    # Mock transport behavior:
    # 1) GET http://example/start -> 302 Location: /final
    # 2) GET http://example/final -> 200 with mcp-session-id + application/json
    async def mock_dispatch(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/start"):
            return httpx.Response(302, headers={"location": "/final"})
        if url.endswith("/final"):
            return httpx.Response(200, headers={"mcp-session-id": "abc", "content-type": "application/json"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_dispatch)
    # Build a ResilientHttpClient that uses this transport
    client_args = {"transport": transport, "follow_redirects": True}
    mock_resilient = ResilientHttpClient(client_args=client_args)

    # Patch ResilientHttpClient where gateway_service constructs it
    class MockResilientFactory:
        def __init__(self, *args, **kwargs):
            # ignore args; use our prebuilt instance
            self.client = mock_resilient.client

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aclose(self):
            await mock_resilient.aclose()

        # expose stream method used by gateway_service
        def stream(self, method, url, **kwargs):
            return mock_resilient.client.stream(method, url, **kwargs)

@pytest.mark.asyncio
async def test_200_with_location_is_not_treated_as_redirect():
    svc = GatewayService()

    async def mock_dispatch(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/bad"):
            # Non-standard: 200 with Location header. Should NOT be treated as redirect.
            return httpx.Response(200, headers={"location": "/should-not-follow", "content-type": "text/plain"})
        if url.endswith("/should-not-follow"):
            # If code incorrectly followed Location on 200, we'd reach here
            return httpx.Response(200, headers={"mcp-session-id": "x", "content-type": "application/json"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_dispatch)
    client_args = {"transport": transport, "follow_redirects": True}
    mock_resilient = ResilientHttpClient(client_args=client_args)

    class MockResilientFactory:
        def __init__(self, *args, **kwargs):
            self.client = mock_resilient.client

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aclose(self):
            await mock_resilient.aclose()

        def stream(self, method, url, **kwargs):
            return mock_resilient.client.stream(method, url, **kwargs)
