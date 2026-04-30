# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_baggage_middleware_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for baggage_middleware.py coverage gaps.

This module contains targeted tests for specific uncovered lines in
mcpgateway/middleware/baggage_middleware.py to improve coverage.
"""

# Standard
from unittest.mock import MagicMock, patch

# Note: Lines 38-42 (ImportError handling for OpenTelemetry) are difficult to test
# in isolation without breaking the test environment. These lines are defensive
# fallback code that ensures the middleware can load even without OpenTelemetry.
# The integration tests verify the middleware works correctly when OTEL is available.


class TestBaggageMiddlewareConfigLoading:
    """Tests for configuration loading paths."""

    def test_config_load_exception_creates_disabled_config_lines_93_102(self):
        """Test that config load exception creates disabled fallback (lines 93-102)."""
        # First-Party
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        middleware = BaggageMiddleware(app, config=None)

        # Mock BaggageConfig.from_settings to raise exception
        with patch("mcpgateway.baggage.BaggageConfig.from_settings", side_effect=Exception("Config load failed")):
            with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                config = middleware._ensure_config_loaded()

                # Should log error
                assert mock_logger.error.called
                # Should create disabled fallback config
                assert config.enabled is False
                assert config.mappings == []

    def test_config_already_loaded_skips_reload_line_83(self):
        """Test that already loaded config is not reloaded (line 83-85)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig, HeaderMapping
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        test_config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Test", "test.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=test_config)

        # First call loads config
        config1 = middleware._ensure_config_loaded()
        assert config1 is test_config

        # Second call should return same config without reloading
        with patch("mcpgateway.baggage.BaggageConfig.from_settings") as mock_from_settings:
            config2 = middleware._ensure_config_loaded()
            # Should not call from_settings again
            assert not mock_from_settings.called
            assert config2 is test_config


class TestBaggageMiddlewareHeaderExtraction:
    """Tests for header extraction error paths."""

    def test_extract_headers_decode_exception_lines_132_134(self):
        """Test header extraction handles decode exceptions (lines 132-134)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=config)

        # Create scope with headers that will cause AttributeError
        # (non-bytes objects that don't have .decode())
        scope = {
            "type": "http",
            "headers": [
                (None, b"value"),  # None doesn't have .decode()
                (b"valid-key", "not-bytes"),  # String doesn't have .decode()
            ],
        }

        with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
            headers = middleware._extract_headers_from_scope(scope)
            # Should log debug message about decode failure
            assert mock_logger.debug.called
            # Should return empty or partial headers dict (skips bad headers)
            assert isinstance(headers, dict)


class TestBaggageMiddlewareExistingBaggage:
    """Tests for existing baggage extraction."""

    def test_extract_existing_baggage_parse_exception_lines_154_156(self):
        """Test existing baggage extraction handles parse exceptions (lines 154-156)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=config)

        # Headers with malformed baggage
        headers = {"baggage": "invalid baggage format"}

        with patch("mcpgateway.middleware.baggage_middleware.parse_w3c_baggage_header", side_effect=Exception("Parse failed")):
            with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                result = middleware._extract_existing_baggage(headers, config)
                # Should log debug message
                assert mock_logger.debug.called
                # Should return empty dict
                assert result == {}


class TestBaggageMiddlewareContextSetting:
    """Tests for OpenTelemetry context setting."""

    def test_set_baggage_otel_not_available_lines_172(self):
        """Test baggage context setting when OTEL not available (line 172)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=config)

        baggage = {"test.key": "test-value"}

        # Mock OTEL as unavailable
        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", None):
            with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                result = middleware._set_baggage_in_context(baggage)
                # Should log debug message
                assert mock_logger.debug.called
                # Should return None
                assert result is None

    def test_set_baggage_empty_dict_lines_180_182(self):
        """Test baggage context setting with empty baggage (lines 180-182)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=config)

        # Empty baggage should return None immediately
        result = middleware._set_baggage_in_context({})
        assert result is None

    def test_set_baggage_exception_lines_199_200(self):
        """Test baggage context setting handles exceptions (lines 199-200)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig
        from mcpgateway.middleware.baggage_middleware import BaggageMiddleware

        app = MagicMock()
        config = BaggageConfig(
            enabled=True,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )
        middleware = BaggageMiddleware(app, config=config)

        baggage = {"test.key": "test-value"}

        # Mock otel_get_current to raise exception
        mock_otel_baggage = MagicMock()
        mock_otel_get_current = MagicMock(side_effect=Exception("Context error"))

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", mock_otel_baggage):
            with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", mock_otel_get_current):
                with patch("mcpgateway.middleware.baggage_middleware.otel_attach", MagicMock()):
                    with patch("mcpgateway.middleware.baggage_middleware.logger") as mock_logger:
                        result = middleware._set_baggage_in_context(baggage)
                        # Should log warning
                        assert mock_logger.warning.called
                        # Should return None
                        assert result is None
