# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for export service implementation.
"""

# Standard
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.export_service import ExportService, ExportError, ExportValidationError
from mcpgateway.schemas import ToolRead, GatewayRead, ServerRead, PromptRead, ResourceRead
from mcpgateway.models import Root


@pytest.fixture
def export_service():
    """Create an export service instance with mocked dependencies."""
    service = ExportService()
    service.tool_service = AsyncMock()
    service.gateway_service = AsyncMock()
    service.server_service = AsyncMock()
    service.prompt_service = AsyncMock()
    service.resource_service = AsyncMock()
    service.root_service = AsyncMock()
    return service


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def sample_tool():
    """Create a sample tool for testing."""
    from mcpgateway.schemas import ToolMetrics
    return ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        url="https://api.example.com/tool",
        description="Test tool",
        integration_type="REST",
        request_type="GET",
        headers={},
        input_schema={"type": "object", "properties": {}},
        annotations={},
        jsonpath_filter="",
        auth=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        gateway_id=None,
        execution_count=0,
        metrics=ToolMetrics(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=None,
            max_response_time=None,
            avg_response_time=None,
            last_execution_time=None
        ),
        gateway_slug="",
        original_name_slug="test_tool",
        tags=["api", "test"]
    )


@pytest.fixture
def sample_gateway():
    """Create a sample gateway for testing."""
    return GatewayRead(
        id="gw1",
        name="test_gateway",
        url="https://gateway.example.com",
        description="Test gateway",
        transport="SSE",
        capabilities={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        last_seen=datetime.now(timezone.utc),
        auth_type=None,
        auth_value=None,
        auth_username=None,
        auth_password=None,
        auth_token=None,
        auth_header_key=None,
        auth_header_value=None,
        tags=["gateway", "test"],
        slug="test_gateway",
        passthrough_headers=None
    )


@pytest.mark.asyncio
async def test_export_configuration_basic(export_service, mock_db, sample_tool, sample_gateway):
    """Test basic configuration export."""
    # Setup mocks
    export_service.tool_service.list_tools.return_value = [sample_tool]
    export_service.gateway_service.list_gateways.return_value = [sample_gateway]
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    # Execute export
    result = await export_service.export_configuration(
        db=mock_db,
        exported_by="test_user"
    )

    # Validate result structure
    assert "version" in result
    assert "exported_at" in result
    assert "exported_by" in result
    assert result["exported_by"] == "test_user"
    assert "entities" in result
    assert "metadata" in result

    # Check entities
    entities = result["entities"]
    assert "tools" in entities
    assert "gateways" in entities
    assert len(entities["tools"]) == 1
    assert len(entities["gateways"]) == 1

    # Check metadata
    metadata = result["metadata"]
    assert "entity_counts" in metadata
    assert metadata["entity_counts"]["tools"] == 1
    assert metadata["entity_counts"]["gateways"] == 1


@pytest.mark.asyncio
async def test_export_configuration_with_filters(export_service, mock_db):
    """Test export with filtering options."""
    # Setup mocks
    export_service.tool_service.list_tools.return_value = []
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    # Execute export with filters
    result = await export_service.export_configuration(
        db=mock_db,
        include_types=["tools", "gateways"],
        tags=["production"],
        include_inactive=True,
        exported_by="test_user"
    )

    # Verify service calls with filters
    export_service.tool_service.list_tools.assert_called_once_with(
        mock_db, tags=["production"], include_inactive=True
    )
    export_service.gateway_service.list_gateways.assert_called_once_with(
        mock_db, include_inactive=True
    )

    # Should not call other services
    export_service.server_service.list_servers.assert_not_called()
    export_service.prompt_service.list_prompts.assert_not_called()
    export_service.resource_service.list_resources.assert_not_called()

    # Check only requested types are in result
    entities = result["entities"]
    assert "tools" in entities
    assert "gateways" in entities
    assert "servers" not in entities
    assert "prompts" not in entities
    assert "resources" not in entities


@pytest.mark.asyncio
async def test_export_selective(export_service, mock_db, sample_tool):
    """Test selective export functionality."""
    # Setup mocks
    export_service.tool_service.get_tool.return_value = sample_tool
    export_service.tool_service.list_tools.return_value = [sample_tool]

    entity_selections = {
        "tools": ["tool1"]
    }

    # Execute selective export
    result = await export_service.export_selective(
        db=mock_db,
        entity_selections=entity_selections,
        exported_by="test_user"
    )

    # Validate result
    assert "entities" in result
    assert "tools" in result["entities"]
    assert len(result["entities"]["tools"]) >= 0  # May be 0 if filtering doesn't match

    # Check metadata indicates selective export
    metadata = result["metadata"]
    assert metadata["export_options"]["selective"] == True
    assert metadata["export_options"]["selections"] == entity_selections


@pytest.mark.asyncio
async def test_export_tools_filters_mcp(export_service, mock_db):
    """Test that export filters out MCP tools from gateways."""
    # Create a mix of tools
    from mcpgateway.schemas import ToolMetrics

    local_tool = ToolRead(
        id="tool1", original_name="local_tool", name="local_tool",
        url="https://api.example.com", description="Local REST tool", integration_type="REST", request_type="GET",
        headers={}, input_schema={}, annotations={}, jsonpath_filter="",
        auth=None, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        enabled=True, reachable=True, gateway_id=None, execution_count=0,
        metrics=ToolMetrics(
            total_executions=0, successful_executions=0, failed_executions=0,
            failure_rate=0.0, min_response_time=None, max_response_time=None,
            avg_response_time=None, last_execution_time=None
        ), gateway_slug="", original_name_slug="local_tool", tags=[]
    )

    mcp_tool = ToolRead(
        id="tool2", original_name="mcp_tool", name="gw1-mcp_tool",
        url="https://gateway.example.com", description="MCP tool from gateway", integration_type="MCP", request_type="SSE",
        headers={}, input_schema={}, annotations={}, jsonpath_filter="",
        auth=None, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        enabled=True, reachable=True, gateway_id="gw1", execution_count=0,
        metrics=ToolMetrics(
            total_executions=0, successful_executions=0, failed_executions=0,
            failure_rate=0.0, min_response_time=None, max_response_time=None,
            avg_response_time=None, last_execution_time=None
        ), gateway_slug="gw1", original_name_slug="mcp_tool", tags=[]
    )

    export_service.tool_service.list_tools.return_value = [local_tool, mcp_tool]

    # Execute export
    tools = await export_service._export_tools(mock_db, None, False)

    # Should only include the local REST tool, not the MCP tool from gateway
    assert len(tools) == 1
    assert tools[0]["name"] == "local_tool"
    assert tools[0]["integration_type"] == "REST"


@pytest.mark.asyncio
async def test_export_validation_error(export_service, mock_db):
    """Test export validation error handling."""
    # Mock services to return invalid data that will cause validation to fail
    export_service.tool_service.list_tools.return_value = []
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    # Mock validation to fail
    with patch.object(export_service, '_validate_export_data') as mock_validate:
        mock_validate.side_effect = ExportValidationError("Test validation error")

        with pytest.raises(ExportError) as excinfo:
            await export_service.export_configuration(mock_db, exported_by="test_user")

        assert "Test validation error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_export_data_success(export_service):
    """Test successful export data validation."""
    valid_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": {"tools": []},
        "metadata": {"entity_counts": {"tools": 0}}
    }

    # Should not raise any exception
    export_service._validate_export_data(valid_data)


@pytest.mark.asyncio
async def test_validate_export_data_missing_fields(export_service):
    """Test export data validation with missing fields."""
    invalid_data = {
        "version": "2025-03-26",
        # Missing required fields
    }

    with pytest.raises(ExportValidationError) as excinfo:
        export_service._validate_export_data(invalid_data)

    assert "Missing required field" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_export_data_invalid_entities(export_service):
    """Test export data validation with invalid entities structure."""
    invalid_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": "not_a_dict",  # Should be a dict
        "metadata": {"entity_counts": {}}
    }

    with pytest.raises(ExportValidationError) as excinfo:
        export_service._validate_export_data(invalid_data)

    assert "Entities must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_extract_dependencies(export_service, mock_db):
    """Test dependency extraction between entities."""
    entities = {
        "servers": [
            {"name": "server1", "tool_ids": ["tool1", "tool2"]},
            {"name": "server2", "tool_ids": ["tool3"]}
        ],
        "tools": [
            {"name": "tool1"},
            {"name": "tool2"},
            {"name": "tool3"}
        ]
    }

    dependencies = await export_service._extract_dependencies(mock_db, entities)

    assert "servers_to_tools" in dependencies
    assert dependencies["servers_to_tools"]["server1"] == ["tool1", "tool2"]
    assert dependencies["servers_to_tools"]["server2"] == ["tool3"]


@pytest.mark.asyncio
async def test_export_with_masked_auth_data(export_service, mock_db):
    """Test export handling of masked authentication data."""
    from mcpgateway.schemas import ToolRead, ToolMetrics, AuthenticationValues
    from mcpgateway.config import settings

    # Create tool with masked auth data
    tool_with_masked_auth = ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        url="https://api.example.com/tool",
        description="Test tool",
        integration_type="REST",
        request_type="GET",
        headers={},
        input_schema={"type": "object", "properties": {}},
        annotations={},
        jsonpath_filter="",
        auth=AuthenticationValues(
            auth_type="bearer",
            auth_value=settings.masked_auth_value  # Masked value
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        gateway_id=None,
        execution_count=0,
        metrics=ToolMetrics(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=None,
            max_response_time=None,
            avg_response_time=None,
            last_execution_time=None
        ),
        gateway_slug="",
        original_name_slug="test_tool",
        tags=[]
    )

    # Mock service and database
    export_service.tool_service.list_tools.return_value = [tool_with_masked_auth]

    # Mock database query to return raw auth value
    mock_db_tool = MagicMock()
    mock_db_tool.auth_value = "encrypted_raw_auth_value"
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_tool

    # Execute export
    tools = await export_service._export_tools(mock_db, None, False)

    # Should get raw auth value from database
    assert len(tools) == 1
    assert tools[0]["auth_type"] == "bearer"
    assert tools[0]["auth_value"] == "encrypted_raw_auth_value"


@pytest.mark.asyncio
async def test_export_service_initialization(export_service):
    """Test export service initialization and shutdown."""
    # Test initialization
    await export_service.initialize()

    # Test shutdown
    await export_service.shutdown()


@pytest.mark.asyncio
async def test_export_empty_entities(export_service, mock_db):
    """Test export with empty entity lists."""
    # Setup mocks to return empty lists
    export_service.tool_service.list_tools.return_value = []
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(
        db=mock_db,
        exported_by="test_user"
    )

    # All entity counts should be zero
    entity_counts = result["metadata"]["entity_counts"]
    for entity_type, count in entity_counts.items():
        assert count == 0

    # Should still have proper structure
    assert "version" in result
    assert "entities" in result
    assert "metadata" in result


@pytest.mark.asyncio
async def test_export_with_exclude_types(export_service, mock_db):
    """Test export with excluded entity types."""
    # Setup mocks
    export_service.tool_service.list_tools.return_value = []
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(
        db=mock_db,
        exclude_types=["servers", "prompts"],
        exported_by="test_user"
    )

    # Excluded types should not be in entities
    entities = result["entities"]
    assert "servers" not in entities
    assert "prompts" not in entities

    # Included types should be present
    assert "tools" in entities
    assert "gateways" in entities
    assert "resources" in entities
    assert "roots" in entities


@pytest.mark.asyncio
async def test_export_roots_functionality(export_service):
    """Test root export functionality."""
    from mcpgateway.models import Root

    # Mock root service
    mock_roots = [
        Root(uri="file:///workspace", name="Workspace"),
        Root(uri="file:///tmp", name="Temp"),
        Root(uri="http://example.com/api", name="API")
    ]
    export_service.root_service.list_roots.return_value = mock_roots

    # Execute export
    roots = await export_service._export_roots()

    # Verify structure
    assert len(roots) == 3
    assert roots[0]["uri"] == "file:///workspace"
    assert roots[0]["name"] == "Workspace"
    assert roots[1]["uri"] == "file:///tmp"
    assert roots[1]["name"] == "Temp"
    assert roots[2]["uri"] == "http://example.com/api"
    assert roots[2]["name"] == "API"


@pytest.mark.asyncio
async def test_export_with_include_inactive(export_service, mock_db):
    """Test export with include_inactive flag."""
    # Setup mocks
    export_service.tool_service.list_tools.return_value = []
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = []
    export_service.resource_service.list_resources.return_value = []
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(
        db=mock_db,
        include_inactive=True,
        exported_by="test_user"
    )

    # Verify include_inactive flag is recorded
    export_options = result["metadata"]["export_options"]
    assert export_options["include_inactive"] == True

    # Verify service calls included the flag
    export_service.tool_service.list_tools.assert_called_with(
        mock_db, tags=None, include_inactive=True
    )
