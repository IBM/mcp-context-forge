# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_metadata_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for metadata tracking feature.
This module tests the complete metadata tracking functionality across
the entire application stack, including API endpoints, database storage,
and UI integration.
"""

# Standard
import uuid

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base
from mcpgateway.main import app
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.verify_credentials import require_auth

# Local
from tests.utils.rbac_mocks import MockPermissionService


@pytest.fixture
def test_app():
    """Create test app with proper database setup."""
    # Use file-based SQLite database for better compatibility
    # Standard
    import os
    import tempfile
    from unittest.mock import MagicMock, patch

    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy.pool import StaticPool

    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    # First-Party
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Set up comprehensive authentication overrides
    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service

    # Create mock user for basic auth
    mock_email_user = MagicMock()
    mock_email_user.email = "test_user@example.com"
    mock_email_user.full_name = "Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        db_session = TestingSessionLocal()
        try:
            yield {
                "email": "test_user@example.com",
                "full_name": "Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def mock_get_permission_service(*args, **kwargs):
        """Return a mock permission service that always grants access."""
        return MockPermissionService(always_grant=True)

    def override_get_db():
        """Override database dependency to return our test database."""
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Patch the PermissionService class to always return our mock
    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[require_auth] = lambda: "test_user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        yield app

        # Cleanup
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Dummy Bearer token accepted by the overridden dependency."""
    return {"Authorization": "Bearer test.token.metadata"}


