# -*- coding: utf-8 -*-
"""Test multi-header authentication functionality."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import Request
from pydantic import ValidationError
import pytest
from starlette.datastructures import FormData

# First-Party
from mcpgateway.admin import admin_add_gateway
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.utils.services_auth import decode_auth


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
            {"key": "X-Client-ID", "value": "client123"}
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
            {"key": "Invalid@Key!", "value": "should_fail"}  # This should fail validation
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
            {"key": "lowercase", "value": "test5"}   # Lowercase
        ]

        gateway = GatewayCreate(name="Test Gateway", url="http://example.com", auth_type="authheaders", auth_headers=auth_headers)

        decoded = decode_auth(gateway.auth_value)
        assert len(decoded) == 5
        assert decoded["X-API-Key"] == "test1"
        assert decoded["X_API_KEY"] == "test2"
        assert decoded["API-Key-123"] == "test3"
