# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_validation_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the validation middleware.
"""

# Standard
import re
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.validation_middleware import ValidationMiddleware, is_path_traversal


class TestIsPathTraversal:
    """Tests for is_path_traversal function."""

    def test_double_dots(self):
        """Test detection of double dots."""
        assert is_path_traversal("../etc/passwd") is True
        assert is_path_traversal("/safe/../unsafe") is True

    def test_leading_slash(self):
        """Test detection of leading slash."""
        assert is_path_traversal("/etc/passwd") is True

    def test_backslash(self):
        """Test detection of backslash."""
        assert is_path_traversal("..\\windows\\system32") is True

    def test_safe_path(self):
        """Test safe path returns False."""
        assert is_path_traversal("safe/path/file.txt") is False


class TestValidationMiddleware:
    """Tests for ValidationMiddleware."""

    @pytest.fixture
    def middleware_enabled(self):
        """Create enabled validation middleware."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script", r"javascript:"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            yield middleware

    @pytest.fixture
    def middleware_disabled(self):
        """Create disabled validation middleware."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)
            yield middleware

    @pytest.fixture
    def mock_request(self):
        """Create a mock HTTP request."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_middleware_disabled(self, middleware_disabled, mock_request):
        """Test middleware passes through when disabled."""

        async def call_next(request):
            return Response("ok")

        response = await middleware_disabled.dispatch(mock_request, call_next)
        assert response.body == b"ok"

    @pytest.mark.asyncio
    async def test_middleware_enabled_valid_request(self):
        """Test middleware passes valid request."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/test",
                "query_string": b"name=test",
                "headers": [],
            }
            request = Request(scope)

            async def call_next(req):
                return Response("ok")

            response = await middleware.dispatch(request, call_next)
            assert response.body == b"ok"

    @pytest.mark.asyncio
    async def test_middleware_warn_only_mode(self):
        """Test middleware logs warning in development mode."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = False  # Not strict
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"  # Development mode

            middleware = ValidationMiddleware(app=None)

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/test",
                "query_string": b"data=%3Cscript%3E",  # <script> URL-encoded
                "headers": [],
            }
            request = Request(scope)

            async def call_next(req):
                return Response("ok")

            # Should not raise in warn-only mode
            response = await middleware.dispatch(request, call_next)
            assert response.body == b"ok"

    def test_validate_parameter_exceeds_length(self):
        """Test parameter length validation."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_parameter("test", "a" * 100)

            assert exc_info.value.status_code == 422
            assert "exceeds maximum length" in exc_info.value.detail

    def test_validate_parameter_dangerous_pattern(self):
        """Test dangerous pattern detection."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_parameter("input", "<script>alert('xss')</script>")

            assert exc_info.value.status_code == 422
            assert "dangerous characters" in exc_info.value.detail

    def test_validate_parameter_dev_mode_warns(self):
        """Test parameter validation warns in development mode."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 10
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)

            # Should not raise in development mode
            middleware._validate_parameter("test", "a" * 100)

    def test_validate_json_data_dict(self):
        """Test JSON data validation with dict."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Should not raise for valid data
            middleware._validate_json_data({"name": "test", "nested": {"value": "ok"}})

    def test_validate_json_data_list(self):
        """Test JSON data validation with list."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Should not raise for valid data
            middleware._validate_json_data([{"name": "item1"}, {"name": "item2"}])

    def test_validate_resource_path_traversal(self):
        """Test resource path validation for traversal."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("../etc/passwd")

            assert exc_info.value.status_code == 400
            assert "Path traversal" in exc_info.value.detail

    def test_validate_resource_path_double_slash(self):
        """Test resource path validation for double slash."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("/path//double")

            assert exc_info.value.status_code == 400
            assert "Path traversal" in exc_info.value.detail

    def test_validate_resource_path_uri_scheme_blocked(self):
        """Test resource path validation blocks URIs with // (path traversal check first)."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            # URIs with :// are blocked because // is checked first
            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("http://example.com/resource")

            assert exc_info.value.status_code == 400
            assert "Path traversal" in exc_info.value.detail

    def test_validate_resource_path_too_deep(self):
        """Test resource path validation for depth limit."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 3

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("a/b/c/d/e/f/g")

            assert exc_info.value.status_code == 400
            assert "Path too deep" in exc_info.value.detail

    def test_validate_resource_path_outside_roots(self):
        """Test resource path validation for allowed roots."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = ["/safe"]
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("/unsafe/path")

            assert exc_info.value.status_code == 400
            assert "Path outside allowed roots" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sanitize_response(self):
        """Test response sanitization."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Response with control characters
            response = Response(content="Hello\x00World\x1f")

            sanitized = await middleware._sanitize_response(response)

            assert b"\x00" not in sanitized.body
            assert b"\x1f" not in sanitized.body
            assert b"HelloWorld" in sanitized.body

    @pytest.mark.asyncio
    async def test_sanitize_response_no_body(self):
        """Test response sanitization with no body."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            response = MagicMock()
            del response.body  # Remove body attribute

            result = await middleware._sanitize_response(response)

            assert result == response

    @pytest.mark.asyncio
    async def test_sanitize_output_enabled(self):
        """Test full middleware flow with sanitization."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/test",
                "query_string": b"",
                "headers": [],
            }
            request = Request(scope)

            async def call_next(req):
                return Response(content="Hello\x00World")

            response = await middleware.dispatch(request, call_next)

            assert b"\x00" not in response.body