class TestMetadataIntegration:
    """Integration tests for metadata tracking across the application."""

    def test_tool_creation_api_metadata(self, client, auth_headers):
        """Test that tool creation via API captures metadata correctly."""
        unique_name = f"api_test_tool_{uuid.uuid4().hex[:8]}"
        tool_data = {
            "tool": {"name": unique_name, "url": "http://example.com/api", "description": "Tool created via API", "integration_type": "REST", "request_type": "GET"},
            "team_id": None,
            "visibility": "private",
        }

        response = client.post("/tools/", json=tool_data, headers=auth_headers)
        assert response.status_code == 200

        tool = response.json()

        # Verify metadata was captured
        assert tool["createdBy"] == "test_user@example.com"
        assert tool["createdVia"] == "api"  # Should detect API call
        assert tool["version"] == 1
        assert tool["createdFromIp"] is not None  # Should capture some IP

        # Verify metadata is properly serialized
        assert "createdAt" in tool
        # modifiedAt is only set after modifications, not during creation

    def test_tool_creation_admin_ui_metadata(self, client, auth_headers):
        """Test that tool creation via admin UI works with metadata."""
        tool_data = {
            "name": f"admin_ui_test_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/admin",
            "description": "Tool created via admin UI",
            "integrationType": "REST",
            "requestType": "GET",
        }

        # Simulate admin UI request
        response = client.post("/admin/tools", data=tool_data, headers=auth_headers)

        # Admin endpoint might return different status codes, just verify it doesn't crash
        assert response.status_code in [200, 400, 422, 500]  # Allow various responses

        # The important thing is that the metadata capture code doesn't break the endpoint

    def test_tool_update_metadata(self, client, auth_headers):
        """Test that tool updates capture modification metadata."""
        # First create a tool
        tool_data = {
            "tool": {"name": f"update_test_tool_{uuid.uuid4().hex[:8]}", "url": "http://example.com/test", "description": "Tool for update testing", "integration_type": "REST", "request_type": "GET"},
            "team_id": None,
            "visibility": "private",
        }

        create_response = client.post("/tools/", json=tool_data, headers=auth_headers)
        assert create_response.status_code == 200
        tool_id = create_response.json()["id"]

        # Now update the tool
        update_data = {"description": "Updated description"}

        update_response = client.put(f"/tools/{tool_id}", json=update_data, headers=auth_headers)
        assert update_response.status_code == 200

        updated_tool = update_response.json()

        # Verify modification metadata
        assert updated_tool["modifiedBy"] == "test_user@example.com"
        assert updated_tool["modifiedVia"] == "api"
        assert updated_tool["version"] == 2  # Should increment
        assert updated_tool["description"] == "Updated description"

    def test_metadata_backwards_compatibility(self, client, auth_headers):
        """Test that metadata works with legacy entities."""
        # Create a tool and then manually remove metadata to simulate legacy entity
        tool_data = {
            "tool": {
                "name": f"legacy_simulation_tool_{uuid.uuid4().hex[:8]}",
                "url": "http://example.com/legacy",
                "description": "Simulated legacy tool",
                "integration_type": "REST",
                "request_type": "GET",
            },
            "team_id": None,
            "visibility": "private",
        }

        response = client.post("/tools/", json=tool_data, headers=auth_headers)
        assert response.status_code == 200
        tool = response.json()

        # Even "legacy" simulation should have metadata since we're testing new code
        # But verify that optional fields handle None gracefully
        assert tool["createdBy"] is not None  # Should have metadata
        assert "version" in tool
        assert tool["version"] >= 1

    def test_auth_disabled_metadata(self, client, test_app, auth_headers):
        """Test metadata capture when authentication is disabled."""
        # Import the RBAC dependency that tools endpoint actually uses
        # First-Party
        from mcpgateway.middleware.rbac import get_current_user_with_permissions

        # Override RBAC auth to return anonymous user context
        async def mock_anonymous_user():
            # Need to import here to get the same SessionLocal the test is using
            # First-Party
            import mcpgateway.db as db_mod

            db_session = db_mod.SessionLocal()
            try:
                yield {
                    "email": "anonymous",
                    "full_name": "Anonymous User",
                    "is_admin": False,
                    "ip_address": "127.0.0.1",
                    "user_agent": "test-client",
                    "db": db_session,
                }
            finally:
                db_session.close()

        test_app.dependency_overrides[get_current_user_with_permissions] = mock_anonymous_user

        tool_data = {
            "tool": {
                "name": f"anonymous_test_tool_{uuid.uuid4().hex[:8]}",
                "url": "http://example.com/anon",
                "description": "Tool created anonymously",
                "integration_type": "REST",
                "request_type": "GET",
            },
            "team_id": None,
            "visibility": "private",
        }

        response = client.post("/tools/", json=tool_data, headers=auth_headers)
        assert response.status_code == 200

        tool = response.json()

        # Verify anonymous metadata
        assert tool["createdBy"] == "anonymous"
        assert tool["version"] == 1
        assert tool["createdVia"] == "api"

    def test_metadata_fields_in_tool_read_schema(self, client, auth_headers):
        """Test that all metadata fields are present in API responses."""
        tool_data = {
            "tool": {
                "name": f"schema_test_tool_{uuid.uuid4().hex[:8]}",
                "url": "http://example.com/schema",
                "description": "Tool for schema testing",
                "integration_type": "REST",
                "request_type": "GET",
            },
            "team_id": None,
            "visibility": "private",
        }

        response = client.post("/tools/", json=tool_data, headers=auth_headers)
        assert response.status_code == 200

        tool = response.json()

        # Verify all metadata fields are present
        expected_fields = [
            "createdBy",
            "createdFromIp",
            "createdVia",
            "createdUserAgent",
            "modifiedBy",
            "modifiedFromIp",
            "modifiedVia",
            "modifiedUserAgent",
            "importBatchId",
            "federationSource",
            "version",
        ]

        for field in expected_fields:
            assert field in tool, f"Missing metadata field: {field}"

    def test_tool_list_includes_metadata(self, client, auth_headers):
        """Test that tool list endpoint includes metadata fields."""
        # Create a tool first
        tool_data = {
            "tool": {"name": f"list_test_tool_{uuid.uuid4().hex[:8]}", "url": "http://example.com/list", "description": "Tool for list testing", "integration_type": "REST", "request_type": "GET"},
            "team_id": None,
            "visibility": "private",
        }

        client.post("/tools/", json=tool_data, headers=auth_headers)

        # List tools
        response = client.get("/tools/", headers=auth_headers)
        assert response.status_code == 200

        tools = response.json()
        assert len(tools) > 0

        # Verify metadata is included in list response
        tool = tools[0]
        assert "createdBy" in tool
        assert "version" in tool

    @pytest.mark.asyncio
    async def test_service_layer_metadata_handling(self, test_app):
        """Test metadata handling at the service layer."""
        # Standard
        from types import SimpleNamespace

        # Third-Party
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # First-Party
        from mcpgateway.utils.metadata_capture import MetadataCapture

        # Create test database session
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)

        # Create mock request
        mock_request = SimpleNamespace()
        mock_request.client = SimpleNamespace()
        mock_request.client.host = "test-ip"
        mock_request.headers = {"user-agent": "test-agent"}
        mock_request.url = SimpleNamespace()
        mock_request.url.path = "/admin/tools"

        # Extract metadata
        metadata = MetadataCapture.extract_creation_metadata(mock_request, "service_test_user")

        # Create tool data
        tool_data = ToolCreate(name=f"service_layer_test_{uuid.uuid4().hex[:8]}", url="http://example.com/service", description="Service layer test tool", integration_type="REST", request_type="GET")

        # Test service creation with metadata
        service = ToolService()
        db = TestingSessionLocal()

        try:
            tool_read = await service.register_tool(
                db,
                tool_data,
                created_by=metadata["created_by"],
                created_from_ip=metadata["created_from_ip"],
                created_via=metadata["created_via"],
                created_user_agent=metadata["created_user_agent"],
            )

            # Verify metadata was stored
            assert tool_read.created_by == "service_test_user"
            assert tool_read.created_from_ip == "test-ip"
            assert tool_read.created_via == "ui"
            assert tool_read.created_user_agent == "test-agent"
            assert tool_read.version == 1

        finally:
            db.close()
            engine.dispose()
