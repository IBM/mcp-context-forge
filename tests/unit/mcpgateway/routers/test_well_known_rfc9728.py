# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_well_known_rfc9728.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for RFC 9728 OAuth Protected Resource Metadata compliance.

Tests the new RFC 9728 compliant endpoint at:
/.well-known/oauth-protected-resource/servers/{server_id}/mcp

And verifies deprecation of old non-compliant endpoints:
- /.well-known/oauth-protected-resource?server_id={id} (query-param, returns 404)
- /servers/{server_id}/.well-known/oauth-protected-resource (server-scoped, returns 301)
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from mcpgateway.db import get_db
from mcpgateway.services.server_service import ServerError, ServerNotFoundError


@pytest.fixture
def mock_server():
    """Create a mock server object with OAuth configuration."""
    server = MagicMock()
    server.id = "550e8400-e29b-41d4-a716-446655440000"
    server.enabled = True
    server.visibility = "public"
    server.oauth_enabled = True
    server.oauth_config = {
        "authorization_servers": ["https://auth.example.com"],
        "scopes_supported": ["read", "write"]
    }
    return server


class TestRFC9728CompliantEndpoint:
    """Tests for the RFC 9728 compliant path-based endpoint."""

    def test_rfc9728_endpoint_success(self, app, mock_server):
        """Test successful RFC 9728 metadata retrieval."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        mock_service_instance = MagicMock()
        mock_service_instance.get_oauth_protected_resource_metadata.return_value = {
            "resource": "http://testserver/servers/550e8400-e29b-41d4-a716-446655440000/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["read", "write"]
        }

        client = TestClient(app)

        with patch("mcpgateway.services.server_service.server_service", mock_service_instance):
            response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp")

            assert response.status_code == 200
            data = response.json()

            # Verify RFC 9728 compliance
            assert "resource" in data
            assert data["resource"].endswith("/mcp")
            assert "authorization_servers" in data
            assert isinstance(data["authorization_servers"], list)
            assert data["authorization_servers"] == ["https://auth.example.com"]
            assert data["bearer_methods_supported"] == ["header"]
            assert data["scopes_supported"] == ["read", "write"]

            # Verify cache headers
            assert "Cache-Control" in response.headers

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_without_mcp_suffix(self, app):
        """Test RFC 9728 endpoint accepts path without /mcp suffix."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        mock_service_instance = MagicMock()
        mock_service_instance.get_oauth_protected_resource_metadata.return_value = {
            "resource": "http://testserver/servers/550e8400-e29b-41d4-a716-446655440000/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "bearer_methods_supported": ["header"]
        }

        client = TestClient(app)

        with patch("mcpgateway.services.server_service.server_service", mock_service_instance):
            response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000")

            assert response.status_code == 200

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_invalid_path_format(self, app):
        """Test RFC 9728 endpoint rejects invalid path formats."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        # Missing 'servers' prefix
        response = client.get("/.well-known/oauth-protected-resource/test-server-123/mcp")
        assert response.status_code == 404
        assert "Invalid resource path format" in response.json()["detail"]

        # Wrong prefix
        response = client.get("/.well-known/oauth-protected-resource/gateways/test-server-123/mcp")
        assert response.status_code == 404

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_invalid_uuid(self, app):
        """Test RFC 9728 endpoint rejects non-UUID server IDs."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        # Not a valid UUID
        response = client.get("/.well-known/oauth-protected-resource/servers/not-a-uuid/mcp")
        assert response.status_code == 404
        assert "Invalid server_id format" in response.json()["detail"]

        # Path traversal attempt
        response = client.get("/.well-known/oauth-protected-resource/servers/../admin/mcp")
        assert response.status_code == 404

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_extra_path_segments(self, app):
        """Test RFC 9728 endpoint rejects paths with extra segments."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp/extra")
        assert response.status_code == 404
        assert "Invalid resource path format" in response.json()["detail"]

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_server_not_found(self, app):
        """Test RFC 9728 endpoint returns 404 for non-existent server."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        mock_service_instance = MagicMock()
        mock_service_instance.get_oauth_protected_resource_metadata.side_effect = ServerNotFoundError("Server not found")

        client = TestClient(app)

        with patch("mcpgateway.services.server_service.server_service", mock_service_instance):
            response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp")

            assert response.status_code == 404
            assert "Server not found" in response.json()["detail"]

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_oauth_not_enabled(self, app):
        """Test RFC 9728 endpoint returns 404 when OAuth not enabled."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        mock_service_instance = MagicMock()
        mock_service_instance.get_oauth_protected_resource_metadata.side_effect = ServerError("OAuth not enabled")

        client = TestClient(app)

        with patch("mcpgateway.services.server_service.server_service", mock_service_instance):
            response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_db, None)

    def test_rfc9728_endpoint_well_known_disabled(self, app):
        """Test RFC 9728 endpoint returns 404 when well-known endpoints disabled."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        with patch("mcpgateway.routers.well_known.settings") as mock_settings:
            mock_settings.well_known_enabled = False
            mock_settings.well_known_cache_max_age = 3600

            response = client.get("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_db, None)


class TestDeprecatedQueryParamEndpoint:
    """Tests for the deprecated query-param based endpoint."""

    def test_query_param_endpoint_returns_404(self, app):
        """Test deprecated query-param endpoint returns 404."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/.well-known/oauth-protected-resource?server_id=test-server-123")

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "deprecated" in detail.lower()
        assert "RFC 9728" in detail
        assert "path-based" in detail.lower()

        app.dependency_overrides.pop(get_db, None)

    def test_query_param_endpoint_without_server_id(self, app):
        """Test deprecated query-param endpoint without server_id returns 404."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/.well-known/oauth-protected-resource")

        assert response.status_code == 404

        app.dependency_overrides.pop(get_db, None)


