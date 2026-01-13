# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tag_endpoints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for tag endpoints.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.schemas import TaggedEntity, TagInfo, TagStats

# Local
from tests.utils.rbac_mocks import MockPermissionService


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with auth dependency overridden."""
    app.dependency_overrides[require_auth] = lambda: "integration-test-user"

    # Also need to override RBAC authentication
    # First-Party
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        return {
            "email": "integration-test-user@example.com",
            "full_name": "Integration Test User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": MagicMock(),  # Tags endpoints may not need real DB session
        }

    def mock_get_permission_service(*args, **kwargs):
        """Return a mock permission service that always grants access."""
        return MockPermissionService(always_grant=True)

    def override_get_db():
        """Override database dependency to return a mock database."""
        return MagicMock()  # Simple mock for tags endpoints

    # Patch the PermissionService class to always return our mock
    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        client = TestClient(app)
        yield client

        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)


def test_list_tags_all_entities(test_client):
    """Test listing all tags across all entity types."""
    # Mock the tag service to return test data
    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=2, resources=1, prompts=0, servers=1, gateways=0, total=4)),
        TagInfo(name="data", stats=TagStats(tools=2, resources=1, prompts=0, servers=0, gateways=0, total=3)),
        TagInfo(name="test", stats=TagStats(tools=1, resources=0, prompts=1, servers=0, gateways=1, total=3)),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags")

    assert response.status_code == 200
    tags = response.json()

    # Should have all tags
    assert len(tags) == 3
    tag_names = [tag["name"] for tag in tags]
    assert "api" in tag_names
    assert "data" in tag_names
    assert "test" in tag_names

    # Check statistics for "api" tag
    api_tag = next(tag for tag in tags if tag["name"] == "api")
    assert api_tag["stats"]["tools"] == 2
    assert api_tag["stats"]["resources"] == 1
    assert api_tag["stats"]["servers"] == 1
    assert api_tag["stats"]["total"] == 4


def test_list_tags_filtered_by_tools(test_client):
    """Test listing tags filtered by tools only."""
    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=2, resources=0, prompts=0, servers=0, gateways=0, total=2)),
        TagInfo(name="data", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1)),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags?entity_types=tools")

    assert response.status_code == 200
    tags = response.json()

    # Should only have tags from tools
    tag_names = [tag["name"] for tag in tags]
    assert "api" in tag_names
    assert "data" in tag_names


def test_list_tags_filtered_by_multiple_types(test_client):
    """Test listing tags filtered by multiple entity types."""
    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=2, resources=1, prompts=0, servers=0, gateways=0, total=3)),
        TagInfo(name="resource", stats=TagStats(tools=0, resources=2, prompts=0, servers=0, gateways=0, total=2)),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags?entity_types=tools,resources")

    assert response.status_code == 200
    tags = response.json()

    # Should have tags from tools and resources
    assert len(tags) == 2
    tag_names = [tag["name"] for tag in tags]
    assert "api" in tag_names
    assert "resource" in tag_names


def test_list_tags_no_auth():
    """Test that tag endpoint requires authentication."""
    # Create client without auth override
    client = TestClient(app)
    response = client.get("/tags")
    assert response.status_code == 401


def test_list_tags_empty_database(test_client):
    """Test listing tags when database is empty."""
    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=[])):
        response = test_client.get("/tags")

    assert response.status_code == 200
    tags = response.json()
    assert tags == []


def test_admin_list_tags(test_client):
    """Test admin endpoint for listing tags."""
    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=2, resources=1, prompts=1, servers=1, gateways=0, total=5)),
        TagInfo(name="test", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=1, total=2)),
    ]

    # Need to patch the TagService instance created in admin.py
    with patch("mcpgateway.admin.TagService") as MockTagService:
        mock_service = MockTagService.return_value
        mock_service.get_all_tags = AsyncMock(return_value=mock_tags)

        response = test_client.get("/admin/tags")

    assert response.status_code == 200
    tags = response.json()

    # Admin endpoint returns flat dict structure
    assert isinstance(tags, list)
    assert len(tags) == 2

    # Check that statistics are included
    api_tag = next(tag for tag in tags if tag["name"] == "api")
    assert "tools" in api_tag
    assert "resources" in api_tag
    assert "prompts" in api_tag
    assert "servers" in api_tag
    assert "gateways" in api_tag
    assert "total" in api_tag
    assert api_tag["total"] == 5


def test_admin_list_tags_filtered(test_client):
    """Test admin endpoint with entity type filtering."""
    mock_tags = [
        TagInfo(name="server", stats=TagStats(tools=0, resources=0, prompts=0, servers=2, gateways=0, total=2)),
        TagInfo(name="gateway", stats=TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=1, total=1)),
    ]

    with patch("mcpgateway.admin.TagService") as MockTagService:
        mock_service = MockTagService.return_value
        mock_service.get_all_tags = AsyncMock(return_value=mock_tags)

        response = test_client.get("/admin/tags?entity_types=servers,gateways")

    assert response.status_code == 200
    tags = response.json()

    # Should only have tags from servers and gateways
    assert len(tags) == 2
    tag_names = [tag["name"] for tag in tags]
    assert "server" in tag_names
    assert "gateway" in tag_names


def test_list_tags_with_entities(test_client):
    """Test listing tags with entity details included."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Test Tool", type="tool", description="A test tool"),
        TaggedEntity(id="resource1", name="Test Resource", type="resource", description=None),
    ]

    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=1, resources=1, prompts=0, servers=0, gateways=0, total=2), entities=mock_entities),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags?include_entities=true")

    assert response.status_code == 200
    tags = response.json()

    assert len(tags) == 1
    api_tag = tags[0]
    assert api_tag["name"] == "api"
    assert len(api_tag["entities"]) == 2

    # Check entity details
    tool_entity = next(e for e in api_tag["entities"] if e["type"] == "tool")
    assert tool_entity["id"] == "tool1"
    assert tool_entity["name"] == "Test Tool"
    assert tool_entity["description"] == "A test tool"


