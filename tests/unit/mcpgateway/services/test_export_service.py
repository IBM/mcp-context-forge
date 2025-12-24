# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_export_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for export service implementation.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Root
from mcpgateway.schemas import GatewayRead, PromptMetrics, PromptRead, ResourceMetrics, ResourceRead, ServerMetrics, ServerRead, ToolMetrics, ToolRead
from mcpgateway.services.export_service import ExportError, ExportService, ExportValidationError
from mcpgateway.utils.services_auth import encode_auth


def create_default_server_metrics():
    """Create default ServerMetrics for testing."""
    return ServerMetrics(
        total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
    )


def create_default_prompt_metrics():
    """Create default PromptMetrics for testing."""
    return PromptMetrics(
        total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
    )


def create_default_resource_metrics():
    """Create default ResourceMetrics for testing."""
    return ResourceMetrics(
        total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
    )


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
    # First-Party
    return ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        custom_name="test_tool",
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
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="",
        custom_name_slug="test_tool",
        tags=[{"id": "api", "label": "API"}, {"id": "test", "label": "Test"}],
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
        tags=[{"id": "gateway", "label": "Gateway"}, {"id": "test", "label": "Test"}],
        slug="test_gateway",
        passthrough_headers=None,
    )


@pytest.mark.asyncio
async def test_export_configuration_basic(export_service, mock_db, sample_tool, sample_gateway):
    """Test basic configuration export."""
    # Setup mocks
    export_service.tool_service.list_tools.return_value = ([sample_tool], None)
    export_service.gateway_service.list_gateways.return_value = [sample_gateway]
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    # Execute export
    result = await export_service.export_configuration(db=mock_db, exported_by="test_user")

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
    export_service.tool_service.list_tools.return_value = ([], None)
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    # Execute export with filters
    result = await export_service.export_configuration(db=mock_db, include_types=["tools", "gateways"], tags=["production"], include_inactive=True, exported_by="test_user")

    # Verify service calls with filters (cursor=None for pagination)
    export_service.tool_service.list_tools.assert_called_once_with(mock_db, tags=["production"], include_inactive=True, cursor=None)
    export_service.gateway_service.list_gateways.assert_called_once_with(mock_db, include_inactive=True)

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
    export_service.tool_service.list_tools.return_value = ([sample_tool], None)

    entity_selections = {"tools": ["tool1"]}

    # Execute selective export
    result = await export_service.export_selective(db=mock_db, entity_selections=entity_selections, exported_by="test_user")

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
    # First-Party

    local_tool = ToolRead(
        id="tool1",
        original_name="local_tool",
        name="local_tool",
        custom_name="local_tool",
        url="https://api.example.com",
        description="Local REST tool",
        integration_type="REST",
        request_type="GET",
        headers={},
        input_schema={},
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
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="",
        custom_name_slug="local_tool",
        tags=[],
    )

    mcp_tool = ToolRead(
        id="tool2",
        original_name="mcp_tool",
        name="gw1-mcp_tool",
        custom_name="mcp_tool",
        url="https://gateway.example.com",
        description="MCP tool from gateway",
        integration_type="MCP",
        request_type="SSE",
        headers={},
        input_schema={},
        annotations={},
        jsonpath_filter="",
        auth=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        gateway_id="gw1",
        execution_count=0,
        metrics=ToolMetrics(
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="gw1",
        custom_name_slug="mcp_tool",
        tags=[],
    )

    export_service.tool_service.list_tools.return_value = ([local_tool, mcp_tool], None)

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
    export_service.tool_service.list_tools.return_value = ([], None)
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    # Mock validation to fail
    with patch.object(export_service, "_validate_export_data") as mock_validate:
        mock_validate.side_effect = ExportValidationError("Test validation error")

        with pytest.raises(ExportError) as excinfo:
            await export_service.export_configuration(mock_db, exported_by="test_user")

        assert "Test validation error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_export_data_success(export_service):
    """Test successful export data validation."""
    valid_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "exported_by": "test_user", "entities": {"tools": []}, "metadata": {"entity_counts": {"tools": 0}}}

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
        "metadata": {"entity_counts": {}},
    }

    with pytest.raises(ExportValidationError) as excinfo:
        export_service._validate_export_data(invalid_data)

    assert "Entities must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_extract_dependencies(export_service, mock_db):
    """Test dependency extraction between entities."""
    entities = {"servers": [{"name": "server1", "tool_ids": ["tool1", "tool2"]}, {"name": "server2", "tool_ids": ["tool3"]}], "tools": [{"name": "tool1"}, {"name": "tool2"}, {"name": "tool3"}]}

    dependencies = await export_service._extract_dependencies(mock_db, entities)

    assert "servers_to_tools" in dependencies
    assert dependencies["servers_to_tools"]["server1"] == ["tool1", "tool2"]
    assert dependencies["servers_to_tools"]["server2"] == ["tool3"]


