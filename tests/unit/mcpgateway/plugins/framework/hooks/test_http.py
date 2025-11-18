# -*- coding: utf-8 -*-
"""Tests for HTTP forwarding hooks.

This module tests the HTTP forwarding hook models and their behavior.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthResolveUserPayload,
    HttpAuthResolveUserResult,
    HttpHeaderPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPostRequestResult,
    HttpPreRequestPayload,
    HttpPreRequestResult,
)
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
from mcpgateway.plugins.framework.models import PluginResult


class TestHttpHookType:
    """Test HttpHookType enum."""

    def test_hook_type_values(self):
        """Test that hook types have correct string values."""
        assert HttpHookType.HTTP_PRE_REQUEST == "http_pre_request"
        assert HttpHookType.HTTP_POST_REQUEST == "http_post_request"
        assert HttpHookType.HTTP_AUTH_RESOLVE_USER == "http_auth_resolve_user"

    def test_hook_type_from_string(self):
        """Test creating hook types from string values."""
        assert HttpHookType("http_pre_request") == HttpHookType.HTTP_PRE_REQUEST
        assert HttpHookType("http_post_request") == HttpHookType.HTTP_POST_REQUEST
        assert HttpHookType("http_auth_resolve_user") == HttpHookType.HTTP_AUTH_RESOLVE_USER

    def test_hook_types_list(self):
        """Test getting list of all hook types."""
        hook_types = list(HttpHookType)
        assert len(hook_types) == 4
        assert HttpHookType.HTTP_PRE_REQUEST in hook_types
        assert HttpHookType.HTTP_POST_REQUEST in hook_types
        assert HttpHookType.HTTP_AUTH_RESOLVE_USER in hook_types


class TestHttpHeaderPayload:
    """Test HttpHeaderPayload model."""

    def test_create_header_payload(self):
        """Test creating an HttpHeaderPayload."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token123", "Content-Type": "application/json"})
        assert headers["Authorization"] == "Bearer token123"
        assert headers["Content-Type"] == "application/json"

    def test_header_payload_iteration(self):
        """Test iterating over headers."""
        headers = HttpHeaderPayload({"X-Custom": "value1", "X-Another": "value2"})
        keys = list(headers)
        assert "X-Custom" in keys
        assert "X-Another" in keys

    def test_header_payload_setitem(self):
        """Test setting header values."""
        headers = HttpHeaderPayload({"Initial": "value"})
        headers["New-Header"] = "new-value"
        assert headers["New-Header"] == "new-value"

    def test_header_payload_len(self):
        """Test getting length of headers."""
        headers = HttpHeaderPayload({"Header1": "value1", "Header2": "value2", "Header3": "value3"})
        assert len(headers) == 3

    def test_empty_header_payload(self):
        """Test creating an empty header payload."""
        headers = HttpHeaderPayload({})
        assert len(headers) == 0


class TestHttpPreRequestPayload:
    """Test HttpPreRequestPayload model."""

    def test_create_pre_request_payload(self):
        """Test creating a pre-request payload."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        payload = HttpPreRequestPayload(
            path="/api/v1/test",
            method="POST",
            client_host="192.168.1.1",
            client_port=12345,
            headers=headers,
        )

        assert payload.path == "/api/v1/test"
        assert payload.method == "POST"
        assert payload.client_host == "192.168.1.1"
        assert payload.client_port == 12345
        assert payload.headers["Authorization"] == "Bearer token"

    def test_pre_request_payload_with_optional_fields_none(self):
        """Test creating payload with optional fields as None."""
        headers = HttpHeaderPayload({})
        payload = HttpPreRequestPayload(
            path="/forward",
            method="GET",
            headers=headers,
        )

        assert payload.client_host is None
        assert payload.client_port is None

    def test_pre_request_payload_different_methods(self):
        """Test payload with different HTTP methods."""
        headers = HttpHeaderPayload({})

        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            payload = HttpPreRequestPayload(
                path="/api/test",
                method=method,
                headers=headers,
            )
            assert payload.method == method

    def test_pre_request_payload_serialization(self):
        """Test payload serialization to dict."""
        headers = HttpHeaderPayload({"X-Custom": "value"})
        payload = HttpPreRequestPayload(
            path="/test",
            method="POST",
            client_host="10.0.0.1",
            client_port=8080,
            headers=headers,
        )

        data = payload.model_dump()
        assert data["path"] == "/test"
        assert data["method"] == "POST"
        assert data["client_host"] == "10.0.0.1"
        assert data["client_port"] == 8080

    def test_pre_request_payload_json_serialization(self):
        """Test payload serialization to JSON."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        payload = HttpPreRequestPayload(
            path="/api",
            method="GET",
            headers=headers,
        )

        json_str = payload.model_dump_json()
        assert "/api" in json_str
        assert "GET" in json_str


