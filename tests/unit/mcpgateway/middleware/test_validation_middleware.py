# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_validation_middleware.py
Copyright 2026
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

    @pytest.mark.asyncio
    async def test_dispatch_warn_only_logs_and_continues_on_http_exception(self):
        """Test dispatch handles HTTPException in warn-only mode (log + continue)."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)

            middleware._validate_request = AsyncMock(side_effect=HTTPException(status_code=422, detail="bad"))  # type: ignore[method-assign]

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/test",
                "query_string": b"",
                "headers": [],
            }
            request = Request(scope)

            async def call_next(req):
                return Response("ok")

            response = await middleware.dispatch(request, call_next)
            assert response.body == b"ok"

    @pytest.mark.asyncio
    async def test_dispatch_strict_logs_and_raises_on_http_exception(self):
        """Test dispatch re-raises HTTPException outside warn-only mode."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            middleware._validate_request = AsyncMock(side_effect=HTTPException(status_code=422, detail="bad"))  # type: ignore[method-assign]

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/test",
                "query_string": b"",
                "headers": [],
            }
            request = Request(scope)

            async def call_next(req):
                return Response("ok")

            with pytest.raises(HTTPException):
                await middleware.dispatch(request, call_next)

    @pytest.mark.asyncio
    async def test_validate_request_path_params_and_empty_json_body(self):
        """Test _validate_request validates path params and handles empty JSON body."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            class DummyRequest:
                path_params = {"id": 123}
                query_params = {"q": "ok"}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b""

            await middleware._validate_request(DummyRequest())

    @pytest.mark.asyncio
    async def test_validate_request_without_path_params_attribute(self):
        """Test _validate_request handles objects without a path_params attribute."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            class DummyRequest:
                query_params = {"q": "ok"}
                headers = {}

                async def body(self):
                    return b""

            await middleware._validate_request(DummyRequest())

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

    def test_validate_resource_path_uri_scheme_allowed(self):
        """Test resource path validation skips checks for URI schemes."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            assert middleware.validate_resource_path("http://example.com/resource") == "http://example.com/resource"

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

    def test_validate_resource_path_allowed_root_returns_resolved_path(self, tmp_path):
        """Test valid paths under allowed roots return resolved path."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = [str(tmp_path)]
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)

            candidate = tmp_path / "subdir" / "file.txt"
            resolved = middleware.validate_resource_path(str(candidate))
            assert resolved.startswith(str(tmp_path.resolve()))

    def test_validate_resource_path_no_allowed_roots_returns_resolved_path(self, tmp_path):
        """Test valid paths return resolved path when allowed roots are not configured."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)

            candidate = tmp_path / "file.txt"
            resolved = middleware.validate_resource_path(str(candidate))
            assert resolved == str(candidate.resolve())

    def test_validate_resource_path_invalid_path_raises(self):
        """Test invalid paths raise HTTPException via the error handler."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path("bad\x00path")

            assert exc_info.value.status_code == 400
            assert "Invalid path" in exc_info.value.detail

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
    async def test_sanitize_response_str_body_skips_decode(self):
        """Test sanitization works when response.body is already a string."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            class DummyResponse:
                def __init__(self, body):
                    self.body = body
                    self.headers = {}

            response = DummyResponse("Hello\x00World")
            sanitized = await middleware._sanitize_response(response)
            assert sanitized.body == b"HelloWorld"
            assert sanitized.headers["content-length"] == str(len(sanitized.body))

    @pytest.mark.asyncio
    async def test_sanitize_response_exception_is_caught(self):
        """Test sanitization catches unexpected exceptions."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []

            middleware = ValidationMiddleware(app=None)

            class DummyResponse:
                def __init__(self, body):
                    self.body = body
                    self.headers = {}

            response = DummyResponse(object())
            result = await middleware._sanitize_response(response)
            assert result is response

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

    def test_validate_parameter_valid_uaid(self):
        """Test UAID validation with valid UAID format.

        Covers: validation_middleware.py lines 160, 162, 164-165, 169
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r";"]  # Semicolons would normally be dangerous
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Valid UAID with semicolons (which are allowed in UAIDs)
            valid_uaid = "uaid:aid:abc123;uid=0;registry=context-forge;proto=a2a;nativeId=example.com"

            # Should not raise even though it contains semicolons
            middleware._validate_parameter("agent_id", valid_uaid)

    def test_validate_parameter_invalid_uaid_strict_mode(self):
        """Test UAID validation with invalid UAID in strict mode.

        Covers: validation_middleware.py lines 160, 162, 164-168
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"  # Production + strict = raise

            middleware = ValidationMiddleware(app=None)

            # Invalid UAID format (missing uid parameter)
            invalid_uaid = "uaid:aid:abc123;registry=context-forge"

            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_parameter("agent_id", invalid_uaid)

            assert exc_info.value.status_code == 422
            assert "Invalid UAID format" in exc_info.value.detail

    def test_validate_parameter_invalid_uaid_development_mode(self):
        """Test UAID validation with invalid UAID in development mode.

        Covers: validation_middleware.py lines 160, 162, 164-167
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"  # Development = log warning only

            middleware = ValidationMiddleware(app=None)

            # Invalid UAID format
            invalid_uaid = "uaid:aid:abc123;registry=context-forge"

            # Should not raise in development mode, just log warning
            middleware._validate_parameter("agent_id", invalid_uaid)

    def test_validate_parameter_uaid_import_error_fallback(self):
        """Test UAID validation fallback when validator import fails.

        Covers: validation_middleware.py lines 160, 162, 170, 172-173
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Patch the import to raise ImportError - need to patch it during _validate_parameter call
            import builtins
            real_import = builtins.__import__
            def mock_import(name, *args, **kwargs):
                if name == "mcpgateway.utils.uaid":
                    raise ImportError("UAID validator not available")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                # Should not raise, just log debug and return
                middleware._validate_parameter("agent_id", "uaid:aid:abc123")

    def test_validate_parameter_uuid_format(self):
        """Test UUID validation bypasses dangerous pattern check.

        Covers: validation_middleware.py lines 176-177
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"-"]  # Hyphens would normally be dangerous
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Valid UUID format with hyphens
            valid_uuid = "550e8400-e29b-41d4-a716-446655440000"

            # Should not raise even though it contains hyphens
            middleware._validate_parameter("user_id", valid_uuid)

    def test_validate_parameter_non_id_field_with_dangerous_pattern(self):
        """Test that non-ID fields still get dangerous pattern validation."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Non-ID field should still be validated for dangerous patterns
            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_parameter("user_input", "<script>alert('xss')</script>")

            assert exc_info.value.status_code == 422
            assert "dangerous characters" in exc_info.value.detail

    def test_validate_parameter_uaid_in_non_id_field(self):
        """Test that UAID values bypass dangerous pattern check regardless of key name.

        UAIDs contain semicolons which may match dangerous patterns.
        The exemption should apply to any value starting with 'uaid:', not just '_id' keys.
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            # Semicolons are commonly in dangerous patterns
            mock_settings.dangerous_patterns = [r";"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Valid UAID with semicolons passed in a non-id field (e.g., agent_name)
            valid_uaid = "uaid:aid:abc123;uid=0;registry=context-forge;proto=a2a;nativeId=example.com"

            # Should NOT raise even though key is not '_id' and value contains semicolons
            middleware._validate_parameter("agent_name", valid_uaid)

    def test_validate_parameter_invalid_uaid_falls_through_to_dangerous_pattern(self):
        """Test that invalid UAIDs fall through to dangerous pattern check.

        An attacker should not be able to bypass pattern matching by prefixing
        any payload with 'uaid:' in non-strict environments.
        """
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            # Invalid UAID containing a dangerous pattern
            invalid_uaid_with_script = "uaid:aid:abc123;<script>alert('xss')</script>"

            # Should raise because it contains <script even though it starts with uaid:
            with pytest.raises(HTTPException) as exc_info:
                middleware._validate_parameter("agent_name", invalid_uaid_with_script)
            assert exc_info.value.status_code == 422
            assert "dangerous characters" in exc_info.value.detail
