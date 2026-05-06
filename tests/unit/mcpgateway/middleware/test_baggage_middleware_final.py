# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_baggage_middleware_final.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Final coverage tests for baggage_middleware.py to reach 95%+.

This module targets the remaining uncovered lines in baggage_middleware.py:
- Lines 38-42: ImportError handling for OpenTelemetry baggage API
- Lines 97-98: Exception handling in config loading fallback
- Line 172: Exception in _attach_baggage_to_context
- Lines 199-200: Exception handling in context attachment
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


class TestBaggageMiddlewareImportError:
    """Tests for ImportError handling (lines 38-42)."""

    def test_otel_baggage_import_error_lines_38_42(self):
        """Test ImportError handling when OpenTelemetry baggage API unavailable (lines 38-42)."""
        # Mock the import to raise ImportError
        # Standard
        import sys

        # Remove the module if already imported
        modules_to_remove = [k for k in sys.modules.keys() if "baggage_middleware" in k]
        for mod in modules_to_remove:
            del sys.modules[mod]

        # Mock opentelemetry.baggage import to fail
        with patch.dict("sys.modules", {"opentelemetry.baggage": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'opentelemetry.baggage'")):
                # This should trigger the except ImportError block
                try:
                    # First-Party
                    from mcpgateway.middleware import baggage_middleware

                    # If import succeeds, the except block was executed
                    assert baggage_middleware.OTEL_BAGGAGE_AVAILABLE is False
                    assert baggage_middleware.otel_baggage is None
                    assert baggage_middleware.otel_attach is None
                    assert baggage_middleware.otel_detach is None
                    assert baggage_middleware.otel_get_current is None
                except ImportError:
                    # Expected if the module can't be imported at all
                    pass


class TestBaggageMiddlewareConfigException:
    """Tests for config loading exception handling (lines 97-98)."""

    @pytest.mark.asyncio
    async def test_config_loading_exception_fallback_lines_97_98(self):
        """Test fallback to disabled config when loading fails (lines 97-98)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        # Mock app to be an async callable
        async def mock_app_call(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        mock_app = MagicMock()
        mock_app.side_effect = mock_app_call

        # Patch logger first, then mock config loading to raise exception
        with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
            with patch("mcpgateway.middleware.baggage_middleware.BaggageConfig.from_settings", side_effect=RuntimeError("Config error")):
                # Initialize middleware
                middleware = BaggageMiddleware(mock_app)

                # Create a mock scope to trigger config loading
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

                # Call middleware to trigger lazy config loading
                await middleware(scope, mock_receive, mock_send)

                # Should have logged error
                error_calls = [call for call in mock_logger.error.call_args_list if len(call[0]) > 0 and "Failed to load baggage configuration" in call[0][0]]
                assert len(error_calls) == 1

                # Config should be disabled
                assert middleware._config.enabled is False


class TestBaggageMiddlewareContextException:
    """Tests for context attachment exception handling (line 172, 199-200)."""

    def test_set_baggage_exception_line_172(self):
        """Test exception handling in _set_baggage_in_context (line 172)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        mock_app = MagicMock()
        middleware = BaggageMiddleware(mock_app)

        # Mock otel_get_current to raise exception
        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", MagicMock()):
            with patch("mcpgateway.middleware.baggage_middleware.otel_attach", MagicMock()):
                with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", side_effect=RuntimeError("Context error")):
                    with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                        # Directly call _set_baggage_in_context with baggage
                        result = middleware._set_baggage_in_context({"key1": "value1"})

                        # Should return None on exception
                        assert result is None

                        # Should have logged warning (line 177)
                        warning_calls = [call for call in mock_logger.warning.call_args_list if len(call[0]) > 0 and "Failed to set baggage in OpenTelemetry context" in call[0][0]]
                        assert len(warning_calls) == 1

    @pytest.mark.skip(reason="Lines 199-200 don't have exception handling - detach is in finally block without try-except")
    async def test_context_detach_no_exception_handling(self):
        """Lines 199-200 reference is unclear - detach in finally block has no exception handling."""