class TestHttpPostRequestPayload:
    """Test HttpPostRequestPayload model."""

    def test_create_post_request_payload(self):
        """Test creating a post-request payload."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        response_headers = HttpHeaderPayload({"Content-Type": "application/json", "X-Request-ID": "abc123"})

        payload = HttpPostRequestPayload(
            path="/api/v1/test",
            method="POST",
            client_host="192.168.1.1",
            client_port=12345,
            headers=headers,
            response_headers=response_headers,
            status_code=200,
        )

        assert payload.path == "/api/v1/test"
        assert payload.method == "POST"
        assert payload.client_host == "192.168.1.1"
        assert payload.client_port == 12345
        assert payload.headers["Authorization"] == "Bearer token"
        assert payload.response_headers["Content-Type"] == "application/json"
        assert payload.response_headers["X-Request-ID"] == "abc123"
        assert payload.status_code == 200

    def test_post_request_payload_without_response(self):
        """Test creating post-request payload without response data."""
        headers = HttpHeaderPayload({})
        payload = HttpPostRequestPayload(
            path="/test",
            method="GET",
            headers=headers,
        )

        assert payload.response_headers is None
        assert payload.status_code is None

    def test_post_request_payload_inherits_from_pre(self):
        """Test that HttpPostRequestPayload inherits from HttpPreRequestPayload."""
        headers = HttpHeaderPayload({})
        payload = HttpPostRequestPayload(
            path="/test",
            method="GET",
            headers=headers,
            status_code=404,
        )

        # Check inheritance
        assert isinstance(payload, HttpPreRequestPayload)

    def test_post_request_payload_various_status_codes(self):
        """Test payload with various HTTP status codes."""
        headers = HttpHeaderPayload({})

        for status_code in [200, 201, 204, 400, 401, 403, 404, 500, 502, 503]:
            payload = HttpPostRequestPayload(
                path="/test",
                method="GET",
                headers=headers,
                status_code=status_code,
            )
            assert payload.status_code == status_code

    def test_post_request_payload_serialization(self):
        """Test post-request payload serialization."""
        headers = HttpHeaderPayload({"X-Request": "test"})
        response_headers = HttpHeaderPayload({"X-Response": "result"})

        payload = HttpPostRequestPayload(
            path="/api/test",
            method="POST",
            client_host="127.0.0.1",
            client_port=9000,
            headers=headers,
            response_headers=response_headers,
            status_code=201,
        )

        data = payload.model_dump()
        assert data["path"] == "/api/test"
        assert data["status_code"] == 201


class TestHttpAuthResolveUserPayload:
    """Test HttpAuthResolveUserPayload model."""

    def test_create_auth_resolve_payload_with_credentials(self):
        """Test creating auth resolve payload with credentials."""
        headers = HttpHeaderPayload({"X-Custom-Auth": "custom-token-123", "User-Agent": "TestClient/1.0"})
        credentials = {"scheme": "bearer", "credentials": "jwt-token-abc"}

        payload = HttpAuthResolveUserPayload(
            credentials=credentials,
            headers=headers,
            client_host="10.0.0.5",
            client_port=54321,
        )

        assert payload.credentials == credentials
        assert payload.headers["X-Custom-Auth"] == "custom-token-123"
        assert payload.headers["User-Agent"] == "TestClient/1.0"
        assert payload.client_host == "10.0.0.5"
        assert payload.client_port == 54321

    def test_create_auth_resolve_payload_without_credentials(self):
        """Test creating auth resolve payload without credentials (custom header auth)."""
        headers = HttpHeaderPayload({"X-API-Key": "secret-key-456", "X-Client-ID": "client-789"})

        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
            client_host="192.168.1.100",
        )

        assert payload.credentials is None
        assert payload.headers["X-API-Key"] == "secret-key-456"
        assert payload.headers["X-Client-ID"] == "client-789"
        assert payload.client_host == "192.168.1.100"
        assert payload.client_port is None

    def test_auth_resolve_payload_with_mtls_cert_header(self):
        """Test auth resolve payload with mTLS certificate header."""
        headers = HttpHeaderPayload({
            "X-SSL-Client-Cert": "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----",
            "X-SSL-Client-DN": "CN=user@example.com,O=Example Corp",
        })

        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
            client_host="172.16.0.50",
            client_port=443,
        )

        assert "X-SSL-Client-Cert" in payload.headers
        assert "X-SSL-Client-DN" in payload.headers
        assert payload.client_port == 443

    def test_auth_resolve_payload_with_ldap_token(self):
        """Test auth resolve payload with LDAP token header."""
        headers = HttpHeaderPayload({"X-LDAP-Token": "ldap-session-xyz123"})

        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
        )

        assert payload.headers["X-LDAP-Token"] == "ldap-session-xyz123"

    def test_auth_resolve_payload_serialization(self):
        """Test auth resolve payload serialization."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        credentials = {"scheme": "bearer", "credentials": "token"}

        payload = HttpAuthResolveUserPayload(
            credentials=credentials,
            headers=headers,
            client_host="127.0.0.1",
        )

        data = payload.model_dump()
        assert data["credentials"] == credentials
        assert data["client_host"] == "127.0.0.1"

    def test_auth_resolve_payload_json_serialization(self):
        """Test auth resolve payload JSON serialization."""
        headers = HttpHeaderPayload({"X-Auth": "custom"})

        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
        )

        json_str = payload.model_dump_json()
        assert "X-Auth" in json_str
        assert "custom" in json_str