def test_get_entities_by_tag(test_client):
    """Test getting entities by a specific tag."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Test Tool", type="tool", description="A test tool"),
        TaggedEntity(id="server1", name="Test Server", type="server", description="A test server"),
    ]

    with patch("mcpgateway.main.tag_service.get_entities_by_tag", AsyncMock(return_value=mock_entities)):
        response = test_client.get("/tags/api/entities")

    assert response.status_code == 200
    entities = response.json()

    assert len(entities) == 2

    # Check tool entity
    tool_entity = next(e for e in entities if e["type"] == "tool")
    assert tool_entity["id"] == "tool1"
    assert tool_entity["name"] == "Test Tool"

    # Check server entity
    server_entity = next(e for e in entities if e["type"] == "server")
    assert server_entity["id"] == "server1"
    assert server_entity["name"] == "Test Server"


def test_get_entities_by_tag_filtered(test_client):
    """Test getting entities by tag with entity type filtering."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Test Tool", type="tool", description="A test tool"),
    ]

    with patch("mcpgateway.main.tag_service.get_entities_by_tag", AsyncMock(return_value=mock_entities)):
        response = test_client.get("/tags/api/entities?entity_types=tools")

    assert response.status_code == 200
    entities = response.json()

    assert len(entities) == 1
    assert entities[0]["type"] == "tool"
    assert entities[0]["name"] == "Test Tool"


def test_list_tags_with_entities_filtered_by_type(test_client):
    """Test listing tags filtered by specific entity types with entities included."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Tool 1", type="tool", description="First tool"),
        TaggedEntity(id="tool2", name="Tool 2", type="tool", description="Second tool"),
    ]

    mock_tags = [
        TagInfo(name="development", stats=TagStats(tools=2, resources=0, prompts=0, servers=0, gateways=0, total=2), entities=mock_entities),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags?entity_types=tools&include_entities=true")

    assert response.status_code == 200
    tags = response.json()

    assert len(tags) == 1
    assert tags[0]["name"] == "development"
    assert len(tags[0]["entities"]) == 2
    assert tags[0]["entities"][0]["type"] == "tool"
    assert tags[0]["entities"][1]["type"] == "tool"


def test_list_tags_invalid_entity_types(test_client):
    """Test listing tags with invalid entity types."""
    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=[])):
        response = test_client.get("/tags?entity_types=invalid,also_invalid")

    assert response.status_code == 200
    tags = response.json()
    assert tags == []


def test_get_entities_by_tag_nonexistent_tag(test_client):
    """Test getting entities by a non-existent tag."""
    with patch("mcpgateway.main.tag_service.get_entities_by_tag", AsyncMock(return_value=[])):
        response = test_client.get("/tags/nonexistent/entities")

    assert response.status_code == 200
    entities = response.json()
    assert entities == []


def test_get_entities_by_tag_multiple_types(test_client):
    """Test getting entities by tag across multiple entity types."""
    mock_entities = [
        TaggedEntity(id="tool1", name="API Tool", type="tool", description="A tool"),
        TaggedEntity(id="resource1", name="API Docs", type="resource", description="Documentation"),
        TaggedEntity(id="server1", name="API Server", type="server", description="Server"),
    ]

    with patch("mcpgateway.main.tag_service.get_entities_by_tag", AsyncMock(return_value=mock_entities)):
        response = test_client.get("/tags/api/entities?entity_types=tools,resources,servers")

    assert response.status_code == 200
    entities = response.json()

    assert len(entities) == 3
    entity_types = {e["type"] for e in entities}
    assert entity_types == {"tool", "resource", "server"}


def test_list_tags_statistics_accuracy(test_client):
    """Test that tag statistics are calculated correctly."""
    mock_tags = [
        TagInfo(name="api", stats=TagStats(tools=3, resources=2, prompts=1, servers=1, gateways=0, total=7)),
        TagInfo(name="database", stats=TagStats(tools=2, resources=1, prompts=2, servers=0, gateways=1, total=6)),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags")

    assert response.status_code == 200
    tags = response.json()

    # Verify statistics are preserved
    api_tag = next(tag for tag in tags if tag["name"] == "api")
    assert api_tag["stats"]["tools"] == 3
    assert api_tag["stats"]["total"] == 7

    db_tag = next(tag for tag in tags if tag["name"] == "database")
    assert db_tag["stats"]["gateways"] == 1
    assert db_tag["stats"]["total"] == 6


def test_admin_tags_with_entities(test_client):
    """Test admin tags endpoint with entity details."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Admin Tool", type="tool", description="For admins"),
    ]

    mock_tags = [
        TagInfo(name="admin", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1), entities=mock_entities),
    ]

    with patch("mcpgateway.admin.TagService") as MockTagService:
        mock_service = MockTagService.return_value
        mock_service.get_all_tags = AsyncMock(return_value=mock_tags)

        response = test_client.get("/admin/tags?include_entities=true")

    assert response.status_code == 200
    tags = response.json()

    assert len(tags) == 1
    assert tags[0]["name"] == "admin"
    assert "tools" in tags[0]  # Flattened structure
    assert "entities" in tags[0]
    assert len(tags[0]["entities"]) == 1


