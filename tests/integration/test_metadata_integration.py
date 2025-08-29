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
from types import SimpleNamespace

# Third-Party
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.db import get_db, SessionLocal
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.utils.metadata_capture import MetadataCapture


# --------------------------------------------------------------------------------------
# Test client bound to the isolated, patched DB from conftest.py (client_with_temp_db)
# --------------------------------------------------------------------------------------
@pytest.fixture
def client(client_with_temp_db: TestClient):
    """
    Provide a TestClient tied to the in-memory/temp DB.
    Ensures API code paths use the same patched SessionLocal as services.
    """
    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    client_with_temp_db.app.dependency_overrides[get_db] = _override_get_db
    client_with_temp_db.app.dependency_overrides[require_auth] = lambda: "test_user"

    from mcpgateway.admin import get_db as admin_get_db
    client_with_temp_db.app.dependency_overrides[admin_get_db] = _override_get_db

    return client_with_temp_db


class TestMetadataIntegration:
    """Integration tests for metadata tracking across the application."""

    def test_tool_creation_api_metadata(self, client: TestClient):
        """Tool creation via API captures metadata correctly."""
        unique_name = f"api_test_tool_{uuid.uuid4().hex[:8]}"
        tool_data = {
            "name": unique_name,
            "url": "http://example.com/api",
            "description": "Tool created via API",
            "integration_type": "REST",
            "request_type": "GET",
        }

        response = client.post("/tools", json=tool_data)
        assert response.status_code == 200, response.text

        tool = response.json()
        assert tool["createdBy"] == "test_user"
        assert tool["createdVia"] == "api"
        assert tool["version"] == 1
        assert tool.get("createdFromIp") is not None
        assert "createdAt" in tool

    def test_tool_update_metadata(self, client: TestClient):
        """Updates capture modification metadata and version increments."""
        tool_data = {
            "name": f"update_test_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/test",
            "description": "Tool for update testing",
            "integration_type": "REST",
            "request_type": "GET",
        }

        create_response = client.post("/tools", json=tool_data)
        assert create_response.status_code == 200, create_response.text
        tool_id = create_response.json()["id"]

        update_data = {"description": "Updated description"}
        update_response = client.put(f"/tools/{tool_id}", json=update_data)
        assert update_response.status_code == 200, update_response.text

        updated_tool = update_response.json()
        assert updated_tool["modifiedBy"] == "test_user"
        assert updated_tool["modifiedVia"] == "api"
        assert updated_tool["version"] == 2
        assert updated_tool["description"] == "Updated description"

    def test_metadata_backwards_compatibility(self, client: TestClient):
        """Creating a tool still produces expected metadata assumptions."""
        tool_data = {
            "name": f"legacy_simulation_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/legacy",
            "description": "Simulated legacy tool",
            "integration_type": "REST",
            "request_type": "GET",
        }

        response = client.post("/tools", json=tool_data)
        assert response.status_code == 200, response.text
        tool = response.json()

        assert tool["createdBy"] is not None
        assert "version" in tool and tool["version"] >= 1

    def test_auth_disabled_metadata(self, client: TestClient):
        """When auth is overridden to 'anonymous', metadata should reflect it."""
        client.app.dependency_overrides[require_auth] = lambda: "anonymous"

        tool_data = {
            "name": f"anonymous_test_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/anon",
            "description": "Tool created anonymously",
            "integration_type": "REST",
            "request_type": "GET",
        }

        response = client.post("/tools", json=tool_data)
        assert response.status_code == 200, response.text
        tool = response.json()

        assert tool["createdBy"] == "anonymous"
        assert tool["version"] == 1
        assert tool["createdVia"] == "api"

    def test_metadata_fields_in_tool_read_schema(self, client: TestClient):
        """All expected metadata fields are present in API responses (create path)."""
        tool_data = {
            "name": f"schema_test_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/schema",
            "description": "Tool for schema testing",
            "integration_type": "REST",
            "request_type": "GET",
        }

        response = client.post("/tools", json=tool_data)
        assert response.status_code == 200, response.text
        tool = response.json()

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

    def test_tool_list_includes_metadata(self, client: TestClient):
        """List endpoint should include metadata for items."""
        tool_data = {
            "name": f"list_test_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/list",
            "description": "Tool for list testing",
            "integration_type": "REST",
            "request_type": "GET",
        }
        client.post("/tools", json=tool_data)

        response = client.get("/tools")
        assert response.status_code == 200, response.text

        tools = response.json()
        assert isinstance(tools, list) and len(tools) > 0
        sample = tools[0]
        assert "createdBy" in sample
        assert "version" in sample

    @pytest.mark.asyncio
    async def test_service_layer_metadata_handling(self, test_db):
        """Test metadata handling directly via the service layer using the test DB fixture."""
        # Simulate a FastAPI request object for metadata extraction
        mock_request = SimpleNamespace()
        mock_request.client = SimpleNamespace()
        mock_request.client.host = "test-ip"
        mock_request.headers = {"user-agent": "test-agent"}
        mock_request.url = SimpleNamespace()
        mock_request.url.path = "/admin/tools"

        metadata = MetadataCapture.extract_creation_metadata(mock_request, "service_test_user")

        tool_data = ToolCreate(
            name=f"service_layer_test_{uuid.uuid4().hex[:8]}",
            url="http://example.com/service",
            description="Service layer test tool",
            integration_type="REST",
            request_type="GET",
        )

        service = ToolService()
        tool_read = await service.register_tool(
            test_db,
            tool_data,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
        )

        assert tool_read.created_by == "service_test_user"
        assert tool_read.created_from_ip == "test-ip"
        assert tool_read.created_via == "ui"   # path "/admin" should map to ui
        assert tool_read.created_user_agent == "test-agent"
        assert tool_read.version == 1