class TestDeprecatedServerScopedEndpoint:
    """Tests for the deprecated server-scoped endpoint."""

    def test_server_scoped_endpoint_returns_301(self, app):
        """Test deprecated server-scoped endpoint returns 301 redirect."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/servers/550e8400-e29b-41d4-a716-446655440000/.well-known/oauth-protected-resource", follow_redirects=False)

        assert response.status_code == 301
        assert "Location" in response.headers

        # Verify redirect points to RFC 9728 compliant endpoint
        location = response.headers["Location"]
        assert "/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp" in location

        app.dependency_overrides.pop(get_db, None)


class TestServiceLayerRFC9728Compliance:
    """Tests for server_service.py RFC 9728 compliance."""

    def test_service_returns_authorization_servers_array(self, mock_server):
        """Test service layer returns authorization_servers as JSON array per RFC 9728."""
        from mcpgateway.services.server_service import ServerService

        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        result = service.get_oauth_protected_resource_metadata(
            db=mock_db,
            server_id="550e8400-e29b-41d4-a716-446655440000",
            resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
        )

        # Verify RFC 9728 compliance: authorization_servers is plural, array
        assert "authorization_servers" in result
        assert isinstance(result["authorization_servers"], list)
        assert result["authorization_servers"] == ["https://auth.example.com"]
        assert result["resource"] == "http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"

    def test_service_plural_config(self, mock_server):
        """Test service handles authorization_servers config with multiple servers."""
        from mcpgateway.services.server_service import ServerService

        mock_server.oauth_config = {
            "authorization_servers": ["https://auth.example.com", "https://backup.example.com"],
            "scopes_supported": ["read"]
        }
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        result = service.get_oauth_protected_resource_metadata(
            db=mock_db,
            server_id="550e8400-e29b-41d4-a716-446655440000",
            resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
        )

        assert "authorization_servers" in result
        assert result["authorization_servers"] == ["https://auth.example.com", "https://backup.example.com"]
        assert isinstance(result["authorization_servers"], list)

    def test_service_singular_config_fallback(self, mock_server):
        """Test service reads singular authorization_server config as fallback."""
        from mcpgateway.services.server_service import ServerService

        # Configure with singular form only (legacy)
        mock_server.oauth_config = {
            "authorization_server": "https://primary.example.com",
            "scopes_supported": ["read"]
        }
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        result = service.get_oauth_protected_resource_metadata(
            db=mock_db,
            server_id="550e8400-e29b-41d4-a716-446655440000",
            resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
        )

        # Should wrap singular value into array for RFC 9728 response
        assert result["authorization_servers"] == ["https://primary.example.com"]
        assert isinstance(result["authorization_servers"], list)

    def test_service_resource_url_includes_mcp_suffix(self, mock_server):
        """Test service preserves /mcp suffix in resource URL."""
        from mcpgateway.services.server_service import ServerService

        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        result = service.get_oauth_protected_resource_metadata(
            db=mock_db,
            server_id="550e8400-e29b-41d4-a716-446655440000",
            resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
        )

        assert result["resource"].endswith("/mcp")

    def test_service_disabled_server_raises_not_found(self, mock_server):
        """Test service raises ServerNotFoundError for disabled servers."""
        from mcpgateway.services.server_service import ServerService

        mock_server.enabled = False
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        with pytest.raises(ServerNotFoundError):
            service.get_oauth_protected_resource_metadata(
                db=mock_db,
                server_id="550e8400-e29b-41d4-a716-446655440000",
                resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
            )

    def test_service_non_public_server_raises_not_found(self, mock_server):
        """Test service raises ServerNotFoundError for non-public servers."""
        from mcpgateway.services.server_service import ServerService

        mock_server.visibility = "private"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        with pytest.raises(ServerNotFoundError):
            service.get_oauth_protected_resource_metadata(
                db=mock_db,
                server_id="550e8400-e29b-41d4-a716-446655440000",
                resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
            )

    def test_service_oauth_not_enabled_raises_error(self, mock_server):
        """Test service raises ServerError when OAuth not enabled."""
        from mcpgateway.services.server_service import ServerService

        mock_server.oauth_enabled = False
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server
        service = ServerService()

        with pytest.raises(ServerError, match="OAuth not enabled"):
            service.get_oauth_protected_resource_metadata(
                db=mock_db,
                server_id="550e8400-e29b-41d4-a716-446655440000",
                resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
            )


class TestRFC9728SecurityValidation:
    """Security tests for RFC 9728 endpoint."""

    def test_path_traversal_prevention(self, app):
        """Test endpoint prevents path traversal attacks."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        # Various path traversal attempts
        traversal_attempts = [
            "/.well-known/oauth-protected-resource/servers/../admin/mcp",
            "/.well-known/oauth-protected-resource/servers/../../etc/passwd/mcp",
            "/.well-known/oauth-protected-resource/servers/%2e%2e%2fadmin/mcp",
        ]

        for path in traversal_attempts:
            response = client.get(path)
            assert response.status_code == 404, f"Path traversal not blocked: {path}"

        app.dependency_overrides.pop(get_db, None)

    def test_sql_injection_prevention(self, app):
        """Test endpoint prevents SQL injection in server_id."""
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        # SQL injection attempts
        injection_attempts = [
            "/.well-known/oauth-protected-resource/servers/'; DROP TABLE servers; --/mcp",
            "/.well-known/oauth-protected-resource/servers/1' OR '1'='1/mcp",
        ]

        for path in injection_attempts:
            response = client.get(path)
            assert response.status_code == 404, f"SQL injection not blocked: {path}"

        app.dependency_overrides.pop(get_db, None)

    def test_only_public_servers_exposed(self, mock_server):
        """Test only public servers expose OAuth metadata."""
        from mcpgateway.services.server_service import ServerService

        service = ServerService()

        # Test private server
        mock_server.visibility = "private"
        mock_db = MagicMock()
        mock_db.get.return_value = mock_server

        with pytest.raises(ServerNotFoundError):
            service.get_oauth_protected_resource_metadata(
                db=mock_db,
                server_id="550e8400-e29b-41d4-a716-446655440000",
                resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
            )

        # Test team server
        mock_server.visibility = "team"
        with pytest.raises(ServerNotFoundError):
            service.get_oauth_protected_resource_metadata(
                db=mock_db,
                server_id="550e8400-e29b-41d4-a716-446655440000",
                resource_base_url="http://localhost:4444/servers/550e8400-e29b-41d4-a716-446655440000/mcp"
            )
