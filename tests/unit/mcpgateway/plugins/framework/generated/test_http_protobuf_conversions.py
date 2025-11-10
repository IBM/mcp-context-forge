# -*- coding: utf-8 -*-
"""Tests for HTTP hook Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for HTTP hook payload classes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResultPayload,
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpPostRequestPayload,
    HttpPreRequestPayload,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestHttpPreRequestPayloadConversion:
    """Test HttpPreRequestPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic HttpPreRequestPayload conversion to protobuf and back."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token123", "Content-Type": "application/json"})
        payload = HttpPreRequestPayload(
            path="/api/v1/tools",
            method="GET",
            client_host="192.168.1.100",
            client_port=54321,
            headers=headers,
        )

        # Convert to protobuf
        proto_payload = payload.model_dump_pb()

        # Verify protobuf fields
        assert proto_payload.path == "/api/v1/tools"
        assert proto_payload.method == "GET"
        assert proto_payload.client_host == "192.168.1.100"
        assert proto_payload.client_port == 54321

        # Convert back to Pydantic
        restored = HttpPreRequestPayload.model_validate_pb(proto_payload)

        # Verify restoration
        assert restored.path == payload.path
        assert restored.method == payload.method
        assert restored.client_host == payload.client_host
        assert restored.client_port == payload.client_port
        assert restored.headers["Authorization"] == "Bearer token123"

    def test_with_optional_fields_none(self):
        """Test HttpPreRequestPayload with optional fields as None."""
        headers = HttpHeaderPayload({"X-Custom-Header": "value"})
        payload = HttpPreRequestPayload(
            path="/test",
            method="POST",
            client_host=None,
            client_port=None,
            headers=headers,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpPreRequestPayload.model_validate_pb(proto_payload)

        assert restored.path == "/test"
        assert restored.method == "POST"
        assert restored.client_host is None
        assert restored.client_port is None

    def test_roundtrip_conversion(self):
        """Test multiple roundtrip conversions maintain data integrity."""
        headers = HttpHeaderPayload({"User-Agent": "TestAgent/1.0"})
        payload = HttpPreRequestPayload(
            path="/api/tools/invoke",
            method="POST",
            client_host="10.0.0.1",
            client_port=8080,
            headers=headers,
        )

        # Multiple roundtrips
        for _ in range(3):
            proto_payload = payload.model_dump_pb()
            payload = HttpPreRequestPayload.model_validate_pb(proto_payload)

        assert payload.path == "/api/tools/invoke"
        assert payload.method == "POST"
        assert payload.client_host == "10.0.0.1"


class TestHttpPostRequestPayloadConversion:
    """Test HttpPostRequestPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic HttpPostRequestPayload conversion to protobuf and back."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        response_headers = HttpHeaderPayload({"Content-Type": "application/json", "X-Request-ID": "req-123"})
        payload = HttpPostRequestPayload(
            path="/api/v1/tools",
            method="POST",
            client_host="192.168.1.100",
            client_port=54321,
            headers=headers,
            response_headers=response_headers,
            status_code=200,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpPostRequestPayload.model_validate_pb(proto_payload)

        assert restored.path == payload.path
        assert restored.method == payload.method
        assert restored.status_code == 200
        assert restored.response_headers["Content-Type"] == "application/json"
        assert restored.response_headers["X-Request-ID"] == "req-123"

    def test_with_error_status_code(self):
        """Test HttpPostRequestPayload with error status code."""
        headers = HttpHeaderPayload({})
        response_headers = HttpHeaderPayload({"Content-Type": "application/json"})
        payload = HttpPostRequestPayload(
            path="/api/error",
            method="GET",
            headers=headers,
            response_headers=response_headers,
            status_code=500,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpPostRequestPayload.model_validate_pb(proto_payload)

        assert restored.status_code == 500

    def test_without_response_headers(self):
        """Test HttpPostRequestPayload without response headers."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token"})
        payload = HttpPostRequestPayload(
            path="/api/test",
            method="GET",
            headers=headers,
            response_headers=None,
            status_code=204,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpPostRequestPayload.model_validate_pb(proto_payload)

        assert restored.response_headers is None
        assert restored.status_code == 204


class TestHttpAuthResolveUserPayloadConversion:
    """Test HttpAuthResolveUserPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion_with_credentials(self):
        """Test HttpAuthResolveUserPayload with credentials."""
        headers = HttpHeaderPayload({"Authorization": "Bearer token123"})
        credentials = {"scheme": "Bearer", "credentials": "token123"}
        payload = HttpAuthResolveUserPayload(
            credentials=credentials,
            headers=headers,
            client_host="192.168.1.100",
            client_port=54321,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthResolveUserPayload.model_validate_pb(proto_payload)

        assert restored.credentials["scheme"] == "Bearer"
        assert restored.credentials["credentials"] == "token123"
        assert restored.client_host == "192.168.1.100"
        assert restored.client_port == 54321

    def test_without_credentials(self):
        """Test HttpAuthResolveUserPayload without credentials."""
        headers = HttpHeaderPayload({"X-API-Key": "secret123"})
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
            client_host="10.0.0.1",
            client_port=443,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthResolveUserPayload.model_validate_pb(proto_payload)

        assert restored.credentials is None
        assert restored.headers["X-API-Key"] == "secret123"

    def test_with_custom_headers(self):
        """Test HttpAuthResolveUserPayload with custom authentication headers."""
        headers = HttpHeaderPayload(
            {"X-Client-Cert-DN": "CN=user,O=org", "X-LDAP-Token": "ldap-token-123", "X-Correlation-ID": "corr-456"}
        )
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=headers,
            client_host="192.168.1.50",
            client_port=8443,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthResolveUserPayload.model_validate_pb(proto_payload)

        assert restored.headers["X-Client-Cert-DN"] == "CN=user,O=org"
        assert restored.headers["X-LDAP-Token"] == "ldap-token-123"
        assert restored.headers["X-Correlation-ID"] == "corr-456"


class TestHttpAuthCheckPermissionPayloadConversion:
    """Test HttpAuthCheckPermissionPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic HttpAuthCheckPermissionPayload conversion."""
        payload = HttpAuthCheckPermissionPayload(
            user_email="user@example.com",
            permission="tools.read",
            resource_type="tool",
            team_id="team-123",
            is_admin=False,
            auth_method="simple_token",
            client_host="192.168.1.100",
            user_agent="TestClient/1.0",
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionPayload.model_validate_pb(proto_payload)

        assert restored.user_email == "user@example.com"
        assert restored.permission == "tools.read"
        assert restored.resource_type == "tool"
        assert restored.team_id == "team-123"
        assert restored.is_admin is False
        assert restored.auth_method == "simple_token"
        assert restored.client_host == "192.168.1.100"
        assert restored.user_agent == "TestClient/1.0"

    def test_with_admin_user(self):
        """Test HttpAuthCheckPermissionPayload with admin user."""
        payload = HttpAuthCheckPermissionPayload(
            user_email="admin@example.com",
            permission="servers.write",
            resource_type="server",
            is_admin=True,
            auth_method="jwt",
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionPayload.model_validate_pb(proto_payload)

        assert restored.user_email == "admin@example.com"
        assert restored.is_admin is True
        assert restored.permission == "servers.write"

    def test_with_optional_fields_none(self):
        """Test HttpAuthCheckPermissionPayload with optional fields as None."""
        payload = HttpAuthCheckPermissionPayload(
            user_email="user@example.com",
            permission="prompts.read",
            resource_type=None,
            team_id=None,
            is_admin=False,
            auth_method=None,
            client_host=None,
            user_agent=None,
        )

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionPayload.model_validate_pb(proto_payload)

        assert restored.user_email == "user@example.com"
        assert restored.permission == "prompts.read"
        assert restored.resource_type is None
        assert restored.team_id is None
        assert restored.auth_method is None


class TestHttpAuthCheckPermissionResultPayloadConversion:
    """Test HttpAuthCheckPermissionResultPayload Pydantic <-> Protobuf conversion."""

    def test_granted_permission(self):
        """Test HttpAuthCheckPermissionResultPayload with granted permission."""
        payload = HttpAuthCheckPermissionResultPayload(granted=True, reason="API key has valid permissions")

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionResultPayload.model_validate_pb(proto_payload)

        assert restored.granted is True
        assert restored.reason == "API key has valid permissions"

    def test_denied_permission(self):
        """Test HttpAuthCheckPermissionResultPayload with denied permission."""
        payload = HttpAuthCheckPermissionResultPayload(granted=False, reason="Insufficient permissions")

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionResultPayload.model_validate_pb(proto_payload)

        assert restored.granted is False
        assert restored.reason == "Insufficient permissions"

    def test_without_reason(self):
        """Test HttpAuthCheckPermissionResultPayload without reason."""
        payload = HttpAuthCheckPermissionResultPayload(granted=True, reason=None)

        proto_payload = payload.model_dump_pb()
        restored = HttpAuthCheckPermissionResultPayload.model_validate_pb(proto_payload)

        assert restored.granted is True
        assert restored.reason is None

    def test_roundtrip_conversion(self):
        """Test multiple roundtrip conversions maintain data integrity."""
        payload = HttpAuthCheckPermissionResultPayload(granted=False, reason="Token expired")

        # Multiple roundtrips
        for _ in range(3):
            proto_payload = payload.model_dump_pb()
            payload = HttpAuthCheckPermissionResultPayload.model_validate_pb(proto_payload)

        assert payload.granted is False
        assert payload.reason == "Token expired"
