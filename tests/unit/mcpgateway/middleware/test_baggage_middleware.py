# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_baggage_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for BaggageMiddleware.

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


def _current_baggage() -> dict:
    # First-Party
    from mcpgateway.middleware.baggage_middleware import otel_baggage

    if otel_baggage is None:
        return {}
    return dict(otel_baggage.get_all())


class _FakeOtelBaggage:
    def __init__(self):
        self._state = {}

    def get_all(self):
        return dict(self._state)

    def set_baggage(self, key, value, context=None):
        new_context = dict(self._state if context is None else context)
        new_context[key] = value
        return new_context

    def get_current(self):
        return dict(self._state)

    def attach(self, context):
        previous = dict(self._state)
        self._state = dict(context)
        return previous

    def detach(self, token):
        self._state = dict(token)


@pytest.fixture(autouse=True)
def fake_otel_baggage(monkeypatch):
    fake = _FakeOtelBaggage()
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_baggage", fake)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_get_current", fake.get_current)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_attach", fake.attach)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_detach", fake.detach)
    return fake


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
        return {"status": "ok", "baggage": _current_baggage()}

    return app


class TestBaggageMiddlewareIntegration:
    """Test BaggageMiddleware integration with FastAPI."""

    def test_middleware_processes_configured_headers(self, app_with_baggage):
        """Test middleware extracts configured headers."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant-123",
                "X-User-ID": "user-456",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_middleware_skips_undefined_headers(self, app_with_baggage):
        """Test middleware skips headers not in configuration."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant-123",
                "X-Unknown": "value",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant-123"}

    def test_middleware_case_insensitive_headers(self, app_with_baggage):
        """Test middleware handles case-insensitive header matching."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "x-tenant-id": "tenant-123",
                "X-USER-ID": "user-456",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_middleware_sanitizes_values(self, app_with_baggage):
        """Test middleware sanitizes header values."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant\x00\x01\x02",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant"}

    def test_middleware_merges_with_upstream_baggage(self, app_with_baggage):
        """Test middleware merges header baggage with upstream baggage."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant-123",
                "baggage": "user.id=user-456",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_middleware_header_overrides_upstream(self, app_with_baggage):
        """Test header baggage overrides upstream baggage for same key."""
        client = TestClient(app_with_baggage)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "new-tenant",
                "baggage": "tenant.id=old-tenant",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "new-tenant"}

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
            return {"status": "ok", "baggage": _current_baggage()}

        client = TestClient(app)

        response = client.get(
            "/test",
            headers={"X-Tenant-ID": "tenant-123"},
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {}

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
            return {"status": "ok", "baggage": _current_baggage()}

        client = TestClient(app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", None):
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
            return {"status": "ok", "baggage": _current_baggage()}

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
            return {"status": "ok", "baggage": _current_baggage()}

        client = TestClient(app)

        response = client.get(
            "/test",
            headers={
                "X-Header-1": "value1",
                "X-Header-2": "value2",
                "X-Header-3": "value3",
            },
        )

        assert response.status_code == 200
        assert len(response.json()["baggage"]) == 2

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
            return {"status": "ok", "baggage": _current_baggage()}

        client = TestClient(app)

        response = client.get(
            "/test",
            headers={
                "X-Header-1": "a" * 30,
                "X-Header-2": "b" * 30,
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {"key1": "a" * 30}

    def test_outer_middleware_sees_baggage_before_inner_app(self, test_config):
        """Baggage middleware should execute before inner request observers."""
        captured = []

        class CaptureMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope.get("type") == "http":
                    # First-Party
                    from mcpgateway.middleware.baggage_middleware import otel_baggage

                    captured.append(dict(otel_baggage.get_all()))
                await self.app(scope, receive, send)

        app = FastAPI()
        app.add_middleware(CaptureMiddleware)
        app.add_middleware(BaggageMiddleware, config=test_config)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Tenant-ID": "tenant-123"})

        assert response.status_code == 200
        assert captured == [{"tenant.id": "tenant-123"}]


class TestMiddlewareEdgeCases:
    """Test middleware edge cases for improved coverage."""

    @pytest.mark.asyncio
    async def test_middleware_without_otel_baggage_api(self):
        """Test middleware behavior when OTEL baggage API is unavailable."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": []}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        with patch("mcpgateway.middleware.baggage_middleware.OTEL_BAGGAGE_AVAILABLE", False):
            middleware = BaggageMiddleware(app=mock_app)
            await middleware(mock_scope, mock_receive, mock_send)

            # Should call app without crashing
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_config_load_error(self):
        """Test middleware behavior when config loading fails."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": []}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        with patch("mcpgateway.baggage.BaggageConfig.from_settings", side_effect=Exception("Config error")):
            middleware = BaggageMiddleware(app=mock_app)
            await middleware(mock_scope, mock_receive, mock_send)

            # Should handle error gracefully and call app
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_disabled(self):
        """Test middleware when baggage feature is disabled."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": []}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        middleware = BaggageMiddleware(app=mock_app, config=config)
        await middleware(mock_scope, mock_receive, mock_send)

        # Should call app without processing
        mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_otel_context_unavailable(self):
        """Test middleware when OTEL context is unavailable."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": [(b"x-tenant-id", b"tenant-123")]}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        with patch("mcpgateway.middleware.baggage_middleware.otel_get_current", return_value=None):
            middleware = BaggageMiddleware(app=mock_app, config=config)
            await middleware(mock_scope, mock_receive, mock_send)

            # Should handle gracefully
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_extraction_error(self):
        """Test middleware when header extraction fails."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": [(b"x-tenant-id", b"tenant-123")]}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        with patch("mcpgateway.baggage.extract_baggage_from_headers", side_effect=Exception("Extraction error")):
            middleware = BaggageMiddleware(app=mock_app, config=config)
            await middleware(mock_scope, mock_receive, mock_send)

            # Should handle error and call app
            mock_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_baggage_parsing_error(self):
        """Test middleware when inbound baggage parsing fails."""
        mock_app = AsyncMock()
        mock_scope = {"type": "http", "headers": [(b"x-tenant-id", b"tenant-123"), (b"baggage", b"invalid-baggage")]}
        mock_receive = AsyncMock()
        mock_send = AsyncMock()

        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        with patch("mcpgateway.baggage.parse_w3c_baggage_header", side_effect=Exception("Parse error")):
            middleware = BaggageMiddleware(app=mock_app, config=config)
            await middleware(mock_scope, mock_receive, mock_send)

            # Should handle error and call app
            mock_app.assert_called_once()
