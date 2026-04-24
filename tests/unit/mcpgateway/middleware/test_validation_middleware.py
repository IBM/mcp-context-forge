# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_validation_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the validation middleware.
"""

# Standard
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import orjson
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.validation_middleware import ValidationMiddleware, is_path_traversal


class JsonDepthError(ValueError):
    """Test double for the Rust extension JSON depth exception."""


class InvalidJsonError(ValueError):
    """Test double for the Rust extension invalid JSON exception."""


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
    async def test_validate_request_rejects_bad_params_before_reading_json_body(self):
        """Test invalid params short-circuit before JSON body reads."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            class DummyRequest:
                path_params = {"id": "<script>"}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    raise AssertionError("body should not be read when params already fail")

            with pytest.raises(HTTPException, match="contains dangerous characters"):
                await middleware._validate_request(DummyRequest())

    @pytest.mark.asyncio
    async def test_validate_request_uses_rust_http_request_when_enabled(self):
        """Test request validation uses one Rust HTTP request call."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            rust_module = MagicMock()
            rust_validator = MagicMock()
            rust_validator.validate_json_bytes.return_value = None
            rust_module.Validator.return_value = rust_validator

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", None):
                with patch("mcpgateway.middleware.validation_middleware.importlib.import_module", return_value=rust_module):
                    middleware = ValidationMiddleware(app=None)

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            await middleware._validate_request(DummyRequest())

            rust_validator.validate_json_bytes.assert_called_once_with(b'{"name":"safe"}')

    @pytest.mark.asyncio
    async def test_validate_request_validates_parameters_before_rust_json_bytes(self):
        """Test Rust request validation prechecks parameters before validating body bytes."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = None
            rust_validator.validate_json_bytes.return_value = None
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes

            class DummyRequest:
                path_params = {"id": 123}
                query_params = {"q": "safe"}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            await middleware._validate_request(DummyRequest())

            rust_validator.validate_parameters.assert_called_once_with([("id", "123"), ("q", "safe")])
            rust_validator.validate_json_bytes.assert_called_once_with(b'{"name":"safe"}')

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_result_raises_http_422(self):
        """Test Rust request results map back to middleware HTTP errors."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_json_bytes = MagicMock(return_value=("name", "dangerous_pattern"))

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                await middleware._validate_request(DummyRequest())

            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_invalid_json_defers_to_later_middleware(self):
        """Test Rust JSON decode failures are ignored here like the Python path."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_json_bytes = MagicMock(side_effect=orjson.JSONDecodeError("invalid json", "", 0))

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b"{"

            await middleware._validate_request(DummyRequest())

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_rejects_bad_params_before_body_validation(self):
        """Test Rust-backed request validation rejects bad params during the precheck."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = ("id", "dangerous_pattern")
            rust_validator.validate_json_bytes.return_value = None
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes

            class DummyRequest:
                path_params = {"id": "<script>"}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            with pytest.raises(HTTPException, match="contains dangerous characters"):
                await middleware._validate_request(DummyRequest())

            rust_validator.validate_parameters.assert_called_once_with([("id", "<script>")])
            rust_validator.validate_json_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_body_failure_skips_redundant_python_parameter_validation(self):
        """Test Rust request-path failures fall back to Python body validation without rechecking params."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = None
            rust_validator.validate_json_bytes.side_effect = RuntimeError("boom")
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes
            middleware._validate_parameters_with_python = MagicMock(return_value=None)  # type: ignore[method-assign]

            class DummyRequest:
                path_params = {"id": "safe"}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            await middleware._validate_request(DummyRequest())

            rust_validator.validate_parameters.assert_called_once_with([("id", "safe")])
            rust_validator.validate_json_bytes.assert_called_once_with(b'{"name":"safe"}')
            middleware._validate_parameters_with_python.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_request_rust_bytes_extension_falls_back_to_python_validation(self):
        """Test request validation falls back to Python when the Rust bytes path fails."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_bytes.side_effect = RuntimeError("boom")
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"<script>"}'

            with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                await middleware._validate_request(DummyRequest())

            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_prechecks_parameters_before_json_body(self):
        """Test Rust request validation prechecks params, then validates only the JSON body."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = None
            rust_validator.validate_json_bytes.return_value = None
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes

            class DummyRequest:
                path_params = {"id": 123}
                query_params = {"q": "safe"}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            await middleware._validate_request(DummyRequest())

            rust_validator.validate_parameters.assert_called_once_with([("id", "123"), ("q", "safe")])
            rust_validator.validate_json_bytes.assert_called_once_with(b'{"name":"safe"}')

    @pytest.mark.asyncio
    async def test_validate_request_with_rust_rejects_bad_params_before_reading_json_body(self):
        """Test Rust mode still short-circuits bad params before reading JSON bodies."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = ("id", "dangerous_pattern")
            rust_validator.validate_json_bytes.return_value = None
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes

            class DummyRequest:
                path_params = {"id": "<script>"}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    raise AssertionError("body should not be read when params already fail")

            with pytest.raises(HTTPException, match="contains dangerous characters"):
                await middleware._validate_request(DummyRequest())

            rust_validator.validate_parameters.assert_called_once_with([("id", "<script>")])
            rust_validator.validate_json_bytes.assert_not_called()

    def test_validate_request_with_rust_maps_invalid_json_value_error_to_decode_error(self):
        """Test Rust invalid JSON errors map to orjson.JSONDecodeError."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_bytes.side_effect = InvalidJsonError("Request body contains invalid JSON: expected value")
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes
            middleware._rust_invalid_json_error = InvalidJsonError

            with pytest.raises(orjson.JSONDecodeError):
                middleware._validate_body_with_rust(b"{")

    @pytest.mark.asyncio
    async def test_validate_request_maps_rust_max_depth_to_http_422(self):
        """Test Rust max-depth validation errors map to HTTP 422."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_bytes.side_effect = JsonDepthError("JSON payload exceeds maximum supported nesting depth")
            middleware._rust_validator = rust_validator
            middleware._rust_validate_json_bytes = rust_validator.validate_json_bytes
            middleware._rust_json_depth_error = JsonDepthError

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            with pytest.raises(HTTPException, match="maximum supported nesting depth") as exc_info:
                await middleware._validate_request(DummyRequest())

            assert exc_info.value.status_code == 422

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

    @pytest.mark.asyncio
    async def test_validate_request_with_python_rejects_deep_json_before_parse(self):
        """Test Python fallback rejects deeply nested JSON before orjson can fail open."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.validation_middleware_max_json_depth = 1024
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            class DummyRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b"[" * 1025 + b"0" + b"]" * 1025

            with pytest.raises(HTTPException, match="maximum supported nesting depth") as exc_info:
                await middleware._validate_request(DummyRequest())

            assert exc_info.value.status_code == 422

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

    def test_validate_json_data_list_rejects_dangerous_string_items(self):
        """Test JSON data validation rejects dangerous strings nested directly in lists."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                middleware._validate_json_data(["<script>"])

            assert exc_info.value.status_code == 422

    def test_validate_json_data_root_string_rejects_dangerous_patterns(self):
        """Test root scalar strings are validated like nested string payloads."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                middleware._validate_json_data("<script>")

            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_validate_request_with_real_rust_extension_when_installed(self):
        """Test the compiled Rust extension can be imported and used through middleware."""
        if os.getenv("REQUIRE_RUST") == "1":
            # Rust-required CI must fail if the built extension is missing.
            import importlib

            validation_rust = importlib.import_module("validation_middleware_rust")
        else:
            validation_rust = pytest.importorskip("validation_middleware_rust")

        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", validation_rust):
                middleware = ValidationMiddleware(app=None)

            class SafeRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            class DangerousRequest:
                path_params = {}
                query_params = {}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"<script>"}'

            await middleware._validate_request(SafeRequest())

            with pytest.raises(HTTPException, match="contains dangerous characters"):
                await middleware._validate_request(DangerousRequest())

    def test_real_rust_extension_rejects_root_scalar_json_when_installed(self):
        """Test Rust JSON validation matches Python for root scalar strings."""
        if os.getenv("REQUIRE_RUST") == "1":
            import importlib

            validation_rust = importlib.import_module("validation_middleware_rust")
        else:
            validation_rust = pytest.importorskip("validation_middleware_rust")

        validator = validation_rust.Validator(1000, [r"<script"], [], 10)

        assert validator.validate_json_data("<script>") == ("payload", "dangerous_pattern")
        assert validator.validate_json_bytes(b'"<script>"') == ("payload", "dangerous_pattern")
        with pytest.raises(validation_rust.InvalidJsonError):
            validator.validate_json_bytes(b"{")
        with pytest.raises(validation_rust.JsonDepthError):
            validation_rust.Validator(1000, [r"<script"], [], 10, 1).validate_json_bytes(b'{"nested": {"value": "safe"}}')

    def test_real_rust_extension_validates_allowed_roots_when_installed(self, tmp_path):
        """Test middleware path validation passes real allowed roots to Rust."""
        if os.getenv("REQUIRE_RUST") == "1":
            import importlib

            validation_rust = importlib.import_module("validation_middleware_rust")
        else:
            validation_rust = pytest.importorskip("validation_middleware_rust")

        allowed_root = tmp_path / "data"
        allowed_root.mkdir()
        child = allowed_root / "file.txt"
        child.write_text("safe", encoding="utf-8")
        sibling = tmp_path / "database"
        sibling.mkdir()
        sibling_child = sibling / "file.txt"
        sibling_child.write_text("unsafe", encoding="utf-8")

        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = [str(allowed_root)]
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 100
            mock_settings.environment = "production"

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", validation_rust):
                middleware = ValidationMiddleware(app=None)

            assert middleware.validate_resource_path(str(child)) == str(child.resolve())
            with pytest.raises(HTTPException, match="Path outside allowed roots") as exc_info:
                middleware.validate_resource_path(str(sibling_child))
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_validation_middleware_rust_parity_is_covered_in_unit_suite(self):
        """Test Rust/Python parity from the default unit-test suite when the extension is available."""
        if os.getenv("REQUIRE_RUST") == "1":
            import importlib

            validation_rust = importlib.import_module("validation_middleware_rust")
        else:
            validation_rust = pytest.importorskip("validation_middleware_rust")

        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"]
            mock_settings.max_param_length = 32
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", validation_rust):
                mock_settings.experimental_rust_validation_middleware_enabled = False
                python_middleware = ValidationMiddleware(app=None)
                mock_settings.experimental_rust_validation_middleware_enabled = True
                rust_middleware = ValidationMiddleware(app=None)

            class SafeRequest:
                path_params = {"id": "123"}
                query_params = {"q": "safe"}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"safe"}'

            class DangerousRequest:
                path_params = {"id": "123"}
                query_params = {"q": "safe"}
                headers = {"content-type": "application/json"}

                async def body(self):
                    return b'{"name":"<script>"}'

            await python_middleware._validate_request(SafeRequest())
            await rust_middleware._validate_request(SafeRequest())

            with pytest.raises(HTTPException) as python_exc:
                await python_middleware._validate_request(DangerousRequest())
            with pytest.raises(HTTPException) as rust_exc:
                await rust_middleware._validate_request(DangerousRequest())

            assert (python_exc.value.status_code, python_exc.value.detail) == (rust_exc.value.status_code, rust_exc.value.detail)
            assert python_middleware._validate_parameters_with_python([("q", "<script>")]) == rust_middleware._validate_parameters_with_rust([("q", "<script>")])

            python_response = await python_middleware._sanitize_response(Response(content="prefix\x00middle\x1fsuffix"))
            rust_response = await rust_middleware._sanitize_response(Response(content="prefix\x00middle\x1fsuffix"))
            assert python_response.body == rust_response.body

    def test_validate_json_data_uses_rust_extension_when_enabled(self):
        """Test JSON validation uses the Rust extension when explicitly enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            rust_module = MagicMock()
            rust_validator = MagicMock()
            rust_validator.validate_json_data.return_value = None
            rust_module.Validator.return_value = rust_validator

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", None):
                with patch("mcpgateway.middleware.validation_middleware.importlib.import_module", return_value=rust_module):
                    middleware = ValidationMiddleware(app=None)

            middleware._validate_json_data({"name": "safe"})

            rust_module.Validator.assert_called_once_with(1000, [r"<script"], [], mock_settings.max_path_depth, 1024)
            rust_validator.validate_json_data.assert_called_once_with({"name": "safe"})

    def test_validate_json_data_reuses_compiled_rust_validator(self):
        """Test Rust mode creates one compiled validator and reuses it across calls."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            rust_module = MagicMock()
            rust_validator = MagicMock()
            rust_validator.validate_json_data.return_value = None
            rust_module.Validator.return_value = rust_validator

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", None):
                with patch("mcpgateway.middleware.validation_middleware.importlib.import_module", return_value=rust_module):
                    middleware = ValidationMiddleware(app=None)

            middleware._validate_json_data({"name": "safe"})
            middleware._validate_json_data({"name": "still-safe"})

            rust_module.Validator.assert_called_once_with(1000, [r"<script"], [], mock_settings.max_path_depth, 1024)
            assert middleware._rust_validator is rust_validator
            assert rust_validator.validate_json_data.call_count == 2

    def test_validate_request_uses_rust_parameter_batch_when_enabled(self):
        """Test request validation uses the Rust parameter batch path when explicitly enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.return_value = None
            middleware._rust_validator = rust_validator

            middleware._validate_parameters([("id", "123"), ("q", "safe")])

            rust_validator.validate_parameters.assert_called_once_with([("id", "123"), ("q", "safe")])

    def test_validate_parameters_with_python_returns_max_length(self):
        """Test Python parameter batch validation reports max-length failures."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            assert middleware._validate_parameters_with_python([("name", "toolong")]) == ("name", "max_length")

    def test_validate_parameters_with_rust_falls_back_when_validator_build_fails(self):
        """Test Rust parameter batch validation falls back when no validator can be built."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validator = None

            with patch.object(middleware, "_build_rust_validator", return_value=None):
                assert middleware._validate_parameters_with_rust([("id", "<script>")]) == ("id", "dangerous_pattern")

    def test_validate_parameters_with_rust_reraises_http_exception(self):
        """Test Rust parameter batch validation does not swallow HTTPException."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_parameters.side_effect = HTTPException(status_code=422, detail="bad")
            middleware._rust_validator = rust_validator

            with pytest.raises(HTTPException, match="bad"):
                middleware._validate_parameters_with_rust([("id", "safe")])

    def test_validate_body_with_rust_raises_when_validator_handle_missing(self):
        """Test the direct Rust body helper fails fast if the handle is unavailable."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_json_bytes = None

            with pytest.raises(RuntimeError, match="rust validator unavailable"):
                middleware._validate_body_with_rust(b"{}")

    def test_validate_body_with_rust_uses_json_bytes_primitive(self):
        """Test the JSON body Rust path calls the primitive bytes validator."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_json_bytes = MagicMock(return_value=None)

            middleware._validate_body_with_rust(b"{}")

            middleware._rust_validate_json_bytes.assert_called_once_with(b"{}")

    def test_validate_body_with_rust_reraises_unmapped_value_errors(self):
        """Test the direct Rust body helper re-raises unexpected ValueError cases."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_json_bytes = MagicMock(side_effect=ValueError("boom"))

            with pytest.raises(ValueError, match="boom"):
                middleware._validate_body_with_rust(b"{}")

    def test_refresh_rust_validator_handles_returns_false_without_validator(self):
        """Test cached Rust callable refresh returns false when no validator exists."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validator = None

            assert middleware._refresh_rust_validator_handles() is False

    def test_validate_resource_path_uses_rust_extension_when_enabled(self):
        """Test resource path validation uses the Rust extension when explicitly enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_resource_path.return_value = "/safe/path"
            middleware._rust_validator = rust_validator
            middleware._rust_validate_resource_path = rust_validator.validate_resource_path

            assert middleware.validate_resource_path("/safe/path") == "/safe/path"
            rust_validator.validate_resource_path.assert_called_once_with("/safe/path")

    def test_validate_resource_path_falls_back_to_python_when_rust_handles_unavailable(self):
        """Test resource path validation falls back to Python if Rust handles stay unavailable."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validator = None

            with patch.object(middleware, "_build_rust_validator", return_value=None):
                assert middleware.validate_resource_path("relative/file.txt").endswith("relative/file.txt")

    def test_validate_resource_path_rust_failure_falls_back_to_python(self):
        """Test resource path validation falls back to Python when Rust raises unexpectedly."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validate_resource_path = MagicMock(side_effect=RuntimeError("boom"))

            assert middleware.validate_resource_path("relative/file.txt").endswith("relative/file.txt")

    @pytest.mark.asyncio
    async def test_sanitize_response_uses_rust_extension_when_enabled(self):
        """Test response sanitization uses the Rust extension when explicitly enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.sanitize_response_body.return_value = b"HelloWorld"
            middleware._rust_validator = rust_validator
            middleware._rust_sanitize_response_body = rust_validator.sanitize_response_body

            response = Response(content="Hello\x00World")
            sanitized = await middleware._sanitize_response(response)

            assert sanitized.body == b"HelloWorld"
            rust_validator.sanitize_response_body.assert_called_once()

    @pytest.mark.asyncio
    async def test_sanitize_response_builds_rust_handles_and_encodes_str_body(self):
        """Test response sanitization rebuilds Rust handles and encodes str bodies."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.sanitize_response_body.return_value = b"sanitized"
            middleware._rust_validator = None
            middleware._rust_sanitize_response_body = None

            with patch.object(middleware, "_build_rust_validator", return_value=rust_validator):
                response = Response(content="Hello")
                response.body = "Hello"  # exercise the explicit str -> bytes path
                sanitized = await middleware._sanitize_response(response)

            assert sanitized.body == b"sanitized"
            rust_validator.sanitize_response_body.assert_called_once_with(b"Hello")

    @pytest.mark.asyncio
    async def test_sanitize_response_falls_back_to_python_when_rust_handles_missing(self):
        """Test response sanitization uses Python when no Rust sanitizer is available."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validator = None
            middleware._rust_sanitize_response_body = None

            with patch.object(middleware, "_build_rust_validator", return_value=None):
                response = Response(content=b"Hello\x00World")
                sanitized = await middleware._sanitize_response(response)

            assert sanitized.body == b"HelloWorld"

    @pytest.mark.asyncio
    async def test_sanitize_response_falls_back_to_python_when_rust_sanitizer_fails(self):
        """Test response sanitization does not skip Python fallback after Rust failures."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = True
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.sanitize_response_body.side_effect = RuntimeError("boom")
            middleware._rust_validator = rust_validator
            middleware._rust_sanitize_response_body = rust_validator.sanitize_response_body

            response = Response(content=b"Hello\x00World")
            sanitized = await middleware._sanitize_response(response)

            assert sanitized.body == b"HelloWorld"
            assert middleware._rust_validator_unavailable is True

    def test_validate_json_data_rust_extension_falls_back_to_python_validation(self):
        """Test Rust mode falls back to Python validation when the extension cannot be loaded."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            middleware._rust_validator = None

            with patch.object(middleware, "_build_rust_validator", return_value=None):
                with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                    middleware._validate_json_data({"name": "<script>"})
            assert exc_info.value.status_code == 422

    def test_validate_json_data_with_rust_falls_back_after_non_depth_value_error(self):
        """Test Rust JSON validation falls back to Python for non-depth ValueError cases."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.side_effect = ValueError("boom")
            middleware._rust_validator = rust_validator

            assert middleware._validate_json_data_with_rust({"name": "<script>"}) == ("name", "dangerous_pattern")

    def test_validate_json_data_with_rust_falls_back_after_generic_exception(self):
        """Test Rust JSON validation falls back to Python for generic exceptions."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.side_effect = RuntimeError("boom")
            middleware._rust_validator = rust_validator

            assert middleware._validate_json_data_with_rust({"name": "<script>"}) == ("name", "dangerous_pattern")
            assert middleware._rust_validator_unavailable is True
            assert middleware._rust_validator is None

    def test_validate_json_data_with_missing_rust_extension_caches_the_first_miss(self):
        """Test repeated Rust misses fall back once without repeated import attempts."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.max_path_depth = 10
            mock_settings.environment = "production"

            with patch("mcpgateway.middleware.validation_middleware._RUST_VALIDATION_MODULE", None):
                with patch("mcpgateway.middleware.validation_middleware.importlib.import_module", side_effect=ModuleNotFoundError("missing")) as import_module:
                    middleware = ValidationMiddleware(app=None)

                    assert middleware._validate_json_data_with_rust({"name": "<script>"}) == ("name", "dangerous_pattern")
                    assert middleware._validate_json_data_with_rust({"name": "<script>"}) == ("name", "dangerous_pattern")

            assert import_module.call_count == 1

    def test_validate_json_data_with_rust_reraises_http_exception(self):
        """Test Rust JSON validation preserves HTTPException without fallback."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.side_effect = HTTPException(status_code=422, detail="bad")
            middleware._rust_validator = rust_validator

            with pytest.raises(HTTPException, match="bad"):
                middleware._validate_json_data_with_rust({"name": "safe"})

    def test_validate_json_data_rust_extension_respects_warn_only_mode(self):
        """Test Rust mode preserves warn-only behavior outside production."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.return_value = ("name", "dangerous_pattern")
            middleware._rust_validator = rust_validator

            middleware._validate_json_data({"name": "<script>"})

    def test_validate_json_data_rust_extension_maps_max_length_errors(self):
        """Test Rust mode maps max-length failures to HTTP 422 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.return_value = ("name", "max_length")
            middleware._rust_validator = rust_validator

            with pytest.raises(HTTPException, match="exceeds maximum length") as exc_info:
                middleware._validate_json_data({"name": "toolong"})

            assert exc_info.value.status_code == 422

    def test_validate_json_data_rust_extension_maps_depth_errors(self):
        """Test Rust mode maps Rust depth errors to HTTP 422 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_json_data.side_effect = JsonDepthError("JSON payload exceeds maximum supported nesting depth")
            middleware._rust_validator = rust_validator
            middleware._rust_json_depth_error = JsonDepthError

            with pytest.raises(HTTPException, match="exceeds maximum supported nesting depth") as exc_info:
                middleware._validate_json_data({"name": "safe"})

            assert exc_info.value.status_code == 422

    def test_validate_json_data_with_python_enforces_depth_limit(self):
        """Test Python JSON validation enforces the explicit depth guard."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException, match="maximum supported nesting depth"):
                middleware._validate_json_data_with_python({}, depth=1025)

    def test_validate_json_data_with_python_uses_configured_depth_limit(self):
        """Test Python JSON validation honors VALIDATION_MIDDLEWARE_MAX_JSON_DEPTH."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.validation_middleware_max_json_depth = 1
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException, match="maximum supported nesting depth"):
                middleware._validate_json_data_with_python({"nested": {"value": "safe"}})

    def test_validate_json_data_with_python_depth_limit_counts_containers_only(self):
        """Test scalar list items do not count as nested JSON containers."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.validation_middleware_max_json_depth = 1
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            assert middleware._validate_json_data_with_python([1, True, None]) is None
            with pytest.raises(HTTPException, match="maximum supported nesting depth"):
                middleware._validate_json_data_with_python([[1]])

    def test_validate_json_data_with_python_handles_deep_payload_iteratively(self):
        """Test Python fallback can enforce the default middleware JSON depth."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.validation_middleware_max_json_depth = 1024
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            payload: dict[str, Any] = {}
            cursor = payload
            for _ in range(1023):
                child: dict[str, Any] = {}
                cursor["nested"] = child
                cursor = child

            assert middleware._validate_json_data_with_python(payload) is None
            cursor["nested"] = {}

            with pytest.raises(HTTPException, match="maximum supported nesting depth"):
                middleware._validate_json_data_with_python(payload)

    def test_validate_json_data_with_python_returns_nested_dict_failure(self):
        """Test Python JSON validation returns nested dict failures."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            assert middleware._validate_json_data_with_python({"outer": {"name": "toolong"}}) == ("name", "max_length")

    def test_validate_json_data_with_python_returns_list_string_failure(self):
        """Test Python JSON validation returns direct list-item failures."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            assert middleware._validate_json_data_with_python(["toolong"]) == ("list_item", "max_length")

    def test_validate_json_data_with_python_returns_nested_list_failure(self):
        """Test Python JSON validation returns failures found inside nested lists."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            assert middleware._validate_json_data_with_python([{"name": "toolong"}]) == ("name", "max_length")

    def test_raise_validation_failure_warns_for_max_length_in_development(self):
        """Test warn-only max-length failures do not raise outside production."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)

            assert middleware._raise_validation_failure("name", "max_length") is None

    def test_raise_validation_failure_uses_generic_message_for_unknown_errors(self):
        """Test unknown validation error types map to the generic HTTP 422 message."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException, match="failed validation") as exc_info:
                middleware._raise_validation_failure("name", "other")

            assert exc_info.value.status_code == 422

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

    def test_validate_resource_path_rejects_sibling_prefix_of_allowed_root(self, tmp_path):
        """Test allowed root matching is component-aware, not string-prefix based."""
        allowed_root = tmp_path / "data"
        allowed_root.mkdir()
        sibling = tmp_path / "database"
        sibling.mkdir()
        candidate = sibling / "file.txt"

        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = [str(allowed_root)]
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)

            with pytest.raises(HTTPException) as exc_info:
                middleware.validate_resource_path(str(candidate))

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

    def test_validate_resource_path_with_rust_maps_value_error_to_http_400(self):
        """Test Rust resource-path failures become HTTP 400 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_path_depth = 100

            middleware = ValidationMiddleware(app=None)
            rust_validator = MagicMock()
            rust_validator.validate_resource_path.side_effect = ValueError("invalid_path: Invalid path")
            middleware._rust_validator = rust_validator
            middleware._rust_validate_resource_path = rust_validator.validate_resource_path

            with pytest.raises(HTTPException, match="invalid_path: Invalid path") as exc_info:
                middleware.validate_resource_path("bad\0path")

            assert exc_info.value.status_code == 400

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
