# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_validation_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the validation middleware.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.validation_middleware import ValidationMiddleware, is_path_traversal
from mcpgateway.services.validation_sidecar_client import (
    ValidationSidecarProtocolError,
    ValidationSidecarTimeoutError,
    ValidationSidecarTransportError,
    ValidationSidecarValidationError,
)


class _JSONBodyRequest:
    """Minimal request stub for exercising JSON body validation branches."""

    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        """Store body bytes and expose the small interface the middleware expects."""
        self._body = body
        self.path_params = {}
        self.query_params = {}
        self.headers = {"content-type": content_type}

    async def body(self) -> bytes:
        """Return the configured body bytes."""
        return self._body


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

    def test_validate_json_data_uses_legacy_rust_when_sidecar_is_disabled(self):
        """Test JSON validation still uses the legacy PyO3 path when the sidecar is disabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_sidecar_enabled = False
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_module = MagicMock()
            rust_module.validate_json_data.return_value = None

            with patch.object(middleware, "_load_rust_validation_module", return_value=rust_module):
                middleware._validate_json_data({"name": "safe"})

            rust_module.validate_json_data.assert_called_once_with({"name": "safe"}, 1000, [r"<script"])

    @pytest.mark.asyncio
    async def test_validate_request_uses_sidecar_only_when_both_gates_are_enabled(self, mock_request):
        """Test the sidecar path only activates when both middleware gates are enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            sidecar_validate = AsyncMock(return_value=None)
            parsed_validate = AsyncMock(return_value=None)

            middleware._validate_json_body_with_sidecar = sidecar_validate  # type: ignore[method-assign]
            middleware._validate_json_data_async = parsed_validate  # type: ignore[method-assign]

            request = _JSONBodyRequest(b'{"name":"safe"}')
            await middleware._validate_request(request)

            sidecar_validate.assert_awaited_once_with(b'{"name":"safe"}')
            parsed_validate.assert_not_awaited()

        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            sidecar_validate = AsyncMock(return_value=None)
            parsed_validate = AsyncMock(return_value=None)

            middleware._validate_json_body_with_sidecar = sidecar_validate  # type: ignore[method-assign]
            middleware._validate_json_data_async = parsed_validate  # type: ignore[method-assign]

            request = _JSONBodyRequest(b'{"name":"safe"}')
            await middleware._validate_request(request)

            sidecar_validate.assert_not_awaited()
            parsed_validate.assert_awaited_once_with({"name": "safe"})

    @pytest.mark.asyncio
    async def test_validate_request_prefers_sidecar_over_legacy_rust(self):
        """Test the sidecar backend takes precedence over the legacy PyO3 flag."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            sidecar_validate = AsyncMock(return_value=None)

            middleware._validate_json_body_with_sidecar = sidecar_validate  # type: ignore[method-assign]
            middleware._load_rust_validation_module = MagicMock(side_effect=AssertionError("legacy path should not be used"))  # type: ignore[method-assign]

            request = _JSONBodyRequest(b'{"name":"safe"}')
            await middleware._validate_request(request)

            sidecar_validate.assert_awaited_once_with(b'{"name":"safe"}')

    @pytest.mark.asyncio
    async def test_sidecar_validation_failures_are_warn_only_in_development(self):
        """Test warn-only mode still swallows ordinary sidecar validation failures in development."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            middleware._validate_json_body_with_sidecar = AsyncMock(side_effect=HTTPException(status_code=422, detail="Parameter name exceeds maximum length"))  # type: ignore[method-assign]

            async def call_next(req):
                return Response("ok")

            response = await middleware.dispatch(_JSONBodyRequest(b'{"name":"toolong"}'), call_next)
            assert response.body == b"ok"

    @pytest.mark.asyncio
    async def test_sidecar_validation_failures_still_raise_in_strict_development(self):
        """Test ordinary sidecar validation failures still raise when strict mode stays enabled."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            middleware._validate_json_body_with_sidecar = AsyncMock(side_effect=HTTPException(status_code=422, detail="Parameter name exceeds maximum length"))  # type: ignore[method-assign]

            async def call_next(req):
                return Response("ok")

            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(_JSONBodyRequest(b'{"name":"toolong"}'), call_next)

            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_sidecar_transport_failures_return_503(self):
        """Test sidecar transport failures stay fatal even in warn-only mode."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            middleware._validate_json_body_with_sidecar = AsyncMock(side_effect=HTTPException(status_code=503, detail="Validation sidecar is not configured"))  # type: ignore[method-assign]

            async def call_next(req):
                return Response("ok")

            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(_JSONBodyRequest(b'{"name":"safe"}'), call_next)

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_sidecar_invalid_json_verdict_maps_to_422(self):
        """Test sidecar invalid-json validation verdicts map to HTTP 422 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            fake_client = MagicMock()
            fake_client.validate_json_body = AsyncMock(
                side_effect=ValidationSidecarValidationError(
                    "Request body contains invalid JSON",
                    key="payload",
                    error_type="invalid_json",
                    detail="Request body contains invalid JSON",
                )
            )
            middleware._validation_sidecar_client = fake_client

            with pytest.raises(HTTPException) as exc_info:
                await middleware._validate_json_body_with_sidecar(b'{"name":"safe"}')

            assert exc_info.value.status_code == 422
            assert "failed validation" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sidecar_malformed_response_maps_to_503(self):
        """Test malformed sidecar protocol responses fail closed with HTTP 503."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            fake_client = MagicMock()
            fake_client.validate_json_body = AsyncMock(side_effect=ValidationSidecarProtocolError("Malformed sidecar response: invalid JSON"))
            middleware._validation_sidecar_client = fake_client

            with pytest.raises(HTTPException) as exc_info:
                await middleware._validate_json_body_with_sidecar(b'{"name":"safe"}')

            assert exc_info.value.status_code == 503
            assert "Malformed sidecar response" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sidecar_malformed_response_is_not_warn_only_in_development(self):
        """Test malformed sidecar responses stay fatal even when warn-only mode is active."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            middleware._validate_json_body_with_sidecar = AsyncMock(side_effect=HTTPException(status_code=503, detail="Malformed sidecar response: invalid JSON"))  # type: ignore[method-assign]

            async def call_next(req):
                return Response("ok")

            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(_JSONBodyRequest(b'{"name":"safe"}'), call_next)

            assert exc_info.value.status_code == 503

    @pytest.mark.parametrize(
        "sidecar_error",
        [ValidationSidecarTransportError("connect failed"), ValidationSidecarTimeoutError("timed out waiting for sidecar")],
    )
    @pytest.mark.asyncio
    async def test_sidecar_transport_and_readiness_failures_map_to_503(self, sidecar_error):
        """Test sidecar transport and readiness errors map to HTTP 503 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.experimental_rust_validation_middleware_enabled = False
            mock_settings.experimental_rust_validation_sidecar_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            fake_client = MagicMock()
            fake_client.validate_json_body = AsyncMock(side_effect=sidecar_error)
            middleware._validation_sidecar_client = fake_client

            with pytest.raises(HTTPException) as exc_info:
                await middleware._validate_json_body_with_sidecar(b'{"name":"safe"}')

            assert exc_info.value.status_code == 503

    def test_validate_json_data_rust_sidecar_falls_back_to_python_validation(self):
        """Test Rust mode falls back to Python validation when the sidecar cannot be loaded."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)

            with patch.object(middleware, "_load_rust_validation_module", side_effect=ModuleNotFoundError("missing sidecar")):
                with pytest.raises(HTTPException, match="contains dangerous characters") as exc_info:
                    middleware._validate_json_data({"name": "<script>"})
            assert exc_info.value.status_code == 422

    def test_validate_json_data_rust_sidecar_respects_warn_only_mode(self):
        """Test Rust mode preserves warn-only behavior outside production."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.validation_strict = False
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = [r"<script"]
            mock_settings.max_param_length = 1000
            mock_settings.environment = "development"

            middleware = ValidationMiddleware(app=None)
            rust_module = MagicMock()
            rust_module.validate_json_data.return_value = ("name", "dangerous_pattern")

            with patch.object(middleware, "_load_rust_validation_module", return_value=rust_module):
                middleware._validate_json_data({"name": "<script>"})

    def test_validate_json_data_rust_sidecar_maps_max_length_errors(self):
        """Test Rust mode maps max-length failures to HTTP 422 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 5
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_module = MagicMock()
            rust_module.validate_json_data.return_value = ("name", "max_length")

            with patch.object(middleware, "_load_rust_validation_module", return_value=rust_module):
                with pytest.raises(HTTPException, match="exceeds maximum length") as exc_info:
                    middleware._validate_json_data({"name": "toolong"})

            assert exc_info.value.status_code == 422

    def test_validate_json_data_rust_sidecar_maps_depth_errors(self):
        """Test Rust mode maps sidecar depth errors to HTTP 422 responses."""
        with patch("mcpgateway.middleware.validation_middleware.settings") as mock_settings:
            mock_settings.experimental_validate_io = True
            mock_settings.experimental_rust_validation_middleware_enabled = True
            mock_settings.validation_middleware_enabled = True
            mock_settings.validation_strict = True
            mock_settings.sanitize_output = False
            mock_settings.allowed_roots = []
            mock_settings.dangerous_patterns = []
            mock_settings.max_param_length = 1000
            mock_settings.environment = "production"

            middleware = ValidationMiddleware(app=None)
            rust_module = MagicMock()
            rust_module.validate_json_data.side_effect = ValueError("JSON payload exceeds maximum supported nesting depth")

            with patch.object(middleware, "_load_rust_validation_module", return_value=rust_module):
                with pytest.raises(HTTPException, match="exceeds maximum supported nesting depth") as exc_info:
                    middleware._validate_json_data({"name": "safe"})

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
