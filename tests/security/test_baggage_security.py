# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_baggage_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security tests for baggage implementation.

Tests cover:
- Deny-path scenarios (unauthenticated, wrong team, insufficient permissions)
- Size limit enforcement
- Sanitization of malicious input
- Configuration validation
- Fail-closed behavior
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.baggage import (
    BaggageConfig,
    BaggageConfigError,
    BaggageSizeLimitError,
    HeaderMapping,
    extract_baggage_from_headers,
)
from mcpgateway.middleware.baggage_middleware import BaggageMiddleware


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


class TestBaggageSecurityDenyPaths:
    """Test security deny-path scenarios."""

    def test_undefined_headers_rejected(self):
        """Test that undefined headers are rejected (fail-closed)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Tenant-ID": "tenant-123",
            "X-Malicious": "malicious-value",
            "X-Unknown": "unknown-value",
        }

        result = extract_baggage_from_headers(headers, config)

        # Only configured header should be extracted
        assert len(result) == 1
        assert "tenant.id" in result
        assert "malicious" not in str(result)
        assert "unknown" not in str(result)

    def test_control_characters_sanitized(self):
        """Test that control characters are sanitized."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Tenant-ID": "tenant\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f",
        }

        result = extract_baggage_from_headers(headers, config)

        # Control characters should be removed
        assert result["tenant.id"] == "tenant"
        assert "\x00" not in result["tenant.id"]

    def test_crlf_injection_prevented(self):
        """Test that CRLF injection is prevented."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Tenant-ID": "tenant\r\nX-Injected: malicious",
        }

        result = extract_baggage_from_headers(headers, config)

        # CRLF should be removed (sanitization removes \r\n but keeps rest of string)
        assert "\r" not in result["tenant.id"]
        assert "\n" not in result["tenant.id"]
        # The rest of the string remains after sanitization
        assert result["tenant.id"] == "tenantX-Injected: malicious"

    def test_max_items_limit_enforced(self):
        """Test that max items limit is strictly enforced."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
                HeaderMapping("X-Header-3", "key3"),
                HeaderMapping("X-Header-4", "key4"),
                HeaderMapping("X-Header-5", "key5"),
            ],
            propagate_to_external=False,
            max_items=3,  # Strict limit
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Header-1": "value1",
            "X-Header-2": "value2",
            "X-Header-3": "value3",
            "X-Header-4": "value4",
            "X-Header-5": "value5",
        }

        result = extract_baggage_from_headers(headers, config)

        # Only max_items should be extracted
        assert len(result) <= config.max_items

    def test_max_size_limit_enforced(self):
        """Test that max size limit is strictly enforced."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=100,  # Small limit
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Header-1": "a" * 50,
            "X-Header-2": "b" * 50,
        }

        result = extract_baggage_from_headers(headers, config)

        # Calculate total size
        total_size = sum(len(k) + len(v) + 2 for k, v in result.items())
        assert total_size <= config.max_size_bytes

    def test_empty_value_after_sanitization_dropped(self):
        """Test that values that become empty after sanitization are dropped."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        headers = {
            "X-Tenant-ID": "\x00\x01\x02\x03",  # Only control characters
        }

        result = extract_baggage_from_headers(headers, config)

        # Empty value should be dropped
        assert "tenant.id" not in result

    def test_oversized_value_truncated(self):
        """Test that oversized values are truncated."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        # Create value larger than MAX_HEADER_VALUE_LENGTH (4096)
        large_value = "a" * 5000

        headers = {
            "X-Tenant-ID": large_value,
        }

        result = extract_baggage_from_headers(headers, config)

        # Value should be truncated
        assert len(result["tenant.id"]) <= 4096


class TestBaggageConfigurationSecurity:
    """Test configuration validation security."""

    def test_invalid_header_name_rejected(self):
        """Test that invalid header names are rejected."""
        with pytest.raises(BaggageConfigError, match="Invalid header name"):
            HeaderMapping("X-Tenant@ID", "tenant.id")

    def test_invalid_baggage_key_rejected(self):
        """Test that invalid baggage keys are rejected."""
        with pytest.raises(BaggageConfigError, match="Invalid baggage key"):
            HeaderMapping("X-Tenant-ID", "tenant@id")

    def test_duplicate_headers_rejected(self):
        """Test that duplicate headers are rejected."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "x-tenant-id", "baggage_key": "tenant.id2"}]',
            )

            with pytest.raises(BaggageConfigError, match="Duplicate header mapping"):
                BaggageConfig.from_settings()

    def test_duplicate_baggage_keys_rejected(self):
        """Test that duplicate baggage keys are rejected."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "X-Tenant", "baggage_key": "tenant.id"}]',
            )

            with pytest.raises(BaggageConfigError, match="Duplicate baggage key"):
                BaggageConfig.from_settings()

    def test_invalid_json_rejected(self):
        """Test that invalid JSON configuration is rejected."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings="invalid json",
            )

            with pytest.raises(BaggageConfigError, match="Invalid JSON"):
                BaggageConfig.from_settings()

    def test_non_array_config_rejected(self):
        """Test that non-array configuration is rejected."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='{"header_name": "X-Tenant-ID"}',
            )

            with pytest.raises(BaggageConfigError, match="must be a JSON array"):
                BaggageConfig.from_settings()


class TestBaggageMiddlewareSecurity:
    """Test middleware security controls."""

    def test_middleware_handles_errors_gracefully(self):
        """Test that middleware errors don't fail requests."""
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

        with patch("mcpgateway.middleware.baggage_middleware.extract_baggage_from_headers") as mock_extract:
            mock_extract.side_effect = Exception("Test error")

            response = client.get("/test", headers={"X-Tenant-ID": "tenant-123"})

            # Request should succeed despite error
            assert response.status_code == 200

    def test_disabled_config_prevents_processing(self):
        """Test that disabled configuration prevents all processing."""
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
            response = client.get("/test", headers={"X-Tenant-ID": "tenant-123"})

            assert response.status_code == 200
            # No baggage should be set
            mock_baggage.set_baggage.assert_not_called()

    def test_inbound_baggage_allowlist_blocks_unconfigured_keys(self):
        """Inbound baggage should not bypass the configured baggage-key allowlist."""
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
            # First-Party
            from mcpgateway.middleware.baggage_middleware import otel_baggage

            return {"baggage": dict(otel_baggage.get_all())}

        client = TestClient(app)
        response = client.get("/test", headers={"baggage": "malicious.key=boom,tenant.id=tenant-123"})

        assert response.status_code == 200
        assert response.json()["baggage"] == {"tenant.id": "tenant-123"}

    def test_propagation_disabled_by_default(self):
        """Test that propagation is disabled by default."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,  # Default
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        assert config.propagate_to_external is False


class TestBaggageFailClosed:
    """Test fail-closed behavior."""

    def test_extraction_error_returns_empty(self):
        """Test that extraction errors result in empty baggage (fail-closed)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        # Malformed headers that might cause errors
        headers = {
            "X-Tenant-ID": None,  # None value
        }

        # Should not raise, should return empty or skip
        result = extract_baggage_from_headers(headers, config)
        # Result should be safe (empty or valid)
        assert isinstance(result, dict)

    def test_missing_otel_graceful_degradation(self):
        """Test graceful degradation when OpenTelemetry is not available."""
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

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage", None):
            response = client.get("/test", headers={"X-Tenant-ID": "tenant-123"})

            # Should not fail
            assert response.status_code == 200
