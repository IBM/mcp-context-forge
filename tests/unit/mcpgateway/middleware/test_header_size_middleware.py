# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_header_size_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for RFC 6585 5 (431 Request Header Fields Too Large) middleware.

Examples:
    >>> pytest tests/unit/mcpgateway/middleware/test_header_size_middleware.py -v  # doctest: +SKIP
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import Request
from starlette.datastructures import Headers

# First-Party
from mcpgateway.middleware.header_size_middleware import HeaderSizeMiddleware


class TestHeaderSizeMiddleware:
    """Test suite for RFC 6585 compliant header size validation."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance with test settings."""
        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 10
            mock_settings.trust_proxy_auth = False  # Don't trust proxy headers in tests

            app = MagicMock()
            return HeaderSizeMiddleware(app)

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock(spec=Request)
        request.headers = Headers({})
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    def test_middleware_initialization(self, middleware):
        """Test middleware initializes with correct settings."""
        assert middleware.enabled is True
        assert middleware.max_total_size == 1000
        assert middleware.max_field_size == 500
        assert middleware.max_header_count == 10

    @pytest.mark.asyncio
    async def test_request_passes_under_limits(self, middleware, mock_request):
        """Test request passes when under all limits."""
        mock_request.headers = Headers({"Content-Type": "application/json", "Accept": "application/json"})

        mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_rejected_too_many_headers(self, middleware, mock_request):
        """Test request rejected when header count exceeds limit."""
        # Create 11 headers (limit is 10)
        headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(11)}
        mock_request.headers = Headers(headers_dict)

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 431
        assert "Too many header fields" in response.body.decode()
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_rejected_field_too_large(self, middleware, mock_request):
        """Test request rejected when individual field exceeds limit."""
        # Create a header field larger than 500 bytes
        large_value = "x" * 600
        mock_request.headers = Headers({"X-Large-Header": large_value})

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 431
        body = response.body.decode()
        assert "Header field" in body
        assert "exceeds maximum size" in body
        # Starlette lowercases header names
        assert "x-large-header" in body.lower()
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_rejected_total_size_too_large(self, middleware, mock_request):
        """Test request rejected when total header size exceeds limit."""
        # Create multiple headers that together exceed 1000 bytes but each under 500 bytes
        # Each header: "X-H-{i}: " + value = ~10 + 2 + 80 = ~92 bytes
        # 12 headers * 92 = ~1104 bytes > 1000 bytes limit
        headers_dict = {f"X-H-{i}": "x" * 80 for i in range(12)}
        mock_request.headers = Headers(headers_dict)

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 431
        body = response.body.decode()
        assert ("Total header size exceeds maximum" in body or "Too many header fields" in body)
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_rejected_total_size_too_large_under_header_count_limit(self, middleware, mock_request):
        """Total size violation specifically, staying under the header-count limit.

        Uses fewer headers than max_header_count so the header-count check
        does not short-circuit before the total-size check runs.
        """
        # 5 headers, each field under 500 bytes, but summing over 1000 bytes total.
        headers_dict = {f"X-H-{i}": "x" * 200 for i in range(5)}
        mock_request.headers = Headers(headers_dict)

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 431
        body = response.body.decode()
        assert "Total header size exceeds maximum" in body
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_431_response_includes_limits(self, middleware, mock_request):
        """Test 431 response includes limit information."""
        headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(11)}
        mock_request.headers = Headers(headers_dict)

        response = await middleware.dispatch(mock_request, AsyncMock())

        assert response.status_code == 431
        body_json = response.body.decode()
        assert "max_total_size_bytes" in body_json
        assert "max_field_size_bytes" in body_json
        assert "max_header_count" in body_json

    @pytest.mark.asyncio
    async def test_431_response_includes_connection_close(self, middleware, mock_request):
        """Test 431 response includes Connection: close header per RFC 6585."""
        headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(11)}
        mock_request.headers = Headers(headers_dict)

        response = await middleware.dispatch(mock_request, AsyncMock())

        assert response.status_code == 431
        assert response.headers.get("Connection") == "close"

    @pytest.mark.asyncio
    async def test_middleware_disabled(self, mock_request):
        """Test middleware passes through when disabled."""
        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = False

            app = MagicMock()
            middleware = HeaderSizeMiddleware(app)

            # Create request with too many headers
            headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(20)}
            mock_request.headers = Headers(headers_dict)

            mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
            response = await middleware.dispatch(mock_request, mock_call_next)

            assert response.status_code == 200
            mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_header_size_calculation_includes_colon(self, middleware, mock_request):
        """Test header size calculation includes field-name, colon, and field-value."""
        # Field size = len(name) + len(value) + 2 (for ": ")
        # "X-Test: value" = 6 + 5 + 2 = 13 bytes
        mock_request.headers = Headers({"X-Test": "value"})

        mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_client_ip_with_x_forwarded_for(self):
        """Test client IP extraction from X-Forwarded-For header when trust_proxy_auth=True."""
        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 10
            mock_settings.trust_proxy_auth = True  # Enable proxy trust

            app = MagicMock()
            middleware = HeaderSizeMiddleware(app)

            request = MagicMock(spec=Request)
            request.headers = Headers({"X-Forwarded-For": "203.0.113.1, 198.51.100.1"})
            request.scope = {"client": ("192.168.1.100", 12345)}

            client_ip = middleware._get_client_ip(request)
            assert client_ip == "203.0.113.1"

    @pytest.mark.asyncio
    async def test_get_client_ip_with_x_real_ip(self):
        """Test client IP extraction from X-Real-IP header when trust_proxy_auth=True."""
        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 10
            mock_settings.trust_proxy_auth = True  # Enable proxy trust

            app = MagicMock()
            middleware = HeaderSizeMiddleware(app)

            request = MagicMock(spec=Request)
            request.headers = Headers({"X-Real-IP": "203.0.113.1"})
            request.scope = {"client": ("192.168.1.100", 12345)}

            client_ip = middleware._get_client_ip(request)
            assert client_ip == "203.0.113.1"

    @pytest.mark.asyncio
    async def test_get_client_ip_fallback_to_scope(self, middleware):
        """Test client IP falls back to scope when proxy headers absent."""
        request = MagicMock(spec=Request)
        request.headers = Headers({})
        request.scope = {"client": ("192.168.1.100", 12345)}

        client_ip = middleware._get_client_ip(request)
        assert client_ip == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_get_client_ip_unknown_when_no_client(self, middleware):
        """Test client IP returns 'unknown' when no client info available."""
        request = MagicMock(spec=Request)
        request.headers = Headers({})
        request.scope = {}

        client_ip = middleware._get_client_ip(request)
        assert client_ip == "unknown"

    @pytest.mark.asyncio
    async def test_violation_type_in_response(self, middleware, mock_request):
        """Test violation_type is included in 431 response."""
        # Test header_count violation
        headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(11)}
        mock_request.headers = Headers(headers_dict)

        response = await middleware.dispatch(mock_request, AsyncMock())
        body = response.body.decode()
        assert "header_count" in body

    @pytest.mark.asyncio
    async def test_field_name_in_response_for_field_size_violation(self, middleware, mock_request):
        """Test field_name is included in 431 response for field size violations."""
        large_value = "x" * 600
        mock_request.headers = Headers({"X-Large-Header": large_value})

        response = await middleware.dispatch(mock_request, AsyncMock())
        body = response.body.decode()
        # Starlette lowercases header names
        assert "x-large-header" in body.lower()
        assert "field_name" in body

    @pytest.mark.asyncio
    async def test_empty_headers_pass(self, middleware, mock_request):
        """Test request with no headers passes validation."""
        mock_request.headers = Headers({})

        mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_exactly_at_limit_passes(self, middleware, mock_request):
        """Test request exactly at limits passes validation."""
        # Create exactly 10 headers (at the limit)
        headers_dict = {f"X-Custom-{i}": f"value{i}" for i in range(10)}
        mock_request.headers = Headers(headers_dict)

        mock_call_next = AsyncMock(return_value=MagicMock(status_code=200))
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        mock_call_next.assert_called_once()

    def test_create_431_response_structure(self, middleware):
        """Test 431 response has correct structure."""
        response = middleware._create_431_response(
            message="Test message",
            violation_type="test_type",
            field_name="X-Test-Header"
        )

        assert response.status_code == 431
        body = response.body.decode()
        assert "Request Header Fields Too Large" in body
        assert "Test message" in body
        assert "test_type" in body
        assert "X-Test-Header" in body
        assert response.headers.get("Connection") == "close"