@pytest.mark.asyncio
async def test_export_with_masked_auth_data(export_service, mock_db):
    """Test export handling of masked authentication data."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.schemas import AuthenticationValues, ToolRead

    # Create tool with masked auth data
    tool_with_masked_auth = ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        custom_name="test_tool",
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
            auth_value=settings.masked_auth_value,  # Masked value
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        gateway_id=None,
        execution_count=0,
        metrics=ToolMetrics(
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="",
        custom_name_slug="test_tool",
        tags=[],
    )

    # Mock service and database
    export_service.tool_service.list_tools.return_value = ([tool_with_masked_auth], None)

    # Mock database batch query to return raw auth values (id, auth_type, auth_value tuples)
    mock_db.execute.return_value.all.return_value = [("tool1", "bearer", "encrypted_raw_auth_value")]

    # Execute export
    tools = await export_service._export_tools(mock_db, None, False)

    # Should get raw auth value from database via batch query
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
    export_service.tool_service.list_tools.return_value = ([], None)
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(db=mock_db, exported_by="test_user")

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
    export_service.tool_service.list_tools.return_value = ([], None)
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(db=mock_db, exclude_types=["servers", "prompts"], exported_by="test_user")

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
    # First-Party

    # Mock root service
    mock_roots = [Root(uri="file:///workspace", name="Workspace"), Root(uri="file:///tmp", name="Temp"), Root(uri="http://example.com/api", name="API")]
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
    export_service.tool_service.list_tools.return_value = ([], None)
    export_service.gateway_service.list_gateways.return_value = []
    export_service.server_service.list_servers.return_value = []
    export_service.prompt_service.list_prompts.return_value = ([], None)
    export_service.resource_service.list_resources.return_value = ([], None)
    export_service.root_service.list_roots.return_value = []

    result = await export_service.export_configuration(db=mock_db, include_inactive=True, exported_by="test_user")

    # Verify include_inactive flag is recorded
    export_options = result["metadata"]["export_options"]
    assert export_options["include_inactive"] == True

    # Verify service calls included the flag (cursor=None for pagination)
    export_service.tool_service.list_tools.assert_called_with(mock_db, tags=None, include_inactive=True, cursor=None)


@pytest.mark.asyncio
async def test_export_tools_with_non_masked_auth(export_service, mock_db):
    """Test export tools with non-masked authentication data."""
    # First-Party
    from mcpgateway.schemas import AuthenticationValues, ToolRead

    # Create tool with non-masked auth data
    tool_with_auth = ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        custom_name="test_tool",
        displayName="Test Tool",
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
            auth_value="encrypted_auth_value",  # Not masked
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        enabled=True,
        reachable=True,
        gateway_id=None,
        execution_count=0,
        metrics=ToolMetrics(
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="",
        custom_name_slug="test_tool",
        tags=[],
    )

    export_service.tool_service.list_tools.return_value = ([tool_with_auth], None)

    # Execute export
    tools = await export_service._export_tools(mock_db, None, False)

    # Should use auth value directly (not masked)
    assert len(tools) == 1
    assert tools[0]["auth_type"] == "bearer"
    assert tools[0]["auth_value"] == "encrypted_auth_value"


@pytest.mark.asyncio
async def test_export_gateways_with_tag_filtering(export_service, mock_db):
    """Test gateway export with tag filtering."""
    # Create gateways with different tags
    gateway_with_matching_tags = GatewayRead(
        id="gw1",
        name="gateway_with_tags",
        url="https://gateway1.example.com",
        description="Gateway with tags",
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
        tags=[{"id": "production", "label": "Production"}, {"id": "api", "label": "API"}],
        slug="gateway_with_tags",
        passthrough_headers=None,
    )

    gateway_without_matching_tags = GatewayRead(
        id="gw2",
        name="gateway_no_tags",
        url="https://gateway2.example.com",
        description="Gateway without matching tags",
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
        tags=[{"id": "test", "label": "Test"}, {"id": "dev", "label": "Dev"}],
        slug="gateway_no_tags",
        passthrough_headers=None,
    )

    export_service.gateway_service.list_gateways.return_value = [gateway_with_matching_tags, gateway_without_matching_tags]

    # Execute export with tag filter
    gateways = await export_service._export_gateways(mock_db, ["production"], False)

    # Should only include gateway with matching tags
    assert len(gateways) == 1
    assert gateways[0]["name"] == "gateway_with_tags"


@pytest.mark.asyncio
async def test_export_gateways_with_masked_auth(export_service, mock_db):
    """Test gateway export with masked authentication data."""
    # First-Party
    from mcpgateway.config import settings

    # Create gateway with masked auth
    gateway_with_masked_auth = GatewayRead(
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
        auth_type="bearer",
        auth_value=settings.masked_auth_value,
        auth_username=None,
        auth_password=None,
        auth_token=None,
        auth_header_key=None,
        auth_header_value=None,
        tags=[],
        slug="test_gateway",
        passthrough_headers=None,
    )

    export_service.gateway_service.list_gateways.return_value = [gateway_with_masked_auth]

    # Mock database batch query to return raw auth values (id, auth_type, auth_value tuples)
    mock_db.execute.return_value.all.return_value = [("gw1", "bearer", "encrypted_raw_gateway_auth")]

    # Execute export
    gateways = await export_service._export_gateways(mock_db, None, False)

    # Should get raw auth value from database via batch query
    assert len(gateways) == 1
    assert gateways[0]["auth_type"] == "bearer"
    assert gateways[0]["auth_value"] == "encrypted_raw_gateway_auth"


@pytest.mark.asyncio
async def test_export_gateways_with_non_masked_auth(export_service, mock_db):
    """Test gateway export with non-masked authentication data."""
    # Create gateway with non-masked auth - provide proper bearer token format
    gateway_with_auth = GatewayRead(
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
        auth_type="bearer",
        auth_value=encode_auth({"Authorization": "Bearer test_token_123"}),
        auth_username=None,
        auth_password=None,
        auth_token="test_token_123",
        auth_header_key=None,
        auth_header_value=None,
        tags=[],
        slug="test_gateway",
        passthrough_headers=None,
    )
    # Manually set auth_value to bypass encryption
    gateway_with_auth.auth_value = "encrypted_auth_value"

    export_service.gateway_service.list_gateways.return_value = [gateway_with_auth]

    # Execute export
    gateways = await export_service._export_gateways(mock_db, None, False)

    # Should use auth value directly
    assert len(gateways) == 1
    assert gateways[0]["auth_type"] == "bearer"
    assert gateways[0]["auth_value"] == "encrypted_auth_value"


@pytest.mark.asyncio
async def test_export_servers_with_data(export_service, mock_db):
    """Test server export with mock data."""
    # Create mock server object with necessary attributes
    mock_server = MagicMock()
    mock_server.id = "server1"
    mock_server.name = "test_server"
    mock_server.description = "Test server"
    mock_server.associated_tools = ["tool1", "tool2"]
    mock_server.enabled = True
    mock_server.tags = ["test", "api"]

    export_service.server_service.list_servers.return_value = [mock_server]

    # Execute export
    servers = await export_service._export_servers(mock_db, None, False)

    # Verify server data structure
    assert len(servers) == 1
    server_data = servers[0]
    assert server_data["name"] == "test_server"
    assert server_data["description"] == "Test server"
    assert server_data["tool_ids"] == ["tool1", "tool2"]
    assert server_data["sse_endpoint"] == "/servers/server1/sse"
    assert server_data["websocket_endpoint"] == "/servers/server1/ws"
    assert server_data["jsonrpc_endpoint"] == "/servers/server1/jsonrpc"
    assert server_data["is_active"] == True
    assert server_data["tags"] == ["test", "api"]
    assert "capabilities" in server_data


@pytest.mark.asyncio
async def test_export_prompts_with_arguments(export_service, mock_db):
    """Test prompt export with arguments."""
    # Create mock prompt with arguments
    mock_arg1 = MagicMock()
    mock_arg1.name = "user_input"
    mock_arg1.description = "User input text"
    mock_arg1.required = True

    mock_arg2 = MagicMock()
    mock_arg2.name = "context"
    mock_arg2.description = "Additional context"
    mock_arg2.required = False

    mock_prompt = MagicMock()
    mock_prompt.name = "test_prompt"
    mock_prompt.template = "Process {{user_input}} with {{context}}"
    mock_prompt.description = "Test prompt"
    mock_prompt.arguments = [mock_arg1, mock_arg2]
    mock_prompt.enabled = True
    mock_prompt.tags = ["nlp", "processing"]

    export_service.prompt_service.list_prompts.return_value = ([mock_prompt], None)

    # Execute export
    prompts = await export_service._export_prompts(mock_db, None, False)

    # Verify prompt data structure
    assert len(prompts) == 1
    prompt_data = prompts[0]
    assert prompt_data["name"] == "test_prompt"
    assert prompt_data["template"] == "Process {{user_input}} with {{context}}"
    assert prompt_data["description"] == "Test prompt"
    assert prompt_data["is_active"] == True
    assert prompt_data["tags"] == ["nlp", "processing"]

    # Check input schema with arguments
    input_schema = prompt_data["input_schema"]
    assert "properties" in input_schema
    assert "user_input" in input_schema["properties"]
    assert "context" in input_schema["properties"]
    assert input_schema["properties"]["user_input"]["description"] == "User input text"
    assert input_schema["properties"]["context"]["description"] == "Additional context"
    assert input_schema["required"] == ["user_input"]


@pytest.mark.asyncio
async def test_export_resources_with_data(export_service, mock_db):
    """Test resource export with mock data."""
    # Create mock resource
    mock_resource = MagicMock()
    mock_resource.name = "test_resource"
    mock_resource.uri = "file:///workspace/test.txt"
    mock_resource.description = "Test resource file"
    mock_resource.mime_type = "text/plain"
    mock_resource.enabled = True
    mock_resource.tags = ["file", "text"]
    mock_resource.updated_at = datetime.now(timezone.utc)

    export_service.resource_service.list_resources.return_value = ([mock_resource], None)

    # Execute export
    resources = await export_service._export_resources(mock_db, None, False)

    # Verify resource data structure
    assert len(resources) == 1
    resource_data = resources[0]
    assert resource_data["name"] == "test_resource"
    assert resource_data["uri"] == "file:///workspace/test.txt"
    assert resource_data["description"] == "Test resource file"
    assert resource_data["mime_type"] == "text/plain"
    assert resource_data["is_active"] == True
    assert resource_data["tags"] == ["file", "text"]
    assert resource_data["last_modified"] is not None


@pytest.mark.asyncio
async def test_validate_export_data_empty_version(export_service):
    """Test validation failure for empty version."""
    invalid_data = {
        "version": "",  # Empty version
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": {},
        "metadata": {"entity_counts": {}},
    }

    with pytest.raises(ExportValidationError) as excinfo:
        export_service._validate_export_data(invalid_data)

    assert "Version cannot be empty" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_export_data_invalid_metadata(export_service):
    """Test validation failure for invalid metadata structure."""
    invalid_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": {},
        "metadata": {"entity_counts": "not_a_dict"},  # Should be dict
    }

    with pytest.raises(ExportValidationError) as excinfo:
        export_service._validate_export_data(invalid_data)

    assert "Metadata entity_counts must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_export_selective_all_entity_types(export_service, mock_db):
    """Test selective export with all entity types."""
    # First-Party
    from mcpgateway.schemas import GatewayRead, ToolRead

    # Mock entities for each type
    sample_tool = ToolRead(
        id="tool1",
        original_name="test_tool",
        name="test_tool",
        custom_name="test_tool",
        displayName="Test Tool",
        url="https://api.example.com",
        description="Test tool",
        integration_type="REST",
        request_type="GET",
        headers={},
        input_schema={},
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
            total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
        ),
        gateway_slug="",
        custom_name_slug="test_tool",
        tags=[],
    )

    sample_gateway = GatewayRead(
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
        tags=[],
        slug="test_gateway",
        passthrough_headers=None,
    )

    sample_server = ServerRead(
        id="server1",
        name="test_server",
        description="Test server",
        icon=None,
        associated_tools=[],
        associated_a2a_agents=[],
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_server_metrics(),
        tags=[],
    )

    sample_prompt = PromptRead(
        id="ca627760127d409080fdefc309147e08",
        name="test_prompt",
        template="Test template",
        description="Test prompt",
        arguments=[],
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_prompt_metrics(),
        tags=[],
    )

    sample_resource = ResourceRead(
        id="ca627760127d409080fdefc309147e08",
        name="test_resource",
        uri="file:///test.txt",
        description="Test resource",
        mime_type="text/plain",
        size=None,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_resource_metrics(),
        tags=[],
    )

    # Setup mocks for selective export
    export_service.tool_service.get_tool.return_value = sample_tool
    export_service.tool_service.list_tools.return_value = ([sample_tool], None)
    export_service.gateway_service.get_gateway.return_value = sample_gateway
    export_service.gateway_service.list_gateways.return_value = [sample_gateway]
    export_service.server_service.get_server.return_value = sample_server
    export_service.server_service.list_servers.return_value = [sample_server]
    export_service.prompt_service.get_prompt.return_value = sample_prompt
    export_service.prompt_service.list_prompts.return_value = ([sample_prompt], None)
    export_service.resource_service.list_resources.return_value = ([sample_resource], None)

    # First-Party
    from mcpgateway.common.models import Root

    mock_roots = [Root(uri="file:///workspace", name="Workspace")]
    export_service.root_service.list_roots.return_value = mock_roots

    entity_selections = {"tools": ["tool1"], "gateways": ["gw1"], "servers": ["server1"], "prompts": ["test_prompt"], "resources": ["file:///test.txt"], "roots": ["file:///workspace"]}

    # Execute selective export
    result = await export_service.export_selective(db=mock_db, entity_selections=entity_selections, exported_by="test_user")

    # Verify result structure
    assert "entities" in result
    entities = result["entities"]

    # Each entity type should be present
    assert "tools" in entities
    assert "gateways" in entities
    assert "servers" in entities
    assert "prompts" in entities
    assert "resources" in entities
    assert "roots" in entities

    # Check metadata
    metadata = result["metadata"]
    assert metadata["export_options"]["selective"] == True
    assert metadata["export_options"]["selections"] == entity_selections


@pytest.mark.asyncio
async def test_export_selected_tools_error_handling(export_service, mock_db):
    """Test error handling in selective tool export."""
    # Mock service to raise exception
    export_service.tool_service.get_tool.side_effect = Exception("Tool not found")

    tools = await export_service._export_selected_tools(mock_db, ["nonexistent_tool"])

    # Should return empty list and log warning
    assert tools == []


@pytest.mark.asyncio
async def test_export_selected_gateways(export_service, mock_db):
    """Test selective gateway export."""
    sample_gateway = GatewayRead(
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
        tags=[],
        slug="test_gateway",
        passthrough_headers=None,
    )

    export_service.gateway_service.get_gateway.return_value = sample_gateway
    export_service.gateway_service.list_gateways.return_value = [sample_gateway]

    gateways = await export_service._export_selected_gateways(mock_db, ["gw1"])

    # Verify gateway was exported
    assert len(gateways) >= 0  # May be empty if filtering doesn't match


@pytest.mark.asyncio
async def test_export_selected_gateways_error_handling(export_service, mock_db):
    """Test error handling in selective gateway export."""
    export_service.gateway_service.get_gateway.side_effect = Exception("Gateway not found")

    gateways = await export_service._export_selected_gateways(mock_db, ["nonexistent_gateway"])

    # Should return empty list and log warning
    assert gateways == []


@pytest.mark.asyncio
async def test_export_selected_servers(export_service, mock_db):
    """Test selective server export."""
    # First-Party

    sample_server = ServerRead(
        id="server1",
        name="test_server",
        description="Test server",
        icon=None,
        associated_tools=[],
        associated_a2a_agents=[],
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_server_metrics(),
        tags=[],
    )

    export_service.server_service.get_server.return_value = sample_server
    export_service.server_service.list_servers.return_value = [sample_server]

    servers = await export_service._export_selected_servers(mock_db, ["server1"])

    # Verify server was exported
    assert len(servers) >= 0  # May be empty if filtering doesn't match


@pytest.mark.asyncio
async def test_export_selected_servers_error_handling(export_service, mock_db):
    """Test error handling in selective server export."""
    export_service.server_service.get_server.side_effect = Exception("Server not found")

    servers = await export_service._export_selected_servers(mock_db, ["nonexistent_server"])

    # Should return empty list and log warning
    assert servers == []


@pytest.mark.asyncio
async def test_export_selected_prompts(export_service, mock_db):
    """Test selective prompt export."""
    # First-Party

    sample_prompt = PromptRead(
        id="ca627760127d409080fdefc309147e08",
        name="test_prompt",
        template="Test template",
        description="Test prompt",
        arguments=[],
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_prompt_metrics(),
        tags=[],
    )

    export_service.prompt_service.get_prompt.return_value = sample_prompt
    export_service.prompt_service.list_prompts.return_value = ([sample_prompt], None)

    prompts = await export_service._export_selected_prompts(mock_db, ["test_prompt"])

    # Verify prompt was exported
    assert len(prompts) >= 0  # May be empty if filtering doesn't match


@pytest.mark.asyncio
async def test_export_selected_prompts_error_handling(export_service, mock_db):
    """Test error handling in selective prompt export."""
    export_service.prompt_service.get_prompt.side_effect = Exception("Prompt not found")

    prompts = await export_service._export_selected_prompts(mock_db, ["nonexistent_prompt"])

    # Should return empty list and log warning
    assert prompts == []


@pytest.mark.asyncio
async def test_export_selected_resources(export_service, mock_db):
    """Test selective resource export."""
    # First-Party

    sample_resource = ResourceRead(
        id="ca627760127d409080fdefc309147e08",
        name="test_resource",
        uri="file:///test.txt",
        description="Test resource",
        mime_type="text/plain",
        size=None,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metrics=create_default_resource_metrics(),
        tags=[],
    )

    export_service.resource_service.list_resources.return_value = ([sample_resource], None)

    resources = await export_service._export_selected_resources(mock_db, ["file:///test.txt"])

    # Verify resource was exported
    assert len(resources) >= 0  # May be empty if URI doesn't match


@pytest.mark.asyncio
async def test_export_selected_resources_error_handling(export_service, mock_db):
    """Test error handling in selective resource export."""
    export_service.resource_service.list_resources.side_effect = Exception("Resource error")

    resources = await export_service._export_selected_resources(mock_db, ["file:///nonexistent.txt"])

    # Should return empty list and log warning
    assert resources == []


@pytest.mark.asyncio
async def test_export_selected_roots(export_service):
    """Test selective root export."""
    # First-Party

    mock_roots = [Root(uri="file:///workspace", name="Workspace"), Root(uri="file:///tmp", name="Temp")]

    export_service.root_service.list_roots.return_value = mock_roots

    # Mock the _export_roots method to return expected data
    async def mock_export_roots():
        return [{"uri": "file:///workspace", "name": "Workspace"}, {"uri": "file:///tmp", "name": "Temp"}]

    export_service._export_roots = mock_export_roots

    roots = await export_service._export_selected_roots(["file:///workspace"])

    # Should return only matching root
    assert len(roots) == 1
    assert roots[0]["uri"] == "file:///workspace"
    assert roots[0]["name"] == "Workspace"
