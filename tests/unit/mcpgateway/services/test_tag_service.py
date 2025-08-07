# -*- coding: utf-8 -*-
"""Tests for Tag Service."""

import pytest
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from mcpgateway.services.tag_service import TagService
from mcpgateway.schemas import TaggedEntity, TagInfo, TagStats


@pytest.fixture
def tag_service():
    """Create a tag service instance."""
    return TagService()


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.mark.asyncio
async def test_get_all_tags_empty(tag_service, mock_db):
    """Test getting tags when no entities have tags."""
    # Mock database queries to return empty results
    mock_db.execute.return_value.fetchall.return_value = []
    mock_db.execute.return_value.__iter__ = lambda self: iter([])

    tags = await tag_service.get_all_tags(mock_db)

    assert tags == []
    assert mock_db.execute.called


@pytest.mark.asyncio
async def test_get_all_tags_with_tools(tag_service, mock_db):
    """Test getting tags from tools only."""
    # Mock database query for tools
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([
        (["api", "data"],),
        (["api", "auth"],),
        (["data"],),
    ])
    mock_db.execute.return_value = mock_result

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools"])

    assert len(tags) == 3
    tag_names = [tag.name for tag in tags]
    assert "api" in tag_names
    assert "data" in tag_names
    assert "auth" in tag_names

    # Check statistics
    api_tag = next(tag for tag in tags if tag.name == "api")
    assert api_tag.stats.tools == 2
    assert api_tag.stats.resources == 0
    assert api_tag.stats.total == 2


@pytest.mark.asyncio
async def test_get_all_tags_with_entities(tag_service, mock_db):
    """Test getting tags with entity details included."""
    # Create mock entities
    mock_tool1 = MagicMock()
    mock_tool1.id = "tool1"
    mock_tool1.original_name = "Test Tool 1"
    mock_tool1.name = None
    mock_tool1.description = "A test tool"
    mock_tool1.tags = ["api", "data"]

    mock_tool2 = MagicMock()
    mock_tool2.id = "tool2"
    mock_tool2.original_name = "Test Tool 2"
    mock_tool2.name = None
    mock_tool2.description = "Another test tool"
    mock_tool2.tags = ["api"]

    # Mock database query
    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool1, mock_tool2]
    mock_db.execute.return_value = mock_result

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools"], include_entities=True)

    assert len(tags) == 2  # api, data

    # Check api tag has entities
    api_tag = next(tag for tag in tags if tag.name == "api")
    assert len(api_tag.entities) == 2
    assert api_tag.entities[0].name == "Test Tool 1"
    assert api_tag.entities[0].type == "tool"
    assert api_tag.entities[1].name == "Test Tool 2"

    # Check data tag has one entity
    data_tag = next(tag for tag in tags if tag.name == "data")
    assert len(data_tag.entities) == 1
    assert data_tag.entities[0].name == "Test Tool 1"


@pytest.mark.asyncio
async def test_get_all_tags_multiple_entity_types(tag_service, mock_db):
    """Test getting tags from multiple entity types."""
    # Mock database queries for different entity types
    call_count = 0
    results = [
        # Tools results
        MagicMock(__iter__=lambda self: iter([
            (["api", "tool"],),
            (["api"],),
        ])),
        # Resources results
        MagicMock(__iter__=lambda self: iter([
            (["api", "resource"],),
            (["data"],),
        ])),
        # Prompts results
        MagicMock(__iter__=lambda self: iter([
            (["prompt", "api"],),
        ])),
    ]

    def side_effect(*args):
        nonlocal call_count
        result = results[call_count] if call_count < len(results) else MagicMock(__iter__=lambda self: iter([]))
        call_count += 1
        return result

    mock_db.execute.side_effect = side_effect

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools", "resources", "prompts"])

    assert len(tags) == 5  # api, tool, resource, data, prompt

    # Check api tag has counts from multiple entity types
    api_tag = next(tag for tag in tags if tag.name == "api")
    assert api_tag.stats.tools == 2
    assert api_tag.stats.resources == 1
    assert api_tag.stats.prompts == 1
    assert api_tag.stats.total == 4


@pytest.mark.asyncio
async def test_get_all_tags_with_empty_tags(tag_service, mock_db):
    """Test handling entities with empty tag arrays."""
    # Mock database query with some empty tag arrays
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([
        (["api"],),
        ([],),  # Empty tags array
        (None,),  # Null tags
        (["data"],),
    ])
    mock_db.execute.return_value = mock_result

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools"])

    assert len(tags) == 2
    tag_names = [tag.name for tag in tags]
    assert "api" in tag_names
    assert "data" in tag_names


@pytest.mark.asyncio
async def test_get_all_tags_invalid_entity_type(tag_service, mock_db):
    """Test handling invalid entity types."""
    # Invalid entity types should be ignored
    mock_db.execute.return_value.__iter__ = lambda self: iter([])

    tags = await tag_service.get_all_tags(mock_db, entity_types=["invalid_type"])

    assert tags == []
    # Should not execute any queries for invalid entity types
    assert not mock_db.execute.called


@pytest.mark.asyncio
async def test_get_all_tags_sorted(tag_service, mock_db):
    """Test that tags are returned in sorted order."""
    # Mock database query
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([
        (["zebra", "beta", "alpha"],),
        (["gamma", "alpha"],),
    ])
    mock_db.execute.return_value = mock_result

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools"])

    tag_names = [tag.name for tag in tags]
    assert tag_names == sorted(tag_names)  # Should be alphabetically sorted
    assert tag_names == ["alpha", "beta", "gamma", "zebra"]


@pytest.mark.asyncio
async def test_get_entities_by_tag(tag_service, mock_db):
    """Test getting entities by a specific tag."""
    # Create mock entities
    mock_tool = MagicMock()
    mock_tool.id = "tool1"
    mock_tool.original_name = "Test Tool"
    mock_tool.name = None
    mock_tool.description = "A test tool"
    mock_tool.tags = ["api", "test"]

    mock_resource = MagicMock()
    mock_resource.id = None
    mock_resource.uri = "resource://test"
    mock_resource.name = "Test Resource"
    mock_resource.description = None
    mock_resource.tags = ["api", "data"]

    # Mock database queries for different entity types
    call_count = 0

    # Create mock results with proper scalars method
    mock_result1 = MagicMock()
    mock_result1.scalars.return_value = [mock_tool]

    mock_result2 = MagicMock()
    mock_result2.scalars.return_value = [mock_resource]

    mock_empty = MagicMock()
    mock_empty.scalars.return_value = []

    results = [mock_result1, mock_result2]

    def side_effect(*args):
        nonlocal call_count
        result = results[call_count] if call_count < len(results) else mock_empty
        call_count += 1
        return result

    mock_db.execute.side_effect = side_effect

    entities = await tag_service.get_entities_by_tag(mock_db, "api", entity_types=["tools", "resources"])

    assert len(entities) == 2

    # Check tool entity
    tool_entity = next(e for e in entities if e.type == "tool")
    assert tool_entity.id == "tool1"
    assert tool_entity.name == "Test Tool"
    assert tool_entity.description == "A test tool"

    # Check resource entity
    resource_entity = next(e for e in entities if e.type == "resource")
    assert resource_entity.id == "resource://test"
    assert resource_entity.name == "Test Resource"
    assert resource_entity.description is None
