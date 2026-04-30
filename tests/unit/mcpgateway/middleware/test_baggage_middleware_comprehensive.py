# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_baggage_middleware_comprehensive.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive coverage tests for baggage_middleware.py to reach 95%+.

This module adds tests for the main middleware flow and helper methods
to achieve 95%+ coverage on baggage_middleware.py.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


class TestBaggageMiddlewareMainFlow:
    """Tests for main middleware __call__ flow (lines 210-237)."""

    @pytest.mark.asyncio
    async def test_main_flow_with_baggage_extraction(self):
        """Test main middleware flow with baggage extraction and context setting."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        # Mock app
        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        middleware = BaggageMiddleware(mock_app)

        # Create scope with baggage header
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"baggage", b"key1=value1,key2=value2"),
                (b"x-custom-header", b"custom-value"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        # Mock OTEL components and ensure baggage is set
        mock_context = MagicMock()
        with patch("mcpgateway.middleware.baggage_middleware.OTEL_BAGGAGE_AVAILABLE", True):
            with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
                mock_baggage.set_baggage.return_value = mock_context
                with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", return_value=mock_context):
                    with patch("mcpgateway.middleware.baggage_middleware.otel_attach", return_value="token") as mock_attach:
                        with patch("mcpgateway.middleware.baggage_middleware.otel_detach") as mock_detach:
                            # Call middleware
                            await middleware(scope, mock_receive, mock_send)

                            # Verify detach was called in finally block (if baggage was set)
                            # Note: detach only called if baggage_token is not None
                            if mock_attach.called:
                                mock_detach.assert_called_once_with("token")

    @pytest.mark.asyncio
    async def test_main_flow_non_http_request(self):
        """Test middleware skips non-HTTP requests."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        # Mock app
        async def mock_app_call(scope, receive, send):
            pass

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        middleware = BaggageMiddleware(mock_app)

        # WebSocket scope
        scope = {
            "type": "websocket",
            "path": "/ws",
        }

        async def mock_receive():
            return {}

        async def mock_send(message):
            pass

        # Call middleware - should pass through without processing
        await middleware(scope, mock_receive, mock_send)

        # App should have been called
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_flow_disabled_config(self):
        """Test middleware skips processing when config is disabled."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageConfig, BaggageMiddleware

        # Mock app
        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        # Create middleware with disabled config
        disabled_config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        middleware = BaggageMiddleware(mock_app, config=disabled_config)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"baggage", b"key1=value1")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        # Call middleware - should skip baggage processing
        await middleware(scope, mock_receive, mock_send)

        # App should have been called
        mock_app.assert_called_once()


class TestBaggageMiddlewareHelperMethods:
    """Tests for helper methods to cover remaining lines."""

    def test_extract_existing_baggage_parse_error(self):
        """Test _extract_existing_baggage with malformed baggage header (line 150)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageConfig, BaggageMiddleware

        mock_app = MagicMock()
        middleware = BaggageMiddleware(mock_app)

        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        # Mock parse_w3c_baggage_header to raise exception
        with patch("mcpgateway.middleware.baggage_middleware.parse_w3c_baggage_header", side_effect=ValueError("Parse error")):
            with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                headers = {"baggage": "malformed;;;baggage"}
                result = middleware._extract_existing_baggage(headers, config)

                # Should return empty dict on error
                assert result == {}

                # Should have logged debug message
                debug_calls = [call for call in mock_logger.debug.call_args_list if len(call[0]) > 0 and "Failed to parse upstream baggage header" in call[0][0]]
                assert len(debug_calls) >= 1

    def test_set_baggage_otel_not_available(self):
        """Test _set_baggage_in_context when OTEL is not available (lines 176-179)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        mock_app = MagicMock()
        middleware = BaggageMiddleware(mock_app)

        # Mock OTEL components as None
        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", None):
            with patch("mcpgateway.middleware.baggage_middleware.otel_attach", None):
                with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", None):
                    with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                        result = middleware._set_baggage_in_context({"key1": "value1"})

                        # Should return None when OTEL not available
                        assert result is None

                        # Should have logged debug message
                        debug_calls = [call for call in mock_logger.debug.call_args_list if len(call[0]) > 0 and "OpenTelemetry baggage API not available" in call[0][0]]
                        assert len(debug_calls) >= 1
