# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_baggage_middleware_main_flow.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for baggage_middleware.py main __call__ flow (lines 210-237).

This module targets complete coverage of the main middleware request processing flow.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


class TestBaggageMiddlewareMainCallFlow:
    """Tests for the main __call__ method flow (lines 210-237)."""

    @pytest.mark.asyncio
    async def test_full_flow_with_baggage_extraction_and_context_lines_210_238(self):
        """Test complete flow: extract baggage, set context, call app, detach (lines 210-238)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig, HeaderMapping
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        # Mock app
        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        # Create config with header mapping
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Request-ID", "request.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        # Create scope with baggage and custom headers
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"baggage", b"upstream=value1"),
                (b"x-request-id", b"req-123"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        # Mock OTEL components
        mock_context = MagicMock()
        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            mock_baggage.set_baggage.return_value = mock_context
            with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", return_value=mock_context):
                with patch("mcpgateway.middleware.baggage_middleware.otel_attach", return_value="test_token") as mock_attach:
                    with patch("mcpgateway.middleware.baggage_middleware.otel_detach") as mock_detach:
                        # Call middleware
                        await middleware(scope, mock_receive, mock_send)

                        # Verify app was called
                        assert app_called

                        # Verify context was attached
                        assert mock_attach.called

                        # Verify detach was called in finally block (line 237-238)
                        mock_detach.assert_called_once_with("test_token")

    @pytest.mark.asyncio
    async def test_flow_with_empty_baggage_no_context_set_lines_226_228(self):
        """Test flow when no baggage is extracted, context not set (lines 226-228)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        # Scope with no baggage headers
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        with patch("mcpgateway.middleware.baggage_middleware.otel_detach") as mock_detach:
            # Call middleware
            await middleware(scope, mock_receive, mock_send)

            # Verify app was called
            assert app_called

            # Verify detach was NOT called (no token set)
            mock_detach.assert_not_called()

    @pytest.mark.asyncio
    async def test_flow_exception_during_extraction_continues_lines_230_235(self):
        """Test that exception during extraction is caught and request continues (lines 230-235)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"baggage", b"key=value")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        # Mock _extract_headers_from_scope to raise exception
        original_extract = middleware._extract_headers_from_scope

        def failing_extract(scope):
            raise RuntimeError("Extraction failed")

        middleware._extract_headers_from_scope = failing_extract

        # Call middleware - should catch exception and continue
        await middleware(scope, mock_receive, mock_send)

        # Verify app was still called despite exception (line 235)
        assert app_called

    @pytest.mark.asyncio
    async def test_flow_non_http_scope_passthrough_lines_210_212(self):
        """Test that non-HTTP requests pass through without processing (lines 210-212)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        middleware = BaggageMiddleware(mock_app)

        # WebSocket scope (not HTTP)
        scope = {
            "type": "websocket",
            "path": "/ws",
        }

        async def mock_receive():
            return {}

        async def mock_send(message):
            pass

        # Call middleware
        await middleware(scope, mock_receive, mock_send)

        # Verify app was called
        assert app_called

    @pytest.mark.asyncio
    async def test_flow_disabled_config_passthrough_lines_213_215(self):
        """Test that disabled config causes passthrough without processing (lines 213-215)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        # Disabled config
        config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"baggage", b"key=value")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        with patch("mcpgateway.middleware.baggage_middleware.otel_detach") as mock_detach:
            # Call middleware
            await middleware(scope, mock_receive, mock_send)

            # Verify app was called
            assert app_called

            # Verify no baggage processing occurred
            mock_detach.assert_not_called()

    @pytest.mark.asyncio
    async def test_flow_with_upstream_and_header_baggage_merge_lines_217_223(self):
        """Test merging of upstream baggage and header-derived baggage (lines 217-223)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig, HeaderMapping
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app_called = False

        async def mock_app_call(scope, receive, send):
            nonlocal app_called
            app_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Custom", "custom.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        # Scope with both upstream baggage and custom header
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"baggage", b"upstream-key=upstream-value"),
                (b"x-custom", b"custom-value"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        messages = []

        async def mock_send(message):
            messages.append(message)

        # Track calls to merge and extraction methods
        extract_existing_called = False
        extract_headers_called = False
        merge_called = False

        original_extract_existing = middleware._extract_existing_baggage
        original_extract_headers = middleware._extract_headers_from_scope

        def track_extract_existing(headers, config):
            nonlocal extract_existing_called
            extract_existing_called = True
            return original_extract_existing(headers, config)

        def track_extract_headers(scope):
            nonlocal extract_headers_called
            extract_headers_called = True
            return original_extract_headers(scope)

        middleware._extract_existing_baggage = track_extract_existing
        middleware._extract_headers_from_scope = track_extract_headers

        with patch("mcpgateway.middleware.baggage_middleware.merge_baggage") as mock_merge:
            mock_merge.side_effect = lambda h, e: {**e, **h}  # Simple merge
            with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
                with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", return_value=MagicMock()):
                    with patch("mcpgateway.middleware.baggage_middleware.otel_attach", return_value="token"):
                        with patch("mcpgateway.middleware.baggage_middleware.otel_detach"):
                            # Call middleware
                            await middleware(scope, mock_receive, mock_send)

                            # Verify app was called
                            assert app_called

                            # Verify the merge flow was executed (lines 217-223)
                            assert extract_headers_called, "Headers should be extracted"
                            assert extract_existing_called, "Existing baggage should be extracted"
                            assert mock_merge.called, "Baggage should be merged"

    @pytest.mark.asyncio
    async def test_flow_finally_block_detach_even_on_app_exception_lines_234_238(self):
        """Test that detach is called in finally block even if app raises (lines 234-238)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig, HeaderMapping
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        # Mock app that raises exception
        async def mock_app_call(scope, receive, send):
            raise RuntimeError("App error")

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        # Config with mapping so baggage will actually be set
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Test", "test.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(mock_app, config=config)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [(b"x-test", b"test-value")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            pass

        # Mock OTEL
        mock_context = MagicMock()
        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            mock_baggage.set_baggage.return_value = mock_context
            with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", return_value=mock_context):
                with patch("mcpgateway.middleware.baggage_middleware.otel_attach", return_value="token"):
                    with patch("mcpgateway.middleware.baggage_middleware.otel_detach") as mock_detach:
                        # Call middleware - should raise but detach should still be called
                        with pytest.raises(RuntimeError, match="App error"):
                            await middleware(scope, mock_receive, mock_send)

                        # Verify detach was called in finally block despite exception
                        mock_detach.assert_called_once_with("token")