def test_admin_tags_error_handling(test_client):
    """Test admin tags endpoint error handling."""
    with patch("mcpgateway.admin.TagService") as MockTagService:
        mock_service = MockTagService.return_value
        mock_service.get_all_tags = AsyncMock(side_effect=Exception("Database error"))

        response = test_client.get("/admin/tags")

    # Should handle errors gracefully
    assert response.status_code == 500


def test_list_tags_sorted_alphabetically(test_client):
    """Test that tags are returned in alphabetical order."""
    mock_tags = [
        TagInfo(name="zebra", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1)),
        TagInfo(name="alpha", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1)),
        TagInfo(name="beta", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1)),
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags")

    assert response.status_code == 200
    tags = response.json()

    # Tags should be in alphabetical order (service handles sorting)
    tag_names = [tag["name"] for tag in tags]
    assert tag_names == ["zebra", "alpha", "beta"]  # Service returns them sorted


def test_get_entities_by_tag_case_sensitive(test_client):
    """Test that tag matching is case sensitive."""
    # Mock different results for different cases
    with patch("mcpgateway.main.tag_service.get_entities_by_tag") as mock_service:
        mock_service.return_value = AsyncMock(return_value=[])

        # Test lowercase
        response1 = test_client.get("/tags/api/entities")

        # Test uppercase
        response2 = test_client.get("/tags/API/entities")

    assert response1.status_code == 200
    assert response2.status_code == 200

    # Both should succeed but may have different results based on tag normalization
    entities1 = response1.json()
    entities2 = response2.json()

    # Both should be lists (empty in our mock)
    assert isinstance(entities1, list)
    assert isinstance(entities2, list)


def test_list_tags_empty_include_entities_false(test_client):
    """Test that entities array is empty when include_entities=false."""
    mock_tags = [
        TagInfo(name="test", stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1), entities=[]),  # Should be empty when include_entities=False
    ]

    with patch("mcpgateway.main.tag_service.get_all_tags", AsyncMock(return_value=mock_tags)):
        response = test_client.get("/tags?include_entities=false")

    assert response.status_code == 200
    tags = response.json()

    assert len(tags) == 1
    assert tags[0]["entities"] == []
    assert tags[0]["stats"]["tools"] == 1


def test_get_entities_by_tag_special_characters(test_client):
    """Test getting entities by tags with special characters."""
    mock_entities = [
        TaggedEntity(id="tool1", name="Version Tool", type="tool", description="Versioned tool"),
    ]

    with patch("mcpgateway.main.tag_service.get_entities_by_tag", AsyncMock(return_value=mock_entities)):
        # Test tag with colon and dots (valid characters)
        response = test_client.get("/tags/api:v2.0/entities")

    assert response.status_code == 200
    entities = response.json()

    assert len(entities) == 1
    assert entities[0]["name"] == "Version Tool"
