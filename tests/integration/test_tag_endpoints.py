# -*- coding: utf-8 -*-
"""Integration tests for tag endpoints."""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from mcpgateway.main import app, require_auth
from mcpgateway.schemas import TagInfo, TagStats


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with auth dependency overridden."""
    app.dependency_overrides[require_auth] = lambda: "integration-test-user"
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(require_auth, None)


def test_list_tags_all_entities(test_client):
    """Test listing all tags across all entity types."""
    # Mock the tag service to return test data
    mock_tags = [
        TagInfo(
            name="api",
            stats=TagStats(tools=2, resources=1, prompts=0, servers=1, gateways=0, total=4)
        ),
        TagInfo(
            name="data", 
            stats=TagStats(tools=2, resources=1, prompts=0, servers=0, gateways=0, total=3)
        ),
        TagInfo(
            name="test",
            stats=TagStats(tools=1, resources=0, prompts=1, servers=0, gateways=1, total=3)
        ),
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
        TagInfo(
            name="api",
            stats=TagStats(tools=2, resources=0, prompts=0, servers=0, gateways=0, total=2)
        ),
        TagInfo(
            name="data",
            stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=0, total=1)
        ),
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
        TagInfo(
            name="api",
            stats=TagStats(tools=2, resources=1, prompts=0, servers=0, gateways=0, total=3)
        ),
        TagInfo(
            name="resource",
            stats=TagStats(tools=0, resources=2, prompts=0, servers=0, gateways=0, total=2)
        ),
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
        TagInfo(
            name="api",
            stats=TagStats(tools=2, resources=1, prompts=1, servers=1, gateways=0, total=5)
        ),
        TagInfo(
            name="test",
            stats=TagStats(tools=1, resources=0, prompts=0, servers=0, gateways=1, total=2)
        ),
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
        TagInfo(
            name="server",
            stats=TagStats(tools=0, resources=0, prompts=0, servers=2, gateways=0, total=2)
        ),
        TagInfo(
            name="gateway",
            stats=TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=1, total=1)
        ),
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