class TestHttpResults:
    """Test HTTP result type aliases."""

    def test_pre_request_result_type(self):
        """Test HttpPreRequestResult is a PluginResult."""
        headers = HttpHeaderPayload({"Modified": "header"})
        result = PluginResult[HttpHeaderPayload](
            continue_processing=True,
            modified_payload=headers,
        )

        assert result.continue_processing is True
        assert result.modified_payload["Modified"] == "header"

    def test_post_request_result_type(self):
        """Test HttpPostRequestResult is a PluginResult."""
        headers = HttpHeaderPayload({"X-Added": "value"})
        result = PluginResult[HttpHeaderPayload](
            continue_processing=True,
            modified_payload=headers,
            metadata={"plugin": "auth_plugin"},
        )

        assert result.continue_processing is True
        assert result.modified_payload["X-Added"] == "value"
        assert result.metadata["plugin"] == "auth_plugin"

    def test_auth_resolve_user_result_type(self):
        """Test HttpAuthResolveUserResult returns user dict."""
        user_dict = {
            "email": "user@example.com",
            "full_name": "Test User",
            "is_admin": False,
            "is_active": True,
        }

        result = PluginResult[dict](
            continue_processing=False,  # Stop processing, user authenticated
            modified_payload=user_dict,
        )

        assert result.continue_processing is False
        assert result.modified_payload["email"] == "user@example.com"
        assert result.modified_payload["full_name"] == "Test User"
        assert result.modified_payload["is_admin"] is False

    def test_result_with_violation(self):
        """Test result with a violation (blocking)."""
        from mcpgateway.plugins.framework.models import PluginViolation

        violation = PluginViolation(
            reason="Unauthorized",
            description="Missing authentication token",
            code="AUTH_REQUIRED",
        )

        result = PluginResult[HttpHeaderPayload](
            continue_processing=False,
            violation=violation,
        )

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "AUTH_REQUIRED"