class TestHeaderSizeMiddlewareASGICall:
    """Pure-ASGI ``__call__`` entry point coverage (passthrough and 431 rejection)."""

    @pytest.mark.asyncio
    async def test_call_ignores_non_http_scope(self):
        """Lifespan/websocket scopes pass straight through untouched."""
        called = []

        async def app(scope, receive, send):
            called.append(scope["type"])

        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 10

            middleware = HeaderSizeMiddleware(app)

        async def noop(*_args):
            return None

        await middleware({"type": "lifespan"}, noop, noop)
        assert called == ["lifespan"]

    @pytest.mark.asyncio
    async def test_call_sends_431_rejection_directly_without_calling_downstream(self):
        """Too many headers: the 431 rejection is sent via ASGI, downstream never runs."""
        downstream_called = False

        async def app(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True

        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 2
            mock_settings.trust_proxy_auth = False

            middleware = HeaderSizeMiddleware(app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/data",
            "headers": [(b"x-a", b"1"), (b"x-b", b"2"), (b"x-c", b"3")],
        }

        async def receive():
            return {"type": "http.request", "body": b""}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

        assert downstream_called is False
        assert sent[0]["status"] == 431

    @pytest.mark.asyncio
    async def test_call_invokes_downstream_when_headers_within_limits(self):
        """Headers within limits: downstream app runs and its response is sent verbatim."""

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("mcpgateway.middleware.header_size_middleware.settings") as mock_settings:
            mock_settings.header_size_validation_enabled = True
            mock_settings.max_header_total_size_bytes = 1000
            mock_settings.max_header_field_size_bytes = 500
            mock_settings.max_header_count = 10
            mock_settings.trust_proxy_auth = False

            middleware = HeaderSizeMiddleware(app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/data",
            "headers": [(b"x-a", b"1")],
        }

        async def receive():
            return {"type": "http.request", "body": b""}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

        assert sent[0]["status"] == 200
