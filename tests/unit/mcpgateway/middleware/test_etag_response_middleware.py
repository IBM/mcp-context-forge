# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_etag_response_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Unit tests for ETag response middleware.

Examples:
    >>> pytest tests/unit/mcpgateway/middleware/test_etag_response_middleware.py -v  # doctest: +SKIP
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import JSONResponse, Response


class TestETagResponseMiddleware:
    """Test ETag response middleware."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for tests."""
        with patch("mcpgateway.middleware.etag_response_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            yield mock

    @pytest.fixture
    def middleware(self, mock_settings):
        """Create middleware instance for testing."""
        from mcpgateway.middleware.etag_response_middleware import ETagResponseMiddleware

        return ETagResponseMiddleware(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock HTTP request."""
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/servers/abc123"
        return request

    @pytest.mark.asyncio
    async def test_middleware_disabled_does_not_add_etag(self, middleware, mock_request):
        """Test that disabled middleware doesn't add ETag headers."""
        middleware.enabled = False

        response_data = {"id": "abc123", "name": "Test Server", "version": 5}
        mock_response = JSONResponse(response_data)

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_get_request_adds_etag_header(self, middleware, mock_request):
        """Test that GET request for versioned resource gets ETag header."""
        response_data = {"id": "abc123", "name": "Test Server", "version": 5}

        # Create response with proper body iterator
        async def body_generator():
            yield json.dumps(response_data).encode()

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"abc123-5"'

    @pytest.mark.asyncio
    async def test_post_request_does_not_add_etag(self, middleware, mock_request):
        """Test that POST requests don't get ETag headers."""
        mock_request.method = "POST"

        response_data = {"id": "abc123", "version": 5}
        mock_response = JSONResponse(response_data)

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # ETag not added for non-GET requests
        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_put_request_does_not_add_etag(self, middleware, mock_request):
        """Test that PUT requests don't get ETag headers."""
        mock_request.method = "PUT"

        response_data = {"id": "abc123", "version": 5}
        mock_response = JSONResponse(response_data)

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_404_response_does_not_add_etag(self, middleware, mock_request):
        """Test that error responses don't get ETag headers."""
        response_data = {"error": "Not Found"}
        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=404,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_non_versioned_path_does_not_add_etag(self, middleware, mock_request):
        """Test that non-versioned paths don't get ETag headers."""
        mock_request.url.path = "/health"

        response_data = {"status": "healthy"}
        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_response_without_version_does_not_add_etag(self, middleware, mock_request):
        """Test that responses without version field don't get ETag."""
        response_data = {"id": "abc123", "name": "Test Server"}  # No version field

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_response_without_id_does_not_add_etag(self, middleware, mock_request):
        """Test that responses without id field don't get ETag."""
        response_data = {"name": "Test Server", "version": 5}  # No id field

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_gateway_endpoint_gets_etag(self, middleware, mock_request):
        """Test that gateway endpoint gets ETag header."""
        mock_request.url.path = "/gateways/xyz789"

        response_data = {"id": "xyz789", "name": "Test Gateway", "version": 10}

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"xyz789-10"'

    @pytest.mark.asyncio
    async def test_tool_endpoint_gets_etag(self, middleware, mock_request):
        """Test that tool endpoint gets ETag header."""
        mock_request.url.path = "/tools/tool-123"

        response_data = {"id": "tool-123", "name": "Test Tool", "version": 3}

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"tool-123-3"'

    @pytest.mark.asyncio
    async def test_resource_endpoint_gets_etag(self, middleware, mock_request):
        """Test that resource endpoint gets ETag header."""
        mock_request.url.path = "/resources/res-456"

        response_data = {"id": "res-456", "name": "Test Resource", "version": 7}

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"res-456-7"'

    @pytest.mark.asyncio
    async def test_prompt_endpoint_gets_etag(self, middleware, mock_request):
        """Test that prompt endpoint gets ETag header."""
        mock_request.url.path = "/prompts/prompt-789"

        response_data = {"id": "prompt-789", "name": "Test Prompt", "version": 2}

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"prompt-789-2"'

    @pytest.mark.asyncio
    async def test_a2a_endpoint_gets_etag(self, middleware, mock_request):
        """Test that a2a agent endpoint gets ETag header."""
        mock_request.url.path = "/a2a/agent-abc"

        response_data = {"id": "agent-abc", "name": "Test Agent", "version": 15}

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"agent-abc-15"'

    @pytest.mark.asyncio
    async def test_non_json_response_does_not_add_etag(self, middleware, mock_request):
        """Test that non-JSON responses don't get ETag headers."""
        mock_response = Response(
            content="<html>Hello</html>",
            media_type="text/html",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_crash(self, middleware, mock_request):
        """Test that malformed JSON doesn't crash middleware."""
        mock_response = Response(
            content="invalid json {",
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # Should not raise exception, just skip ETag
        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_list_endpoints_do_not_get_etag(self, middleware, mock_request):
        """Test that list endpoints (without ID) don't get ETags."""
        mock_request.url.path = "/servers"

        response_data = [{"id": "abc", "version": 1}, {"id": "xyz", "version": 2}]

        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # List endpoints shouldn't get ETags (they're arrays, not single resources)
        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_streaming_response_with_body_iterator(self, middleware, mock_request):
        """Test ETag added to StreamingResponse with body_iterator."""
        from starlette.responses import StreamingResponse

        response_data = {"id": "streaming-123", "name": "Test", "version": 8}

        async def generate():
            yield json.dumps(response_data).encode()

        mock_response = StreamingResponse(
            generate(),
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # Should add ETag to streaming responses
        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"streaming-123-8"'

    @pytest.mark.asyncio
    async def test_response_with_empty_body(self, middleware, mock_request):
        """Test that empty body doesn't crash middleware."""
        # Response with no body content
        mock_response = Response(
            content="",
            media_type="application/json",
            status_code=200,
        )

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # Should not crash, just skip ETag
        assert "ETag" not in response.headers

    @pytest.mark.asyncio
    async def test_response_body_attribute(self, middleware, mock_request):
        """Test ETag extraction from Response.body attribute."""
        response_data = {"id": "body-attr-123", "name": "Test", "version": 12}

        # Create response with direct body attribute (not iterator)
        mock_response = Response(
            content=json.dumps(response_data),
            media_type="application/json",
            status_code=200,
        )
        # Force body attribute to exist
        mock_response.body = json.dumps(response_data).encode()

        # Mock the body_iterator to not exist
        if hasattr(mock_response, 'body_iterator'):
            delattr(mock_response, 'body_iterator')

        call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, call_next)

        # Should extract from body attribute
        assert "ETag" in response.headers
        assert response.headers["ETag"] == 'W/"body-attr-123-12"'
