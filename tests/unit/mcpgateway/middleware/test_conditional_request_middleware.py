# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_conditional_request_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Unit tests for RFC 6585 Phase 2 conditional request middleware.

Examples:
    >>> pytest tests/unit/mcpgateway/middleware/test_conditional_request_middleware.py -v  # doctest: +SKIP
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import JSONResponse


class TestConditionalRequestMiddlewareConfiguration:
    """Test middleware configuration and initialization."""

    @patch("mcpgateway.middleware.conditional_request_middleware.settings")
    def test_middleware_initialization_disabled(self, mock_settings):
        """Test middleware initializes with feature disabled."""
        mock_settings.conditional_requests_enabled = False
        mock_settings.conditional_requests_required_methods = ["PUT", "PATCH", "DELETE"]
        mock_settings.conditional_requests_exempt_paths = ["/health"]
        mock_settings.conditional_requests_require_etag = True

        from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

        middleware = ConditionalRequestMiddleware(MagicMock())

        assert middleware.enabled is False
        assert "PUT" in middleware.required_methods
        assert "/health" in middleware.exempt_paths

    @patch("mcpgateway.middleware.conditional_request_middleware.settings")
    def test_middleware_initialization_enabled(self, mock_settings):
        """Test middleware initializes with feature enabled."""
        mock_settings.conditional_requests_enabled = True
        mock_settings.conditional_requests_required_methods = ["PUT", "PATCH", "DELETE"]
        mock_settings.conditional_requests_exempt_paths = ["/health", "/metrics"]
        mock_settings.conditional_requests_require_etag = True

        from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

        middleware = ConditionalRequestMiddleware(MagicMock())

        assert middleware.enabled is True
        assert middleware.required_methods == {"PUT", "PATCH", "DELETE"}
        assert middleware.exempt_paths == ["/health", "/metrics"]
        assert middleware.require_etag is True


class TestConditionalRequestMiddlewareDispatch:
    """Test middleware request dispatch logic."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for tests."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT", "PATCH", "DELETE"]
            mock.conditional_requests_exempt_paths = ["/health", "/metrics"]
            mock.conditional_requests_require_etag = True
            mock.trust_proxy_auth = False
            yield mock

    @pytest.fixture
    def middleware(self, mock_settings):
        """Create middleware instance for testing."""
        from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

        return ConditionalRequestMiddleware(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock HTTP request."""
        request = MagicMock()
        request.method = "PUT"
        request.url.path = "/servers/abc123"
        request.headers = {}
        request.state = MagicMock()
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    @pytest.mark.asyncio
    async def test_dispatch_disabled_middleware_passes_through(self, middleware, mock_request):
        """Test that disabled middleware passes requests through."""
        middleware.enabled = False
        call_next = AsyncMock(return_value=JSONResponse({"status": "ok"}))

        response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_get_request_passes_through(self, middleware, mock_request):
        """Test that GET requests pass through without validation."""
        mock_request.method = "GET"
        call_next = AsyncMock(return_value=JSONResponse({"status": "ok"}))

        response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_exempt_path_passes_through(self, middleware, mock_request):
        """Test that exempt paths pass through without validation."""
        mock_request.url.path = "/health"
        call_next = AsyncMock(return_value=JSONResponse({"status": "ok"}))

        response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_missing_if_match_returns_428(self, middleware, mock_request):
        """Test that missing If-Match header returns 428 Precondition Required."""
        call_next = AsyncMock()

        response = await middleware.dispatch(mock_request, call_next)

        # Should not call next handler
        call_next.assert_not_called()

        # Should return 428
        assert response.status_code == 428
        body = response.body.decode()
        assert "Precondition Required" in body
        assert "If-Match" in body

    @pytest.mark.asyncio
    async def test_dispatch_invalid_if_match_format_returns_412(self, middleware, mock_request):
        """Test that invalid If-Match format returns 412 when resource exists."""
        mock_request.headers = {"If-Match": "invalid-format"}
        call_next = AsyncMock()

        # Mock resource exists with version 5
        with patch.object(middleware, "_get_current_version", return_value=5):
            response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_not_called()
        # Invalid ETag format won't match, so returns 412 Precondition Failed
        assert response.status_code == 412

    @pytest.mark.asyncio
    async def test_dispatch_nonexistent_resource_passes_through(self, middleware, mock_request):
        """Test that requests for non-existent resources pass through (404 handled by endpoint)."""
        mock_request.headers = {"If-Match": 'W/"abc123-5"'}
        call_next = AsyncMock(return_value=JSONResponse({"error": "Not Found"}, status_code=404))

        with patch.object(middleware, "_get_current_version", return_value=None):
            response = await middleware.dispatch(mock_request, call_next)

        # Should pass through to endpoint which returns 404
        call_next.assert_called_once_with(mock_request)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_dispatch_valid_etag_proceeds(self, middleware, mock_request):
        """Test that valid ETag allows request to proceed."""
        mock_request.headers = {"If-Match": 'W/"abc123-5"'}
        call_next = AsyncMock(return_value=JSONResponse({"status": "updated"}))

        with patch.object(middleware, "_get_current_version", return_value=5):
            response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_stale_etag_returns_412(self, middleware, mock_request):
        """Test that stale ETag returns 412 Precondition Failed."""
        mock_request.headers = {"If-Match": 'W/"abc123-5"'}
        call_next = AsyncMock()

        with patch.object(middleware, "_get_current_version", return_value=6):
            response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_not_called()
        assert response.status_code == 412
        body = response.body.decode()
        assert "Precondition Failed" in body
        assert "abc123-6" in body  # Should include current ETag


