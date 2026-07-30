# -*- coding: utf-8 -*-
"""Integration test for gateway tool restoration cache invalidation.

Tests the auto-refresh path (lines 5422-5425) which requires real database
session behavior for db.dirty tracking.
"""

# Standard
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, Gateway, Tool
from mcpgateway.services.gateway_service import GatewayService


@pytest.fixture
def test_db_session():
    """Create a test database session with proper schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create schema
    Base.metadata.create_all(bind=engine)

    session = TestSessionLocal()
    yield session

    session.close()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_refresh_invalidates_cache_for_restored_tools(test_db_session):
    """Integration test: auto-refresh invalidates cache for restored tools.

    Covers lines 5422-5425 in gateway_service.py.
    Uses real database session to ensure db.dirty tracking works properly.
    """
    service = GatewayService()

    # Create gateway using the test_db_session
    gateway = Gateway(
        id="test-gw-cache-001",
        name="Test Gateway Cache",
        url="http://example.com",
        transport="SSE",
        enabled=True,
        reachable=True,
        visibility="public",
        capabilities={}
    )
    test_db_session.add(gateway)
    test_db_session.flush()

    # Add unreachable tool
    tool = Tool(
        id="test-tool-cache-001",
        original_name="test-tool-cache",
        name="test-tool-cache",
        description="Test tool for cache",
        original_description="Test tool for cache",
        input_schema={},  # Required field
        gateway_id=gateway.id,
        reachable=False,  # Tool is unreachable
        enabled=True,
        created_via="health_check",
        integration_type="MCP",
        jsonpath_filter=""  # Required field with default empty string
    )
    test_db_session.add(tool)
    test_db_session.commit()

    # Verify tool is unreachable
    assert tool.reachable is False

    # Now run the refresh with mocked _initialize_gateway
    mock_tool_schema = MagicMock()
    mock_tool_schema.name = "test-tool-cache"
    mock_tool_schema.description = "Test tool for cache"
    mock_tool_schema.input_schema = {}
    mock_tool_schema.output_schema = None
    mock_tool_schema.request_type = "POST"
    mock_tool_schema.headers = {}
    mock_tool_schema.annotations = None
    mock_tool_schema.jsonpath_filter = ""  # Empty string instead of None
    mock_tool_schema.title = None

    mock_registry_cache = AsyncMock()
    mock_tool_lookup_cache = AsyncMock()

    # Mock fresh_db_session to return our test session
    mock_fresh_session = MagicMock()
    mock_fresh_session.__enter__ = MagicMock(return_value=test_db_session)
    mock_fresh_session.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        patch("mcpgateway.services.gateway_service._get_registry_cache", return_value=mock_registry_cache),
        patch("mcpgateway.services.gateway_service._get_tool_lookup_cache", return_value=mock_tool_lookup_cache),
        patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_fresh_session),
    ):
        # Server reports tool is available
        mock_init.return_value = ({}, [mock_tool_schema], [], [], [])

        # Run auto-refresh
        result = await service._refresh_gateway_tools_resources_prompts("test-gw-cache-001")

        # Verify tool was updated (reachable status changed)
        assert result["tools_updated"] > 0, "Tool should have been updated (reachable changed from False to True)"

        # Verify cache was invalidated for the restored tool
        # This is the critical assertion for lines 5423-5424
        mock_tool_lookup_cache.invalidate.assert_called_with("test-tool-cache", gateway_id="test-gw-cache-001")

    # Verify tool is now reachable in database
    test_db_session.refresh(tool)
    assert tool.reachable is True, "Tool should now be marked as reachable"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_refresh_invalidates_cache_for_multiple_restored_tools(test_db_session):
    """Integration test: auto-refresh invalidates cache for multiple restored tools.

    Ensures lines 5423-5425 are fully covered by testing the loop with multiple tools.
    """
    service = GatewayService()

    # Create gateway using the test_db_session
    gateway = Gateway(
        id="test-gw-cache-multi-001",
        name="Test Gateway Cache Multi",
        url="http://example.com",
        transport="SSE",
        enabled=True,
        reachable=True,
        visibility="public",
        capabilities={}
    )
    test_db_session.add(gateway)
    test_db_session.flush()

    # Add multiple unreachable tools
    tools = []
    for i in range(3):
        tool = Tool(
            id=f"test-tool-cache-multi-{i:03d}",
            original_name=f"test-tool-cache-{i}",
            name=f"test-tool-cache-{i}",
            description=f"Test tool for cache {i}",
            original_description=f"Test tool for cache {i}",
            input_schema={},
            gateway_id=gateway.id,
            reachable=False,  # Tool is unreachable
            enabled=True,
            created_via="health_check",
            integration_type="MCP",
            jsonpath_filter=""  # Required field with default empty string
        )
        test_db_session.add(tool)
        tools.append(tool)
    test_db_session.commit()

    # Verify tools are unreachable
    for tool in tools:
        assert tool.reachable is False

    # Create mock tool schemas for all tools
    mock_tool_schemas = []
    for i in range(3):
        mock_tool_schema = MagicMock()
        mock_tool_schema.name = f"test-tool-cache-{i}"
        mock_tool_schema.description = f"Test tool for cache {i}"
        mock_tool_schema.input_schema = {}
        mock_tool_schema.output_schema = None
        mock_tool_schema.request_type = "POST"
        mock_tool_schema.headers = {}
        mock_tool_schema.annotations = None
        mock_tool_schema.jsonpath_filter = ""  # Empty string instead of None
        mock_tool_schema.title = None
        mock_tool_schemas.append(mock_tool_schema)

    mock_registry_cache = AsyncMock()
    mock_tool_lookup_cache = AsyncMock()

    # Mock fresh_db_session to return our test session
    mock_fresh_session = MagicMock()
    mock_fresh_session.__enter__ = MagicMock(return_value=test_db_session)
    mock_fresh_session.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        patch("mcpgateway.services.gateway_service._get_registry_cache", return_value=mock_registry_cache),
        patch("mcpgateway.services.gateway_service._get_tool_lookup_cache", return_value=mock_tool_lookup_cache),
        patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=mock_fresh_session),
    ):
        # Server reports all tools are now available
        mock_init.return_value = ({}, mock_tool_schemas, [], [], [])

        # Run auto-refresh
        result = await service._refresh_gateway_tools_resources_prompts("test-gw-cache-multi-001")

        # Verify tools were updated
        assert result["tools_updated"] >= 3, f"At least 3 tools should have been updated, got {result['tools_updated']}"

        # Verify cache was invalidated for all restored tools (line 5423-5424)
        # This ensures the loop body is fully executed
        assert mock_tool_lookup_cache.invalidate.call_count == 3, "Cache should be invalidated for each restored tool"

        # Check each tool was invalidated
        for i in range(3):
            mock_tool_lookup_cache.invalidate.assert_any_call(f"test-tool-cache-{i}", gateway_id="test-gw-cache-multi-001")

    # Verify all tools are now reachable in database
    for tool in tools:
        test_db_session.refresh(tool)
        assert tool.reachable is True, f"Tool {tool.name} should now be marked as reachable"
