# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability_baggage_exceptions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability.py baggage exception paths.

This module contains targeted tests for specific uncovered exception handling
lines in mcpgateway/observability.py related to baggage operations.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


class TestObservabilityBaggageExceptions:
    """Tests for observability.py baggage exception handling."""

    def test_inject_trace_context_headers_exception_lines_603_604(self):
        """Test exception handling in inject_trace_context_headers (lines 603-604)."""
        # First-Party
        from mcpgateway.observability import inject_trace_context_headers

        mock_settings = MagicMock()
        mock_settings.otel_baggage_enabled = True
        mock_settings.otel_baggage_propagate_to_external = True

        with patch("mcpgateway.observability.get_settings", return_value=mock_settings):
            with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
                with patch("mcpgateway.observability.otel_context_active", return_value=True):
                    with patch("mcpgateway.observability.otel_inject"):
                        with patch("mcpgateway.observability.otel_baggage") as mock_baggage:
                            # Return baggage dict, but make sanitize_baggage_for_propagation raise
                            mock_baggage.get_all.return_value = {"key1": "value1"}

                            with patch("mcpgateway.baggage.sanitize_baggage_for_propagation", side_effect=RuntimeError("Sanitization failed")):
                                with patch("mcpgateway.observability.logger") as mock_logger:
                                    # Call should not raise, but should log the exception
                                    result = inject_trace_context_headers()

                                    # Should return dict (not empty, has trace context)
                                    assert isinstance(result, dict)

                                    # Should have logged the exception (line 604)
                                    debug_calls = [call for call in mock_logger.debug.call_args_list if len(call[0]) > 0 and "Failed to inject baggage into outbound headers" in call[0][0]]
                                    assert len(debug_calls) == 1

    @pytest.mark.skip(reason="Lines 767-773 are covered by integration tests - complex async middleware path")
    @pytest.mark.asyncio
    async def test_request_middleware_baggage_exception_lines_767_773(self):
        """Test baggage injection exception in request middleware (lines 767-773).

        Note: This exception path is tested via integration tests in tests/integration/test_baggage_middleware.py
        which properly exercise the full ASGI middleware stack with real async context.
        """

    def test_create_span_baggage_exception_lines_1168_1171(self):
        """Test baggage injection exception in create_span (lines 1168-1171)."""
        # First-Party
        from mcpgateway.observability import create_span

        mock_settings = MagicMock()
        mock_settings.otel_baggage_enabled = True

        with patch("mcpgateway.observability.get_settings", return_value=mock_settings):
            with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
                with patch("mcpgateway.observability.otel_baggage") as mock_baggage:
                    # Make get_all() raise to trigger exception
                    mock_baggage.get_all.side_effect = RuntimeError("Baggage error")

                    with patch("mcpgateway.observability._TRACER") as mock_tracer:
                        mock_span_context = MagicMock()
                        mock_tracer.start_as_current_span.return_value = mock_span_context

                        with patch("mcpgateway.observability.logger") as mock_logger:
                            # Call create_span which should handle the exception
                            span = create_span("test_span", attributes={"key": "value"})

                            # Should have logged the exception at warning level (line 1170)
                            warning_calls = [call for call in mock_logger.warning.call_args_list if len(call[0]) > 0 and "Failed to inject baggage into span attributes" in call[0][0]]
                            assert len(warning_calls) == 1

                            # Should still return a span context
                            assert span is not None