class TestResourceInfoExtraction:
    """Test resource info extraction from paths."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT"]
            mock.conditional_requests_exempt_paths = []
            mock.conditional_requests_require_etag = True

            from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

            return ConditionalRequestMiddleware(MagicMock())

    def test_extract_resource_info_server(self, middleware):
        """Test extracting resource info for server path."""
        result = middleware._extract_resource_info("/servers/abc123")
        assert result == ("servers", "abc123")

    def test_extract_resource_info_gateway(self, middleware):
        """Test extracting resource info for gateway path."""
        result = middleware._extract_resource_info("/gateways/xyz789")
        assert result == ("gateways", "xyz789")

    def test_extract_resource_info_tool(self, middleware):
        """Test extracting resource info for tool path."""
        result = middleware._extract_resource_info("/tools/tool-id")
        assert result == ("tools", "tool-id")

    def test_extract_resource_info_resource(self, middleware):
        """Test extracting resource info for resource path."""
        result = middleware._extract_resource_info("/resources/res-123")
        assert result == ("resources", "res-123")

    def test_extract_resource_info_prompt(self, middleware):
        """Test extracting resource info for prompt path."""
        result = middleware._extract_resource_info("/prompts/prompt-456")
        assert result == ("prompts", "prompt-456")

    def test_extract_resource_info_a2a(self, middleware):
        """Test extracting resource info for a2a agent path."""
        result = middleware._extract_resource_info("/a2a/agent-789")
        assert result == ("a2a", "agent-789")

    def test_extract_resource_info_invalid_path(self, middleware):
        """Test that invalid paths return None."""
        assert middleware._extract_resource_info("/unknown/path") is None
        assert middleware._extract_resource_info("/servers") is None  # Missing ID
        assert middleware._extract_resource_info("/") is None


class TestVersionRetrieval:
    """Test database version retrieval."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT"]
            mock.conditional_requests_exempt_paths = []
            mock.conditional_requests_require_etag = True

            from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

            return ConditionalRequestMiddleware(MagicMock())

    @patch("mcpgateway.middleware.conditional_request_middleware.SessionLocal")
    def test_get_current_version_success(self, mock_session_local, middleware):
        """Test successful version retrieval from database."""
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session

        mock_resource = MagicMock()
        mock_resource.version = 42
        mock_session.query.return_value.filter.return_value.first.return_value = mock_resource

        version = middleware._get_current_version("servers", "abc123")

        assert version == 42

    @patch("mcpgateway.middleware.conditional_request_middleware.SessionLocal")
    def test_get_current_version_not_found(self, mock_session_local, middleware):
        """Test version retrieval when resource doesn't exist."""
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        version = middleware._get_current_version("servers", "nonexistent")

        assert version is None

    @patch("mcpgateway.middleware.conditional_request_middleware.SessionLocal")
    def test_get_current_version_database_error(self, mock_session_local, middleware):
        """Test version retrieval handles database errors gracefully."""
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.side_effect = Exception("Database error")

        version = middleware._get_current_version("servers", "abc123")

        assert version is None

    def test_get_current_version_invalid_resource_type(self, middleware):
        """Test version retrieval with invalid resource type."""
        version = middleware._get_current_version("invalid_type", "abc123")
        assert version is None


