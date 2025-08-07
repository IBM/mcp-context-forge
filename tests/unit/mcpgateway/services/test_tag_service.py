# -*- coding: utf-8 -*-
"""Tests for Tag Service."""

import pytest
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from mcpgateway.services.tag_service import TagService
from mcpgateway.schemas import TagInfo, TagStats


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