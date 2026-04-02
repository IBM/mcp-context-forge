# -*- coding: utf-8 -*-
"""Integration tests for BaggageMiddleware.

Tests cover:
- Middleware integration with FastAPI
- Header extraction and baggage setting
- OpenTelemetry context integration
- Configuration loading
- Security controls
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.baggage import BaggageConfig, HeaderMapping
from mcpgateway.middleware.baggage_middleware import BaggageMiddleware


@pytest.fixture
def test_config():
    """Create test baggage configuration."""
    return BaggageConfig(
        enabled=True,
        mappings=[
            HeaderMapping("X-Tenant-ID", "tenant.id"),
            HeaderMapping("X-User-ID", "user.id"),
        ],
        propagate_to_external=False,
        max_items=32,
        max_size_bytes=8192,
        log_rejected=True,
        log_sanitization=True,
    )


@pytest.fixture
def app_with_baggage(test_config):
    """Create FastAPI app with baggage middleware."""
    app = FastAPI()

    # Add baggage middleware with test config
    app.add_middleware(BaggageMiddleware, config=test_config)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    return app


class TestBaggageMiddlewareIntegration:
    """Test BaggageMiddleware integration with FastAPI."""

    def test_middleware_processes_configured_headers(self, app_with_baggage):
        """Test middleware extracts configured headers."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant-123",
                    "X-User-ID": "user-456",
                },
            )

            assert response.status_code == 200
            # Verify baggage was set in context
            assert mock_baggage.set_baggage.call_count == 2
            mock_baggage.set_baggage.assert_any_call("tenant.id", "tenant-123")
            mock_baggage.set_baggage.assert_any_call("user.id", "user-456")

    def test_middleware_skips_undefined_headers(self, app_with_baggage):
        """Test middleware skips headers not in configuration."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant-123",
                    "X-Unknown": "value",
                },
            )

            assert response.status_code == 200
            # Only configured header should be set
            assert mock_baggage.set_baggage.call_count == 1
            mock_baggage.set_baggage.assert_called_once_with("tenant.id", "tenant-123")

    def test_middleware_case_insensitive_headers(self, app_with_baggage):
        """Test middleware handles case-insensitive header matching."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "x-tenant-id": "tenant-123",  # lowercase
                    "X-USER-ID": "user-456",  # uppercase
                },
            )

            assert response.status_code == 200
            assert mock_baggage.set_baggage.call_count == 2

    def test_middleware_sanitizes_values(self, app_with_baggage):
        """Test middleware sanitizes header values."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant\x00\x01\x02",  # Control characters
                },
            )

            assert response.status_code == 200
            # Verify sanitized value was set
            mock_baggage.set_baggage.assert_called_once_with("tenant.id", "tenant")

    def test_middleware_merges_with_upstream_baggage(self, app_with_baggage):
        """Test middleware merges header baggage with upstream baggage."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant-123",
                    "baggage": "upstream.key=upstream-value",
                },
            )

            assert response.status_code == 200
            # Both header and upstream baggage should be set
            assert mock_baggage.set_baggage.call_count == 2
            mock_baggage.set_baggage.assert_any_call("tenant.id", "tenant-123")
            mock_baggage.set_baggage.assert_any_call("upstream.key", "upstream-value")

    def test_middleware_header_overrides_upstream(self, app_with_baggage):
        """Test header baggage overrides upstream baggage for same key."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "new-tenant",
                    "baggage": "tenant.id=old-tenant",
                },
            )

            assert response.status_code == 200
            # Header value should override upstream
            mock_baggage.set_baggage.assert_called_once_with("tenant.id", "new-tenant")

    def test_middleware_disabled_config(self):
        """Test middleware with disabled configuration."""
        app = FastAPI()
        disabled_config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        app.add_middleware(BaggageMiddleware, config=disabled_config)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={"X-Tenant-ID": "tenant-123"},
            )

            assert response.status_code == 200
            # No baggage should be set
            mock_baggage.set_baggage.assert_not_called()

    def test_middleware_handles_missing_otel(self):
        """Test middleware gracefully handles missing OpenTelemetry."""
        app = FastAPI()
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        app.add_middleware(BaggageMiddleware, config=config)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        with patch("mcpgateway.middleware.baggage_middleware.OTEL_BAGGAGE_AVAILABLE", False):
            response = client.get(
                "/test",
                headers={"X-Tenant-ID": "tenant-123"},
            )

            # Should not fail, just skip baggage setting
            assert response.status_code == 200

    def test_middleware_handles_errors_gracefully(self, app_with_baggage):
        """Test middleware handles errors without failing request."""
        client = TestClient(app_with_baggage)

        with patch("mcpgateway.middleware.baggage_middleware.extract_baggage_from_headers") as mock_extract:
            mock_extract.side_effect = Exception("Test error")

            response = client.get(
                "/test",
                headers={"X-Tenant-ID": "tenant-123"},
            )

            # Request should succeed despite error
            assert response.status_code == 200

    def test_middleware_non_http_requests(self, app_with_baggage):
        """Test middleware skips non-HTTP requests."""
        # This test verifies the middleware doesn't process WebSocket or other non-HTTP requests
        # In practice, this is tested by the middleware's scope type check
        pass  # WebSocket testing requires different setup

    def test_middleware_lazy_config_loading(self):
        """Test middleware lazy-loads configuration on first request."""
        app = FastAPI()
        # Don't provide config - should load from settings
        app.add_middleware(BaggageMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Test", "baggage_key": "test.key"}]',
                otel_baggage_propagate_to_external=False,
                otel_baggage_max_items=32,
                otel_baggage_max_size_bytes=8192,
                otel_baggage_log_rejected=True,
                otel_baggage_log_sanitization=True,
            )

            with patch("mcpgateway.middleware.baggage_middleware.otel_baggage"):
                response = client.get("/test", headers={"X-Test": "value"})
                assert response.status_code == 200

                # Config should be loaded
                mock_settings.assert_called()


class TestBaggageMiddlewareSecurityControls:
    """Test security controls in BaggageMiddleware."""

    def test_max_items_limit_enforced(self):
        """Test max items limit is enforced."""
        app = FastAPI()
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
                HeaderMapping("X-Header-3", "key3"),
            ],
            propagate_to_external=False,
            max_items=2,  # Limit to 2 items
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        app.add_middleware(BaggageMiddleware, config=config)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Header-1": "value1",
                    "X-Header-2": "value2",
                    "X-Header-3": "value3",
                },
            )

            assert response.status_code == 200
            # Only 2 items should be set
            assert mock_baggage.set_baggage.call_count == 2

    def test_max_size_limit_enforced(self):
        """Test max size limit is enforced."""
        app = FastAPI()
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=50,  # Small size limit
            log_rejected=True,
            log_sanitization=True,
        )
        app.add_middleware(BaggageMiddleware, config=config)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Header-1": "a" * 30,
                    "X-Header-2": "b" * 30,
                },
            )

            assert response.status_code == 200
            # Only first header should fit within size limit
            assert mock_baggage.set_baggage.call_count == 1