class TestResponseFormatting:
    """Test response formatting for 428 and 412 status codes."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT"]
            mock.conditional_requests_exempt_paths = []
            mock.conditional_requests_require_etag = True
            mock.trust_proxy_auth = False

            from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

            return ConditionalRequestMiddleware(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock()
        request.url.path = "/servers/abc123"
        request.method = "PUT"
        request.headers = {}
        request.state = MagicMock()
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    def test_create_428_response_format(self, middleware, mock_request):
        """Test 428 response format."""
        response = middleware._create_428_response(mock_request)

        assert response.status_code == 428
        assert response.headers["Content-Type"] == "application/json"

        body = response.body.decode()
        assert "Precondition Required" in body
        assert "If-Match" in body
        assert "/servers/abc123" in body

    def test_create_428_response_invalid_format(self, middleware, mock_request):
        """Test 428 response for invalid format."""
        response = middleware._create_428_response(mock_request, invalid_format=True)

        assert response.status_code == 428
        body = response.body.decode()
        assert "invalid" in body.lower()

    def test_create_412_response_format(self, middleware, mock_request):
        """Test 412 response format."""
        response = middleware._create_412_response(mock_request, "abc123", 6)

        assert response.status_code == 412
        assert "ETag" in response.headers

        body = response.body.decode()
        assert "Precondition Failed" in body
        assert "abc123-6" in body  # Current ETag

    def test_create_412_response_includes_current_etag(self, middleware, mock_request):
        """Test that 412 response includes current ETag in header and body."""
        response = middleware._create_412_response(mock_request, "server-xyz", 99)

        # Check header
        assert response.headers["ETag"] == 'W/"server-xyz-99"'

        # Check body
        body = response.body.decode()
        assert "server-xyz-99" in body


class TestMultipleETagSupport:
    """Test support for multiple ETags in If-Match header."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT"]
            mock.conditional_requests_exempt_paths = []
            mock.conditional_requests_require_etag = True

            from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

            return ConditionalRequestMiddleware(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock()
        request.method = "PUT"
        request.url.path = "/servers/abc123"
        request.state = MagicMock()
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    @pytest.mark.asyncio
    async def test_dispatch_multiple_etags_one_matches(self, middleware, mock_request):
        """Test that request succeeds if any ETag in list matches."""
        mock_request.headers = {"If-Match": 'W/"abc123-4", W/"abc123-5", W/"abc123-6"'}
        call_next = AsyncMock(return_value=JSONResponse({"status": "updated"}))

        with patch.object(middleware, "_get_current_version", return_value=5):
            response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_wildcard_etag_matches(self, middleware, mock_request):
        """Test that wildcard ETag always matches."""
        mock_request.headers = {"If-Match": "*"}
        call_next = AsyncMock(return_value=JSONResponse({"status": "updated"}))

        with patch.object(middleware, "_get_current_version", return_value=999):
            response = await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once()
        assert response.status_code == 200


class TestSecurityLogging:
    """Test security event logging."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock:
            mock.conditional_requests_enabled = True
            mock.conditional_requests_required_methods = ["PUT"]
            mock.conditional_requests_exempt_paths = []
            mock.conditional_requests_require_etag = True
            mock.trust_proxy_auth = False

            from mcpgateway.middleware.conditional_request_middleware import ConditionalRequestMiddleware

            return ConditionalRequestMiddleware(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock()
        request.url.path = "/servers/abc123"
        request.method = "PUT"
        request.headers = {}
        request.state.user_id = "user-123"
        request.state.user_email = "test@example.com"
        request.state.team_id = "team-456"
        request.scope = {"client": ("192.168.1.100", 12345)}
        return request

    def test_log_security_event_called_on_428(self, middleware, mock_request):
        """Test that security event is logged when returning 428."""
        with patch.object(middleware.security_logger, "_create_security_event") as mock_log:
            middleware._create_428_response(mock_request)

            mock_log.assert_called_once()
            call_args = mock_log.call_args[1]
            assert call_args["user_email"] == "test@example.com"
            assert call_args["category"] == "conditional_request"

    def test_log_security_event_called_on_412(self, middleware, mock_request):
        """Test that security event is logged when returning 412."""
        with patch.object(middleware.security_logger, "_create_security_event") as mock_log:
            middleware._create_412_response(mock_request, "abc123", 5)

            mock_log.assert_called_once()
            call_args = mock_log.call_args[1]
            assert call_args["user_id"] == "user-123"
            assert call_args["category"] == "conditional_request"

    @pytest.mark.asyncio
    async def test_unknown_resource_pattern_allows_request(self, middleware, mock_request):
        """Test that unknown resource patterns are allowed (endpoint handles validation)."""
        # Path that matches required method but not a known resource pattern
        mock_request.url.path = "/unknown/resource/path"
        mock_request.method = "PUT"
        mock_request.headers = {"If-Match": 'W/"test-123"'}

        call_next = AsyncMock(return_value=JSONResponse({"status": "ok"}))
        response = await middleware.dispatch(mock_request, call_next)

        # Request should be allowed through (no 428/412)
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_malformed_if_match_header_returns_428(self, middleware, mock_request):
        """Test that malformed If-Match header returns 428."""
        mock_request.url.path = "/servers/abc123"
        mock_request.method = "PUT"
        # Completely invalid If-Match format
        mock_request.headers = {"If-Match": "not-a-valid-etag-at-all!!!"}

        with patch.object(
            middleware, "_get_current_version", return_value=5
        ), patch("mcpgateway.middleware.conditional_request_middleware.parse_if_match_header", return_value=None):
            response = await middleware.dispatch(mock_request, AsyncMock())

            assert response.status_code == 428
            data = json.loads(response.body)
            assert "Precondition Required" in data["error"]

    @pytest.mark.asyncio
    async def test_security_logger_exception_is_caught(self, middleware, mock_request):
        """Test that exceptions in security logging don't crash the middleware."""
        mock_request.url.path = "/servers/abc123"
        mock_request.method = "PUT"
        mock_request.headers = {"If-Match": 'W/"abc123-999"'}

        with patch.object(middleware, "_get_current_version", return_value=5), patch.object(
            middleware.security_logger, "_create_security_event", side_effect=Exception("DB connection failed")
        ):
            # Should return 412 despite security logging failure
            response = await middleware.dispatch(mock_request, AsyncMock())

            assert response.status_code == 412
            # The exception should be caught and logged, not raised

    @pytest.mark.asyncio
    async def test_get_client_ip_with_x_forwarded_for(self, middleware, mock_request):
        """Test client IP extraction from X-Forwarded-For header."""
        mock_request.headers = {"X-Forwarded-For": "203.0.113.1, 198.51.100.1"}
        mock_request.scope = {"client": ("127.0.0.1", 12345)}

        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock_settings:
            mock_settings.trust_proxy_auth = True
            ip = middleware._get_client_ip(mock_request)

            # Should return first IP in X-Forwarded-For
            assert ip == "203.0.113.1"

    @pytest.mark.asyncio
    async def test_get_client_ip_with_x_real_ip(self, middleware, mock_request):
        """Test client IP extraction from X-Real-IP header."""
        mock_request.headers = {"X-Real-IP": "203.0.113.50"}
        mock_request.scope = {"client": ("127.0.0.1", 12345)}

        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock_settings:
            mock_settings.trust_proxy_auth = True
            ip = middleware._get_client_ip(mock_request)

            # Should return X-Real-IP
            assert ip == "203.0.113.50"

    @pytest.mark.asyncio
    async def test_get_client_ip_without_proxy_headers(self, middleware, mock_request):
        """Test client IP extraction when no proxy headers present."""
        mock_request.headers = {}
        mock_request.scope = {"client": ("192.168.1.100", 54321)}

        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock_settings:
            mock_settings.trust_proxy_auth = False
            ip = middleware._get_client_ip(mock_request)

            # Should return direct client IP from scope
            assert ip == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_get_client_ip_no_client_in_scope(self, middleware, mock_request):
        """Test client IP extraction when client not in scope."""
        mock_request.headers = {}
        mock_request.scope = {}  # No client field

        with patch("mcpgateway.middleware.conditional_request_middleware.settings") as mock_settings:
            mock_settings.trust_proxy_auth = False
            ip = middleware._get_client_ip(mock_request)

            # Should return "unknown" when no client info available
            assert ip == "unknown"