class TestHttpHookRegistry:
    """Test HTTP hooks registration in the hook registry."""

    def test_hooks_are_registered(self):
        """Test that all HTTP hooks are registered."""
        registry = get_hook_registry()

        assert registry.is_registered(HttpHookType.HTTP_PRE_REQUEST)
        assert registry.is_registered(HttpHookType.HTTP_POST_REQUEST)
        assert registry.is_registered(HttpHookType.HTTP_AUTH_RESOLVE_USER)

    def test_pre_request_hook_payload_type(self):
        """Test that pre-request hook has correct payload type."""
        registry = get_hook_registry()

        payload_type = registry.get_payload_type(HttpHookType.HTTP_PRE_REQUEST)
        assert payload_type is HttpPreRequestPayload

    def test_post_request_hook_payload_type(self):
        """Test that post-request hook has correct payload type."""
        registry = get_hook_registry()

        payload_type = registry.get_payload_type(HttpHookType.HTTP_POST_REQUEST)
        assert payload_type is HttpPostRequestPayload

    def test_auth_resolve_user_hook_payload_type(self):
        """Test that auth resolve user hook has correct payload type."""
        registry = get_hook_registry()

        payload_type = registry.get_payload_type(HttpHookType.HTTP_AUTH_RESOLVE_USER)
        assert payload_type is HttpAuthResolveUserPayload

    def test_pre_request_hook_result_type(self):
        """Test that pre-request hook has correct result type."""
        registry = get_hook_registry()

        result_type = registry.get_result_type(HttpHookType.HTTP_PRE_REQUEST)
        assert result_type is not None

    def test_post_request_hook_result_type(self):
        """Test that post-request hook has correct result type."""
        registry = get_hook_registry()

        result_type = registry.get_result_type(HttpHookType.HTTP_POST_REQUEST)
        assert result_type is not None

    def test_auth_resolve_user_hook_result_type(self):
        """Test that auth resolve user hook has correct result type."""
        registry = get_hook_registry()

        result_type = registry.get_result_type(HttpHookType.HTTP_AUTH_RESOLVE_USER)
        assert result_type is not None


class TestHttpPayloadImmutability:
    """Test that payload metadata fields are effectively read-only (Option 3 design)."""

    def test_payload_fields_are_set_at_creation(self):
        """Test that all payload fields are set during creation."""
        headers = HttpHeaderPayload({"X-Test": "value"})
        payload = HttpPreRequestPayload(
            path="/api/test",
            method="POST",
            client_host="10.0.0.1",
            client_port=8080,
            headers=headers,
        )

        # All fields should be accessible
        assert payload.path == "/api/test"
        assert payload.method == "POST"
        assert payload.client_host == "10.0.0.1"
        assert payload.client_port == 8080

    def test_headers_can_be_modified(self):
        """Test that headers can be modified (the plugin's job)."""
        headers = HttpHeaderPayload({"Original": "value"})
        payload = HttpPreRequestPayload(
            path="/test",
            method="GET",
            headers=headers,
        )

        # Headers should be modifiable
        payload.headers["New-Header"] = "new-value"
        assert payload.headers["New-Header"] == "new-value"

    def test_plugin_returns_modified_headers_only(self):
        """Test plugin pattern: return only modified headers in result."""
        # This simulates a plugin receiving a payload and returning modified headers
        original_headers = HttpHeaderPayload({"Content-Type": "application/json"})
        payload = HttpPreRequestPayload(
            path="/api/secure",
            method="POST",
            headers=original_headers,
        )

        # Plugin modifies headers using model_dump()
        modified_headers = HttpHeaderPayload(payload.headers.model_dump())
        modified_headers["Authorization"] = "Bearer plugin-added-token"

        # Plugin returns result with only the modified headers
        result = PluginResult[HttpHeaderPayload](
            continue_processing=True,
            modified_payload=modified_headers,
        )

        # Framework would apply these headers to the request
        assert result.modified_payload["Authorization"] == "Bearer plugin-added-token"
        assert result.modified_payload["Content-Type"] == "application/json"


class TestHttpPayloadEdgeCases:
    """Test edge cases for HTTP forwarding payloads."""

    def test_empty_path(self):
        """Test payload with empty path."""
        headers = HttpHeaderPayload({})
        payload = HttpPreRequestPayload(
            path="",
            method="GET",
            headers=headers,
        )
        assert payload.path == ""

    def test_very_long_path(self):
        """Test payload with very long path."""
        headers = HttpHeaderPayload({})
        long_path = "/api/v1/" + "segment/" * 100 + "endpoint"
        payload = HttpPreRequestPayload(
            path=long_path,
            method="GET",
            headers=headers,
        )
        assert payload.path == long_path

    def test_large_number_of_headers(self):
        """Test payload with many headers."""
        headers_dict = {f"X-Header-{i}": f"value-{i}" for i in range(100)}
        headers = HttpHeaderPayload(headers_dict)
        payload = HttpPreRequestPayload(
            path="/test",
            method="GET",
            headers=headers,
        )
        assert len(payload.headers) == 100

    def test_ipv6_client_host(self):
        """Test payload with IPv6 client host."""
        headers = HttpHeaderPayload({})
        payload = HttpPreRequestPayload(
            path="/test",
            method="GET",
            client_host="2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            headers=headers,
        )
        assert payload.client_host == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
