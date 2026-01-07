# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tag_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Tag Service.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.tag_service import TagService


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear admin stats cache before each test to prevent cross-test contamination."""
    # First-Party
    from mcpgateway.cache.admin_stats_cache import admin_stats_cache

    admin_stats_cache.invalidate_all()
    yield
    admin_stats_cache.invalidate_all()


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
    mock_result.__iter__ = lambda self: iter(
        [
            (["api", "data"],),
            (["api", "auth"],),
            (["data"],),
        ]
    )
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
        MagicMock(
            __iter__=lambda self: iter(
                [
                    (["api", "tool"],),
                    (["api"],),
                ]
            )
        ),
        # Resources results
        MagicMock(
            __iter__=lambda self: iter(
                [
                    (["api", "resource"],),
                    (["data"],),
                ]
            )
        ),
        # Prompts results
        MagicMock(
            __iter__=lambda self: iter(
                [
                    (["prompt", "api"],),
                ]
            )
        ),
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
    mock_result.__iter__ = lambda self: iter(
        [
            (["api"],),
            ([],),  # Empty tags array
            (None,),  # Null tags
            (["data"],),
        ]
    )
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
    mock_result.__iter__ = lambda self: iter(
        [
            (["zebra", "beta", "alpha"],),
            (["gamma", "alpha"],),
        ]
    )
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


@pytest.mark.asyncio
async def test_get_entities_by_tag_no_entity_types(tag_service, mock_db):
    """Test getting entities by tag with no entity type filter."""
    mock_tool = MagicMock()
    mock_tool.id = "tool1"
    mock_tool.name = "Test Tool"
    mock_tool.description = "A test tool"
    mock_tool.tags = ["api"]

    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool]
    mock_db.execute.return_value = mock_result

    # Test with no entity_types specified (should use all types)
    entities = await tag_service.get_entities_by_tag(mock_db, "api")

    assert len(entities) >= 1
    # Should have been called for all entity types
    assert mock_db.execute.call_count == 5  # tools, resources, prompts, servers, gateways


@pytest.mark.asyncio
async def test_get_entities_by_tag_invalid_entity_type(tag_service, mock_db):
    """Test getting entities by tag with invalid entity types."""
    mock_db.execute.return_value.scalars.return_value = []

    entities = await tag_service.get_entities_by_tag(mock_db, "api", ["invalid_type"])

    assert entities == []
    # Should not execute any queries for invalid types
    assert not mock_db.execute.called


@pytest.mark.asyncio
async def test_get_entities_by_tag_empty_tags(tag_service, mock_db):
    """Test entity lookup when entity has empty tags."""
    mock_tool = MagicMock()
    mock_tool.id = "tool1"
    mock_tool.name = "Test Tool"
    mock_tool.description = "A test tool"
    mock_tool.tags = []  # Empty tags

    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool]
    mock_db.execute.return_value = mock_result

    entities = await tag_service.get_entities_by_tag(mock_db, "api", ["tools"])

    # Entity has empty tags, so shouldn't match
    assert entities == []


@pytest.mark.asyncio
async def test_get_entities_by_tag_null_tags(tag_service, mock_db):
    """Test entity lookup when entity has None tags."""
    mock_tool = MagicMock()
    mock_tool.id = "tool1"
    mock_tool.name = "Test Tool"
    mock_tool.description = "A test tool"
    mock_tool.tags = None  # Null tags

    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool]
    mock_db.execute.return_value = mock_result

    entities = await tag_service.get_entities_by_tag(mock_db, "api", ["tools"])

    # Entity has null tags, so shouldn't match
    assert entities == []


@pytest.mark.asyncio
async def test_get_entities_by_tag_name_fallback_simplified(tag_service, mock_db):
    """Test entity name resolution fallback logic."""
    # Test entity with original_name but no name
    mock_tool = MagicMock()
    mock_tool.id = "tool1"
    mock_tool.name = None
    mock_tool.original_name = "Original Tool Name"
    mock_tool.description = "A test tool"
    mock_tool.tags = ["api"]

    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool]
    mock_db.execute.return_value = mock_result

    entities = await tag_service.get_entities_by_tag(mock_db, "api", ["tools"])

    assert len(entities) == 1

    # Check tool with original_name fallback
    tool_entity = entities[0]
    assert tool_entity.name == "Original Tool Name"
    assert tool_entity.id == "tool1"


@pytest.mark.asyncio
async def test_get_tag_counts(tag_service, mock_db):
    """Test getting tag counts per entity type."""
    # Mock database responses for each entity type
    call_count = 0
    tag_counts = [
        [2, 1, 3],  # tools: 3 entities with 2, 1, 3 tags = 6 total
        [1, 2],  # resources: 2 entities with 1, 2 tags = 3 total
        [4],  # prompts: 1 entity with 4 tags = 4 total
        [],  # servers: no entities = 0 total
        [1, 1, 1],  # gateways: 3 entities with 1 tag each = 3 total
    ]

    def side_effect(*args):
        nonlocal call_count
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tag_counts[call_count] if call_count < len(tag_counts) else []
        call_count += 1
        return mock_result

    mock_db.execute.side_effect = side_effect

    counts = await tag_service.get_tag_counts(mock_db)

    assert counts["tools"] == 6
    assert counts["resources"] == 3
    assert counts["prompts"] == 4
    assert counts["servers"] == 0
    assert counts["gateways"] == 3
    assert len(counts) == 5


@pytest.mark.asyncio
async def test_update_stats(tag_service):
    """Test the _update_stats helper method."""
    # First-Party
    from mcpgateway.schemas import TagStats

    stats = TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0)

    # Test updating each entity type
    tag_service._update_stats(stats, "tools")
    assert stats.tools == 1
    assert stats.total == 1

    tag_service._update_stats(stats, "resources")
    assert stats.resources == 1
    assert stats.total == 2

    tag_service._update_stats(stats, "prompts")
    assert stats.prompts == 1
    assert stats.total == 3

    tag_service._update_stats(stats, "servers")
    assert stats.servers == 1
    assert stats.total == 4

    tag_service._update_stats(stats, "gateways")
    assert stats.gateways == 1
    assert stats.total == 5

    # Test invalid entity type (should not crash or increment)
    tag_service._update_stats(stats, "invalid")
    assert stats.total == 5  # Should remain unmodified


@pytest.mark.asyncio
async def test_get_all_tags_with_entities_name_fallback_simplified(tag_service, mock_db):
    """Test entity name resolution in get_all_tags with include_entities=True."""
    # Test entity with primary name
    mock_tool1 = MagicMock()
    mock_tool1.id = "tool1"
    mock_tool1.name = "Primary Name"  # Should use this
    mock_tool1.original_name = "Original Name"
    mock_tool1.description = "Tool 1"
    mock_tool1.tags = ["api"]

    # Test entity with original name fallback
    mock_tool2 = MagicMock()
    mock_tool2.id = "tool2"
    mock_tool2.name = None
    mock_tool2.original_name = "Original Name 2"  # Should use this
    mock_tool2.description = "Tool 2"
    mock_tool2.tags = ["api"]

    mock_result = MagicMock()
    mock_result.scalars.return_value = [mock_tool1, mock_tool2]
    mock_db.execute.return_value = mock_result

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools"], include_entities=True)

    assert len(tags) == 1  # Only "api" tag
    api_tag = tags[0]
    assert len(api_tag.entities) == 2

    # Check name resolution
    entity_names = [e.name for e in api_tag.entities]
    assert "Primary Name" in entity_names
    assert "Original Name 2" in entity_names


@pytest.mark.asyncio
async def test_get_all_tags_with_entities_id_fallback(tag_service, mock_db):
    """Test entity ID resolution in get_all_tags with include_entities=True."""
    mock_resource = MagicMock()
    mock_resource.id = None  # No ID
    mock_resource.uri = "resource://fallback"  # Should use this for resources
    mock_resource.name = "Resource Name"
    mock_resource.description = "Resource"
    mock_resource.tags = ["test"]

    mock_server = MagicMock()
    mock_server.id = None  # No ID
    mock_server.name = "Server Name"  # Should use this as fallback
    mock_server.description = "Server"
    mock_server.tags = ["test"]

    call_count = 0

    def create_mock_result(entities):
        mock_result = MagicMock()
        mock_result.scalars.return_value = entities
        return mock_result

    results = [
        create_mock_result([]),  # tools - empty
        create_mock_result([mock_resource]),  # resources
        create_mock_result([]),  # prompts - empty
        create_mock_result([mock_server]),  # servers
    ]

    def side_effect(*args):
        nonlocal call_count
        result = results[call_count] if call_count < len(results) else create_mock_result([])
        call_count += 1
        return result

    mock_db.execute.side_effect = side_effect

    tags = await tag_service.get_all_tags(mock_db, entity_types=["tools", "resources", "prompts", "servers"], include_entities=True)

    assert len(tags) == 1  # Only "test" tag
    test_tag = tags[0]
    assert len(test_tag.entities) == 2

    # Check ID resolution
    entity_ids = [e.id for e in test_tag.entities]
    assert "resource://fallback" in entity_ids  # Resource used URI
    assert "Server Name" in entity_ids  # Server used name as fallback


@pytest.mark.asyncio
async def test_get_all_tags_default_entity_types(tag_service, mock_db):
    """Test that get_all_tags uses all entity types by default."""
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([])
    mock_db.execute.return_value = mock_result

    # Call without entity_types
    await tag_service.get_all_tags(mock_db)

    # Should have been called for all 5 entity types
    assert mock_db.execute.call_count == 5


@pytest.mark.asyncio
async def test_get_entities_by_tag_default_entity_types(tag_service, mock_db):
    """Test that get_entities_by_tag uses all entity types by default."""
    mock_result = MagicMock()
    mock_result.scalars.return_value = []
    mock_db.execute.return_value = mock_result

    # Call without entity_types
    await tag_service.get_entities_by_tag(mock_db, "test")

    # Should have been called for all 5 entity types
    assert mock_db.execute.call_count == 5
