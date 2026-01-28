# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_multi_auth_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test multi-header authentication functionality.
"""

# Standard
import base64
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import Request
from pydantic import ValidationError
import pytest
from starlette.datastructures import FormData

# First-Party
from mcpgateway.admin import admin_add_gateway
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.services_auth import decode_auth, encode_auth


class TestMultiAuthHeaders:
    """Test cases for multi-header authentication feature."""

    @pytest.mark.asyncio
    async def test_gateway_create_with_valid_multi_headers(self):
        """Test creating gateway with valid multi-auth headers."""
        auth_headers = [{"key": "X-API-Key", "value": "secret123"}, {"key": "X-Client-ID", "value": "client456"}, {"key": "X-Region", "value": "us-east-1"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        assert gateway.auth_value is not None
        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-API-Key"] == "secret123"
        assert decoded["X-Client-ID"] == "client456"
        assert decoded["X-Region"] == "us-east-1"

    @pytest.mark.asyncio
    async def test_gateway_create_with_empty_headers_list(self):
        """Test creating gateway with empty auth_headers list."""
        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=[])

        assert "either 'auth_headers' list or both" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_gateway_create_with_duplicate_header_keys(self):
        """Test handling of duplicate header keys (last value wins)."""
        auth_headers = [{"key": "X-API-Key", "value": "first_value"}, {"key": "X-API-Key", "value": "second_value"}, {"key": "X-Client-ID", "value": "client123"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-API-Key"] == "second_value"  # Last value should win
        assert decoded["X-Client-ID"] == "client123"

    @pytest.mark.asyncio
    async def test_gateway_create_with_empty_header_values(self):
        """Test creating gateway with empty header values."""
        auth_headers = [{"key": "X-API-Key", "value": ""}, {"key": "X-Client-ID", "value": "client123"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-API-Key"] == ""  # Empty values should be allowed
        assert decoded["X-Client-ID"] == "client123"

    @pytest.mark.asyncio
    async def test_gateway_create_with_missing_key_in_header(self):
        """Test creating gateway with missing key in header object."""
        auth_headers = [{"value": "secret123"}, {"key": "X-Client-ID", "value": "client123"}]  # Missing 'key' field

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert "X-Client-ID" in decoded
        assert len(decoded) == 1  # Only valid header should be included

    @pytest.mark.asyncio
    async def test_backward_compatibility_single_headers(self):
        """Test backward compatibility with single header fields."""
        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_header_key="X-API-Key", auth_header_value="secret123")

        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-API-Key"] == "secret123"

    @pytest.mark.asyncio
    async def test_multi_headers_priority_over_single(self):
        """Test that multi-headers take priority over single header fields."""
        auth_headers = [{"key": "X-Multi-Header", "value": "multi_value"}]

        gateway = GatewayCreate(
            name="Test Gateway",
            url="http://example.com",
            auth_type="authheaders",
            auth_headers=auth_headers,
            auth_header_key="X-Single-Header",  # Should be ignored
            auth_header_value="single_value",  # Should be ignored
        )

        decoded = decode_auth(gateway.auth_value)
        assert "X-Multi-Header" in decoded
        assert "X-Single-Header" not in decoded

    @pytest.mark.asyncio
    async def test_gateway_update_add_multi_headers(self):
        """Test updating gateway to add multi-headers."""
        auth_headers = [{"key": "X-New-Header", "value": "new_value"}]

        gateway = GatewayUpdate(auth_type="authheaders", auth_headers=auth_headers)

        assert gateway.auth_value is not None
        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-New-Header"] == "new_value"

    @pytest.mark.asyncio
    async def test_special_characters_in_headers_rejected(self):
        """Test headers with invalid special characters are rejected."""
        auth_headers = [{"key": "X-Special-!@#", "value": "value-with-特殊字符"}, {"key": "Content-Type", "value": "application/json; charset=utf-8"}]

        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        assert "Invalid header key format" in str(exc_info.value)
        assert "X-Special-!@#" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_valid_special_characters_in_values(self):
        """Test headers with special characters in values (allowed) but valid keys."""
        auth_headers = [{"key": "X-Special-Header", "value": "value-with-特殊字符"}, {"key": "Content-Type", "value": "application/json; charset=utf-8"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-Special-Header"] == "value-with-特殊字符"
        assert decoded["Content-Type"] == "application/json; charset=utf-8"

    @pytest.mark.asyncio
    async def test_case_sensitivity_preservation(self):
        """Test that header key case is preserved."""
        auth_headers = [{"key": "X-API-Key", "value": "value1"}, {"key": "x-api-key", "value": "value2"}, {"key": "X-Api-Key", "value": "value3"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        # All three variations should be preserved as separate keys
        assert len(decoded) == 3

    @pytest.mark.asyncio
    async def test_admin_endpoint_with_invalid_json(self):
        """Test admin endpoint handling of invalid JSON."""
        mock_db = MagicMock()
        mock_user = "test_user"

        form_data = FormData([("name", "Test Gateway"), ("url", "http://example.com"), ("auth_type", "authheaders"), ("auth_headers", "{invalid json}")])

        mock_request = MagicMock(spec=Request)
        mock_request.form = AsyncMock(return_value=form_data)

        with patch("mcpgateway.admin.gateway_service.register_gateway", AsyncMock()):
            response = await admin_add_gateway(mock_request, mock_db, mock_user)
            # Should handle invalid JSON gracefully
            assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_large_number_of_headers(self):
        """Test handling of large number of headers."""
        auth_headers = [{"key": f"X-Header-{i}", "value": f"value-{i}"} for i in range(100)]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert len(decoded) == 100
        assert decoded["X-Header-50"] == "value-50"

    @pytest.mark.asyncio
    async def test_authorization_header_in_multi_headers(self):
        """Test including Authorization header in multi-headers."""
        auth_headers = [{"key": "Authorization", "value": "Bearer token123"}, {"key": "X-API-Key", "value": "secret"}]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert decoded["Authorization"] == "Bearer token123"
        assert decoded["X-API-Key"] == "secret"

    @pytest.mark.asyncio
    async def test_gateway_create_invalid_header_key_format(self):
        """Test creating gateway with invalid header key format."""
        auth_headers = [{"key": "Invalid@Key!", "value": "secret123"}]

        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        assert "Invalid header key format" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_gateway_create_excessive_headers(self):
        """Test creating gateway with more than 100 headers."""
        auth_headers = [{"key": f"X-Header-{i}", "value": f"value-{i}"} for i in range(101)]

        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        assert "Maximum of 100 headers allowed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_gateway_create_duplicate_keys_with_warning(self, caplog):
        """Test creating gateway with duplicate header keys logs warning."""
        auth_headers = [
            {"key": "X-API-Key", "value": "first_value"},
            {"key": "X-API-Key", "value": "second_value"},  # Duplicate
            {"key": "X-Client-ID", "value": "client123"},
        ]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        # Check that duplicate warning was logged
        assert "Duplicate header keys detected" in caplog.text
        assert "X-API-Key" in caplog.text

        # Check that last value wins
        decoded = decode_auth(gateway.auth_value)
        assert decoded["X-API-Key"] == "second_value"
        assert decoded["X-Client-ID"] == "client123"

    @pytest.mark.asyncio
    async def test_gateway_create_mixed_valid_invalid_keys(self):
        """Test creating gateway with mixed valid and invalid header keys."""
        auth_headers = [
            {"key": "Valid-Header", "value": "test123"},
            {"key": "Invalid@Key!", "value": "should_fail"},  # This should fail validation
        ]

        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        assert "Invalid header key format" in str(exc_info.value)
        assert "Invalid@Key!" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_gateway_create_edge_case_header_keys(self):
        """Test creating gateway with edge case header keys."""
        # Test valid edge cases
        auth_headers = [
            {"key": "X-API-Key", "value": "test1"},  # Standard format
            {"key": "X_API_KEY", "value": "test2"},  # Underscores allowed
            {"key": "API-Key-123", "value": "test3"},  # Numbers and hyphens
            {"key": "UPPERCASE", "value": "test4"},  # Uppercase
            {"key": "lowercase", "value": "test5"},  # Lowercase
        ]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert len(decoded) == 5
        assert decoded["X-API-Key"] == "test1"
        assert decoded["X_API_KEY"] == "test2"
        assert decoded["API-Key-123"] == "test3"

    def test_gateway_read_includes_masked_auth_headers(self, monkeypatch):
        """Ensure GatewayRead surfaces auth_headers and masks values."""
        monkeypatch.setattr(settings, "auth_encryption_secret", "unit-test-secret")
        auth_map = {"X-API-Key": "secret123", "X-Trace": "trace-value"}
        gateway_read = GatewayRead(
            name="Masked Gateway",
            url="http://example.com",
            auth_type="authheaders",
            auth_value=encode_auth(auth_map),
        )

        assert gateway_read.auth_headers is not None
        assert {header["key"] for header in gateway_read.auth_headers} == set(auth_map.keys())
        assert gateway_read.auth_headers_unmasked == gateway_read.auth_headers

        masked = gateway_read.masked()
        assert masked.auth_headers is not None
        for header in masked.auth_headers:
            if header["value"]:
                assert header["value"] == settings.masked_auth_value
        assert masked.auth_headers_unmasked is not None
        for header in masked.auth_headers_unmasked:
            assert header["value"] == auth_map[header["key"]]

    @pytest.mark.asyncio
    async def test_gateway_update_preserves_masked_header_values(self, monkeypatch):
        """Confirm updating a gateway retains existing header secrets when masked."""
        monkeypatch.setattr(settings, "auth_encryption_secret", "unit-test-secret")

        service = GatewayService()
        existing_headers = {"X-API-Key": "secret123", "X-Trace": "trace-1"}

        gateway_db_obj = MagicMock()
        gateway_db_obj.id = "gateway-1"
        gateway_db_obj.name = "Gateway"
        gateway_db_obj.slug = "gateway"
        gateway_db_obj.enabled = True
        gateway_db_obj.visibility = "public"
        gateway_db_obj.transport = "SSE"
        gateway_db_obj.tags = []
        gateway_db_obj.auth_type = "authheaders"
        gateway_db_obj.auth_value = encode_auth(existing_headers)
        gateway_db_obj.url = "http://example.com"
        gateway_db_obj.tools = []
        gateway_db_obj.resources = []
        gateway_db_obj.prompts = []
        gateway_db_obj.capabilities = {}
        gateway_db_obj.last_seen = None
        gateway_db_obj.version = 1

        mock_db = MagicMock()
        # First execute call returns gateway (selectinload query), subsequent calls return None (conflict checks)
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=gateway_db_obj))
        mock_db.add_all = MagicMock()
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))

        monkeypatch.setattr(service, "_initialize_gateway", AsyncMock(return_value=({}, [], [], [])))
        monkeypatch.setattr(service, "_update_or_create_tools", MagicMock(return_value=[]))
        monkeypatch.setattr(service, "_update_or_create_resources", MagicMock(return_value=[]))
        monkeypatch.setattr(service, "_update_or_create_prompts", MagicMock(return_value=[]))
        monkeypatch.setattr(service, "_notify_gateway_updated", AsyncMock())

        monkeypatch.setattr(service, "_prepare_gateway_for_read", lambda value: value)

        monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda value: value))

        gateway_update = GatewayUpdate(
            name="Gateway",
            url="http://example.com",
            auth_type="authheaders",
            auth_headers=[
                {"key": "X-API-Key", "value": settings.masked_auth_value},
                {"key": "X-Trace", "value": "updated-trace"},
            ],
        )

        result = await service.update_gateway(
            mock_db,
            "gateway-1",
            gateway_update,
            modified_by=None,
        )

        updated_auth = gateway_db_obj.auth_value
        if isinstance(updated_auth, str):
            updated_auth = decode_auth(updated_auth)

        assert updated_auth["X-API-Key"] == "secret123"
        assert updated_auth["X-Trace"] == "updated-trace"
        assert result is gateway_db_obj

    def test_gateway_read_unmasked_basic_and_bearer(self, monkeypatch):
        """Verify GatewayRead retains unmasked values for basic and bearer auth."""
        monkeypatch.setattr(settings, "auth_encryption_secret", "unit-test-secret")

        # Basic auth
        creds = base64.b64encode(b"user:secret-pass").decode("utf-8")
        basic_gateway = GatewayRead(
            name="Basic Gateway",
            url="http://example.com",
            auth_type="basic",
            auth_value=encode_auth({"Authorization": f"Basic {creds}"}),
        )
        assert basic_gateway.auth_password_unmasked == "secret-pass"
        masked_basic = basic_gateway.masked()
        assert masked_basic.auth_password == settings.masked_auth_value
        assert masked_basic.auth_password_unmasked == "secret-pass"

        # Bearer auth
        bearer_gateway = GatewayRead(
            name="Bearer Gateway",
            url="http://example.com",
            auth_type="bearer",
            auth_value=encode_auth({"Authorization": "Bearer token-123"}),
        )
        assert bearer_gateway.auth_token_unmasked == "token-123"
        masked_bearer = bearer_gateway.masked()
        assert masked_bearer.auth_token == settings.masked_auth_value
        assert masked_bearer.auth_token_unmasked == "token-123"
