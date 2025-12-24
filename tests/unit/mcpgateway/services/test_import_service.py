# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_import_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for import service implementation.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.gateway_service import GatewayNameConflictError
from mcpgateway.services.import_service import ConflictStrategy, ImportError, ImportService, ImportStatus, ImportValidationError
from mcpgateway.services.prompt_service import PromptNameConflictError
from mcpgateway.services.resource_service import ResourceURIConflictError
from mcpgateway.services.server_service import ServerNameConflictError
from mcpgateway.services.tool_service import ToolNameConflictError


@pytest.fixture
def import_service():
    """Create an import service instance with mocked dependencies."""
    service = ImportService()
    service.tool_service = AsyncMock()
    service.gateway_service = AsyncMock()
    service.server_service = AsyncMock()
    service.prompt_service = AsyncMock()
    service.resource_service = AsyncMock()
    service.root_service = AsyncMock()

    # Setup default return values for bulk registration methods
    service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }
    service.prompt_service.register_prompts_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }
    service.resource_service.register_resources_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    return service


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def valid_import_data():
    """Create valid import data for testing."""
    return {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "exported_by": "test_user",
        "entities": {
            "tools": [{"name": "test_tool", "url": "https://api.example.com/tool", "integration_type": "REST", "request_type": "GET", "description": "Test tool", "tags": ["api"]}],
            "gateways": [{"name": "test_gateway", "url": "https://gateway.example.com", "description": "Test gateway", "transport": "SSE"}],
        },
        "metadata": {"entity_counts": {"tools": 1, "gateways": 1}},
    }


@pytest.mark.asyncio
async def test_validate_import_data_success(import_service, valid_import_data):
    """Test successful import data validation."""
    # Should not raise any exception
    import_service.validate_import_data(valid_import_data)


@pytest.mark.asyncio
async def test_validate_import_data_missing_version(import_service):
    """Test import data validation with missing version."""
    invalid_data = {"exported_at": "2025-01-01T00:00:00Z", "entities": {}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Missing required field: version" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_invalid_entities(import_service):
    """Test import data validation with invalid entities structure."""
    invalid_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": "not_a_dict"}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Entities must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_import_data_unknown_entity_type(import_service):
    """Test import data validation with unknown entity type."""
    invalid_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"unknown_type": []}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "Unknown entity type: unknown_type" in str(excinfo.value)


@pytest.mark.asyncio
async def test_validate_entity_fields_missing_required(import_service):
    """Test entity field validation with missing required fields."""
    entity_data = {
        "url": "https://example.com"
        # Missing required 'name' field for tools
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service._validate_entity_fields("tools", entity_data, 0)

    assert "missing required field: name" in str(excinfo.value)


@pytest.mark.asyncio
async def test_import_configuration_success(import_service, mock_db, valid_import_data):
    """Test successful configuration import."""
    # Setup mocks for successful bulk creation
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }
    import_service.gateway_service.register_gateway.return_value = MagicMock()

    # Execute import
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.total_entities == 2
    assert status.created_entities == 2
    assert status.failed_entities == 0

    # Verify service calls - tools use bulk registration
    import_service.tool_service.register_tools_bulk.assert_called_once()
    import_service.gateway_service.register_gateway.assert_called_once()


@pytest.mark.asyncio
async def test_import_configuration_dry_run(import_service, mock_db, valid_import_data):
    """Test dry-run import functionality."""
    # Execute dry-run import
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, dry_run=True, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.total_entities == 2
    assert len(status.warnings) >= 2  # Should have warnings for would-be imports

    # Verify no actual service calls were made
    import_service.tool_service.register_tool.assert_not_called()
    import_service.gateway_service.register_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_import_configuration_conflict_skip(import_service, mock_db, valid_import_data):
    """Test import with skip conflict strategy."""
    # Setup mocks for conflict scenario - bulk methods return stats
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []
    }
    import_service.gateway_service.register_gateway.side_effect = GatewayNameConflictError("test_gateway")

    # Execute import with skip strategy
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, conflict_strategy=ConflictStrategy.SKIP, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.skipped_entities == 2
    assert status.created_entities == 0
    assert len(status.warnings) >= 1


@pytest.mark.asyncio
async def test_import_configuration_conflict_update(import_service, mock_db, valid_import_data):
    """Test import with update conflict strategy."""
    # Setup mocks for conflict scenario - bulk methods handle updates internally
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 1, "skipped": 0, "failed": 0, "errors": []
    }
    import_service.gateway_service.register_gateway.side_effect = GatewayNameConflictError("test_gateway")

    # Mock existing entities for update
    mock_gateway = MagicMock()
    mock_gateway.name = "test_gateway"
    mock_gateway.id = "gw1"
    import_service.gateway_service.list_gateways.return_value = [mock_gateway]

    # Execute import with update strategy
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.updated_entities == 2

    # Verify update calls were made for gateway
    import_service.gateway_service.update_gateway.assert_called_once()


@pytest.mark.asyncio
async def test_import_configuration_conflict_fail(import_service, mock_db, valid_import_data):
    """Test import with fail conflict strategy."""
    # Setup mocks for conflict scenario - bulk methods return failures
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 1, "errors": ["Tool name conflict: test_tool"]
    }
    import_service.gateway_service.register_gateway.side_effect = GatewayNameConflictError("test_gateway")

    # Execute import with fail strategy
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, conflict_strategy=ConflictStrategy.FAIL, imported_by="test_user")

    # Verify conflicts caused failures
    assert status.status == "completed"  # Import completes but with failures
    assert status.failed_entities == 2  # Both entities should fail
    assert status.created_entities == 0  # No entities should be created


@pytest.mark.asyncio
async def test_import_configuration_selective(import_service, mock_db, valid_import_data):
    """Test selective import functionality."""
    # Setup mocks for bulk registration
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }
    import_service.gateway_service.register_gateway.return_value = MagicMock()

    selected_entities = {
        "tools": ["test_tool"]
        # Only import the tool, skip the gateway
    }

    # Execute selective import
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, selected_entities=selected_entities, imported_by="test_user")

    # Validate status - in the current implementation, both entities are processed
    # but the gateway should be skipped during processing due to selective filtering
    assert status.status == "completed"
    # The actual behavior creates both because both tools and gateways are processed
    # but only the tool matches the selection
    assert status.created_entities >= 1  # At least the tool should be created

    # Verify tool service bulk method was called
    import_service.tool_service.register_tools_bulk.assert_called_once()


@pytest.mark.asyncio
async def test_import_configuration_error_handling(import_service, mock_db, valid_import_data):
    """Test import error handling when unexpected exceptions occur."""
    # Setup mocks to raise unexpected error in bulk registration
    import_service.tool_service.register_tools_bulk.side_effect = Exception("Unexpected database error")
    import_service.gateway_service.register_gateway.side_effect = Exception("Unexpected database error")

    # Execute import - should handle the exception gracefully and continue
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, imported_by="test_user")

    # Should complete with failures
    assert status.status == "completed"
    assert status.failed_entities >= 1  # At least one entity should fail
    assert status.created_entities == 0


@pytest.mark.asyncio
async def test_validate_import_data_invalid_entity_structure(import_service):
    """Test validation with non-dict entity in list."""
    invalid_data = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "entities": {
            "tools": [
                "not_a_dict"  # Should be a dictionary
            ]
        },
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data)

    assert "must be a dictionary" in str(excinfo.value)


@pytest.mark.asyncio
async def test_rekey_auth_data_success(import_service):
    """Test successful authentication data re-keying."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.utils.services_auth import encode_auth

    # Store original secret
    original_secret = settings.auth_encryption_secret.get_secret_value()

    try:
        # Create entity with auth data using a specific secret
        settings.auth_encryption_secret = "original-key"
        original_auth = {"type": "bearer", "token": "test_token"}
        entity_data = {"name": "test_tool", "auth_type": "bearer", "auth_value": encode_auth(original_auth)}
        original_auth_value = entity_data["auth_value"]

        # Test re-keying with different secret
        new_secret = "new-encryption-key"
        result = import_service._rekey_auth_data(entity_data, new_secret)

        # Should have the same basic structure but potentially different auth_value
        assert result["name"] == "test_tool"
        assert result["auth_type"] == "bearer"
        assert "auth_value" in result

    finally:
        # Restore original secret
        settings.auth_encryption_secret = original_secret


@pytest.mark.asyncio
async def test_rekey_auth_data_no_auth(import_service):
    """Test re-keying data without auth fields."""
    entity_data = {"name": "test_tool", "url": "https://example.com"}

    result = import_service._rekey_auth_data(entity_data, "new-key")

    # Should return unchanged
    assert result == entity_data


@pytest.mark.asyncio
async def test_rekey_auth_data_error_handling(import_service):
    """Test error handling in auth data re-keying."""
    entity_data = {
        "name": "test_tool",
        "auth_type": "bearer",
        "auth_value": "invalid_encrypted_data",  # Invalid encrypted data
    }

    with pytest.raises(ImportError) as excinfo:
        import_service._rekey_auth_data(entity_data, "new-key")

    assert "Failed to re-key authentication data" in str(excinfo.value)


@pytest.mark.asyncio
async def test_process_server_entities(import_service, mock_db):
    """Test processing server entities."""
    server_data = {"name": "test_server", "description": "Test server", "tool_ids": ["tool1", "tool2"], "is_active": True}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup mocks
    import_service.server_service.register_server.return_value = MagicMock()
    import_service.tool_service.list_tools.return_value = ([], None)

    # Execute import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.created_entities == 1

    # Verify server service was called
    import_service.server_service.register_server.assert_called_once()


@pytest.mark.asyncio
async def test_process_prompt_entities(import_service, mock_db):
    """Test processing prompt entities."""
    prompt_data = {"name": "test_prompt", "template": "Hello {{name}}", "description": "Test prompt", "is_active": True}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Setup mocks - use bulk registration
    import_service.prompt_service.register_prompts_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    # Execute import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.created_entities == 1

    # Verify prompt service bulk method was called
    import_service.prompt_service.register_prompts_bulk.assert_called_once()


@pytest.mark.asyncio
async def test_process_resource_entities(import_service, mock_db):
    """Test processing resource entities."""
    resource_data = {"name": "test_resource", "uri": "file:///test.txt", "description": "Test resource", "mime_type": "text/plain", "is_active": True}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Setup mocks - use bulk registration
    import_service.resource_service.register_resources_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    # Execute import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.created_entities == 1

    # Verify resource service bulk method was called
    import_service.resource_service.register_resources_bulk.assert_called_once()


@pytest.mark.asyncio
async def test_process_root_entities(import_service, mock_db):
    """Test processing root entities."""
    root_data = {"uri": "file:///workspace", "name": "Workspace"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"roots": [root_data]}, "metadata": {"entity_counts": {"roots": 1}}}

    # Setup mocks
    import_service.root_service.add_root.return_value = MagicMock()
    mock_db.flush.return_value = None  # Mock flush method

    # Execute import
    status = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        imported_by="test_user",
    )

    # Validate status
    assert status.status == "completed"
    assert status.created_entities == 1

    # Verify root service was called
    import_service.root_service.add_root.assert_called_once()


@pytest.mark.asyncio
async def test_import_status_tracking(import_service):
    """Test import status tracking functionality."""
    # Create import status
    import_id = "test-import-123"
    status = ImportStatus(import_id)

    # Verify initial state
    assert status.import_id == import_id
    assert status.status == "pending"
    assert status.total_entities == 0
    assert status.processed_entities == 0
    assert status.created_entities == 0
    assert status.updated_entities == 0
    assert status.skipped_entities == 0
    assert status.failed_entities == 0
    assert len(status.errors) == 0
    assert len(status.warnings) == 0
    assert status.completed_at is None

    # Test to_dict method
    status_dict = status.to_dict()
    assert status_dict["import_id"] == import_id
    assert status_dict["status"] == "pending"
    assert "progress" in status_dict
    assert "errors" in status_dict
    assert "warnings" in status_dict
    assert "started_at" in status_dict
    assert status_dict["completed_at"] is None


@pytest.mark.asyncio
async def test_import_service_initialization(import_service):
    """Test import service initialization and shutdown."""
    # Test initialization
    await import_service.initialize()

    # Test shutdown
    await import_service.shutdown()


@pytest.mark.asyncio
async def test_import_with_rekey_secret(import_service, mock_db):
    """Test import with authentication re-keying."""
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Create tool with auth data
    original_auth = {"type": "bearer", "token": "old_token"}
    tool_data = {
        "name": "auth_tool",
        "url": "https://api.example.com",
        "integration_type": "REST",
        "request_type": "GET",
        "description": "Tool with auth",
        "auth_type": "bearer",
        "auth_value": encode_auth(original_auth),
    }

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"tools": [tool_data]}, "metadata": {"entity_counts": {"tools": 1}}}

    # Setup mocks for bulk registration
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    # Execute import with rekey secret
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, rekey_secret="new-encryption-key", imported_by="test_user")

    # Validate status
    assert status.status == "completed"
    assert status.created_entities == 1

    # Verify tool service bulk method was called with re-keyed data
    import_service.tool_service.register_tools_bulk.assert_called_once()


@pytest.mark.asyncio
async def test_import_skipped_entity(import_service, mock_db, valid_import_data):
    """Test skipped entity handling."""
    # Setup selective entities that don't match any entities in the data
    selected_entities = {
        "tools": ["non_existent_tool"]  # This doesn't match "test_tool"
    }

    # Execute selective import
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, selected_entities=selected_entities, imported_by="test_user")

    # Should complete but skip entities not in selection
    assert status.status == "completed"


@pytest.mark.asyncio
async def test_import_status_tracking(import_service):
    """Test import status tracking functionality."""
    import_id = "test_import_123"
    status = ImportStatus(import_id)
    import_service.active_imports[import_id] = status

    # Test status retrieval
    retrieved_status = import_service.get_import_status(import_id)
    assert retrieved_status == status
    assert retrieved_status.import_id == import_id

    # Test status listing
    all_statuses = import_service.list_import_statuses()
    assert status in all_statuses

    # Test status cleanup
    status.status = "completed"
    status.completed_at = datetime.now(timezone.utc)

    # Mock datetime to test cleanup
    with patch("mcpgateway.services.import_service.datetime") as mock_datetime:
        # Set current time to 25 hours after completion
        mock_datetime.now.return_value = status.completed_at + timedelta(hours=25)

        removed_count = import_service.cleanup_completed_imports(max_age_hours=24)
        assert removed_count == 1
        assert import_id not in import_service.active_imports


@pytest.mark.asyncio
async def test_convert_schema_methods(import_service):
    """Test schema conversion methods."""
    tool_data = {
        "name": "test_tool",
        "url": "https://api.example.com",
        "integration_type": "REST",
        "request_type": "GET",
        "description": "Test tool",
        "tags": ["api"],
        "auth_type": "bearer",
        "auth_value": "encrypted_token",
    }

    # Test tool create conversion
    tool_create = import_service._convert_to_tool_create(tool_data)
    assert isinstance(tool_create, ToolCreate)
    assert tool_create.name == "test_tool"
    assert str(tool_create.url) == "https://api.example.com"
    assert tool_create.auth is not None
    assert tool_create.auth.auth_type == "bearer"

    # Test tool update conversion
    tool_update = import_service._convert_to_tool_update(tool_data)
    assert tool_update.name == "test_tool"
    assert str(tool_update.url) == "https://api.example.com"


@pytest.mark.asyncio
async def test_get_entity_identifier(import_service):
    """Test entity identifier extraction."""
    # Test tools (uses name)
    tool_entity = {"name": "test_tool", "url": "https://example.com"}
    assert import_service._get_entity_identifier("tools", tool_entity) == "test_tool"

    # Test resources (uses uri)
    resource_entity = {"name": "test_resource", "uri": "/api/data"}
    assert import_service._get_entity_identifier("resources", resource_entity) == "/api/data"

    # Test roots (uses uri)
    root_entity = {"name": "workspace", "uri": "file:///workspace"}
    assert import_service._get_entity_identifier("roots", root_entity) == "file:///workspace"


@pytest.mark.asyncio
async def test_calculate_total_entities(import_service):
    """Test entity count calculation with selection filters."""
    entities = {"tools": [{"name": "tool1"}, {"name": "tool2"}], "gateways": [{"name": "gateway1"}]}

    # Test without selection (should count all)
    total = import_service._calculate_total_entities(entities, None)
    assert total == 3

    # Test with selection
    selected_entities = {
        "tools": ["tool1"]  # Only select one tool
    }
    total = import_service._calculate_total_entities(entities, selected_entities)
    assert total == 1

    # Test with empty selection for entity type
    selected_entities = {
        "tools": []  # Empty list means include all tools
    }
    total = import_service._calculate_total_entities(entities, selected_entities)
    assert total == 2


@pytest.mark.asyncio
async def test_import_service_initialization(import_service):
    """Test import service initialization and shutdown."""
    # Test initialization
    await import_service.initialize()

    # Test shutdown
    await import_service.shutdown()


@pytest.mark.asyncio
async def test_has_auth_data_variations(import_service):
    """Test _has_auth_data with various data structures."""
    # Entity with auth data
    entity_with_auth = {"name": "test", "auth_value": "encrypted_data"}
    assert import_service._has_auth_data(entity_with_auth)

    # Entity without auth_value key
    entity_no_key = {"name": "test"}
    assert not import_service._has_auth_data(entity_no_key)

    # Entity with empty auth_value
    entity_empty = {"name": "test", "auth_value": ""}
    assert not import_service._has_auth_data(entity_empty)

    # Entity with None auth_value
    entity_none = {"name": "test", "auth_value": None}
    assert not import_service._has_auth_data(entity_none)


@pytest.mark.asyncio
async def test_import_configuration_with_errors(import_service, mock_db, valid_import_data):
    """Test import configuration with processing errors."""
    # Setup services to raise errors - bulk method raises exception
    import_service.tool_service.register_tools_bulk.side_effect = Exception("Database error")
    import_service.gateway_service.register_gateway.return_value = MagicMock()

    # Execute import
    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, imported_by="test_user")

    # Should have some failures
    assert status.failed_entities > 0
    assert len(status.errors) > 0
    assert status.status == "completed"  # Import continues despite failures


@pytest.mark.asyncio
async def test_import_status_tracking_complete_workflow(import_service):
    """Test complete import status tracking workflow."""
    import_id = "test_import_456"
    status = ImportStatus(import_id)

    # Test initial state
    assert status.status == "pending"
    assert status.total_entities == 0
    assert status.created_entities == 0

    # Test status updates
    status.status = "running"
    status.total_entities = 10
    status.processed_entities = 5
    status.created_entities = 3
    status.updated_entities = 2
    status.skipped_entities = 0
    status.failed_entities = 0

    # Test to_dict conversion
    status_dict = status.to_dict()
    assert status_dict["import_id"] == import_id
    assert status_dict["status"] == "running"
    assert status_dict["progress"]["total"] == 10
    assert status_dict["progress"]["created"] == 3
    assert status_dict["progress"]["updated"] == 2

    # Add to service tracking
    import_service.active_imports[import_id] = status

    # Test retrieval
    retrieved = import_service.get_import_status(import_id)
    assert retrieved == status

    # Test listing
    all_statuses = import_service.list_import_statuses()
    assert status in all_statuses


@pytest.mark.asyncio
async def test_import_validation_edge_cases(import_service):
    """Test import validation with various edge cases."""
    # Test empty version
    invalid_data1 = {"version": "", "exported_at": "2025-01-01T00:00:00Z", "entities": {}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data1)
    assert "Version field cannot be empty" in str(excinfo.value)

    # Test non-dict entities
    invalid_data2 = {
        "version": "2025-03-26",
        "exported_at": "2025-01-01T00:00:00Z",
        "entities": [],  # Should be dict, not list
    }

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data2)
    assert "Entities must be a dictionary" in str(excinfo.value)

    # Test non-list entity type
    invalid_data3 = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"tools": "not_a_list"}}

    with pytest.raises(ImportValidationError) as excinfo:
        import_service.validate_import_data(invalid_data3)
    assert "Entity type 'tools' must be a list" in str(excinfo.value)


@pytest.mark.asyncio
async def test_import_configuration_with_selected_entities(import_service, mock_db, valid_import_data):
    """Test import with selected entities filter."""
    # Setup mocks for bulk registration
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }
    import_service.gateway_service.register_gateway.return_value = MagicMock()

    # Test with specific entity selection
    selected_entities = {
        "tools": ["test_tool"],
        "gateways": [],  # Empty list should include all gateways
    }

    status = await import_service.import_configuration(db=mock_db, import_data=valid_import_data, selected_entities=selected_entities, imported_by="test_user")

    # Should process entities based on selection
    assert status.status == "completed"
    assert status.processed_entities >= 1


@pytest.mark.asyncio
async def test_conversion_methods_comprehensive(import_service, mock_db):
    """Test all schema conversion methods."""
    # Test gateway conversion without auth (simpler test)
    gateway_data = {"name": "test_gateway", "url": "https://gateway.example.com", "description": "Test gateway", "transport": "SSE", "tags": ["test"]}

    gateway_create = import_service._convert_to_gateway_create(gateway_data)
    assert gateway_create.name == "test_gateway"
    assert str(gateway_create.url) == "https://gateway.example.com"

    # Test server conversion with mock db
    server_data = {"name": "test_server", "description": "Test server", "tool_ids": ["tool1", "tool2"], "tags": ["server"]}

    # Mock the list_tools method to return empty list (no tools to resolve)
    import_service.tool_service.list_tools.return_value = ([], None)

    server_create = await import_service._convert_to_server_create(mock_db, server_data)
    assert server_create.name == "test_server"
    assert server_create.associated_tools == []  # Empty because no tools found to resolve

    # Test prompt conversion with schema
    prompt_data = {
        "name": "test_prompt",
        "template": "Hello {{name}}!",
        "description": "Test prompt",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "User name"}}, "required": ["name"]},
        "tags": ["prompt"],
    }

    prompt_create = import_service._convert_to_prompt_create(prompt_data)
    assert prompt_create.name == "test_prompt"
    assert prompt_create.template == "Hello {{name}}!"
    assert len(prompt_create.arguments) == 1
    assert prompt_create.arguments[0].name == "name"
    assert prompt_create.arguments[0].required == True

    # Test resource conversion
    resource_data = {"name": "test_resource", "uri": "/api/test", "description": "Test resource", "mime_type": "application/json", "tags": ["resource"]}

    resource_create = import_service._convert_to_resource_create(resource_data)
    assert resource_create.name == "test_resource"
    assert resource_create.uri == "/api/test"
    assert resource_create.mime_type == "application/json"


@pytest.mark.asyncio
async def test_import_configuration_general_exception_handling(import_service, mock_db, valid_import_data):
    """Test general exception handling in import_configuration method."""
    # Mock validate_import_data to raise a general exception
    import_service.validate_import_data = MagicMock(side_effect=ValueError("Validation failed unexpectedly"))

    # Execute import and expect ImportError
    with pytest.raises(ImportError) as excinfo:
        await import_service.import_configuration(db=mock_db, import_data=valid_import_data, imported_by="test_user")

    assert "Import failed: Validation failed unexpectedly" in str(excinfo.value)


@pytest.mark.asyncio
async def test_get_entity_identifier_unknown_type(import_service):
    """Test _get_entity_identifier with unknown entity type returns empty string."""
    unknown_entity = {"data": "test"}
    result = import_service._get_entity_identifier("unknown_type", unknown_entity)
    assert result == ""  # Line 385


@pytest.mark.asyncio
async def test_tool_conflict_update_not_found(import_service, mock_db):
    """Test tool UPDATE conflict strategy when existing tool not found."""
    tool_data = {"name": "missing_tool", "url": "https://api.example.com", "integration_type": "REST", "request_type": "GET", "description": "Missing tool"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"tools": [tool_data]}, "metadata": {"entity_counts": {"tools": 1}}}

    # Bulk method handles conflicts internally - simulate skipped result
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the tool
    assert status.skipped_entities == 1


@pytest.mark.asyncio
async def test_tool_conflict_update_exception(import_service, mock_db):
    """Test tool UPDATE conflict strategy when update operation fails."""
    tool_data = {"name": "error_tool", "url": "https://api.example.com", "integration_type": "REST", "request_type": "GET", "description": "Error tool"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"tools": [tool_data]}, "metadata": {"entity_counts": {"tools": 1}}}

    # Bulk method handles update failures internally
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 1, "failed": 0,
        "errors": ["Could not update tool error_tool"]
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the tool
    assert status.skipped_entities == 1


@pytest.mark.asyncio
async def test_tool_conflict_rename_strategy(import_service, mock_db):
    """Test tool RENAME conflict strategy."""
    tool_data = {"name": "conflict_tool", "url": "https://api.example.com", "integration_type": "REST", "request_type": "GET", "description": "Conflict tool"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"tools": [tool_data]}, "metadata": {"entity_counts": {"tools": 1}}}

    # Bulk method handles rename strategy internally
    import_service.tool_service.register_tools_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.RENAME, imported_by="test_user")

    # Should create the renamed tool
    assert status.created_entities == 1


@pytest.mark.asyncio
async def test_gateway_conflict_update_not_found(import_service, mock_db):
    """Test gateway UPDATE conflict strategy when existing gateway not found."""
    gateway_data = {"name": "missing_gateway", "url": "https://gateway.example.com", "description": "Missing gateway", "transport": "SSE"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"gateways": [gateway_data]}, "metadata": {"entity_counts": {"gateways": 1}}}

    # Setup conflict and empty list from service
    import_service.gateway_service.register_gateway.side_effect = GatewayNameConflictError("missing_gateway")
    import_service.gateway_service.list_gateways.return_value = []  # Empty list - no existing gateway found

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the gateway and add warning
    assert status.skipped_entities == 1
    assert any("Could not find existing gateway to update" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_gateway_conflict_update_exception(import_service, mock_db):
    """Test gateway UPDATE conflict strategy when update operation fails."""
    gateway_data = {"name": "error_gateway", "url": "https://gateway.example.com", "description": "Error gateway", "transport": "SSE"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"gateways": [gateway_data]}, "metadata": {"entity_counts": {"gateways": 1}}}

    # Setup conflict, existing gateway, but update fails
    import_service.gateway_service.register_gateway.side_effect = GatewayNameConflictError("error_gateway")
    mock_gateway = MagicMock()
    mock_gateway.name = "error_gateway"
    mock_gateway.id = "gateway_id"
    import_service.gateway_service.list_gateways.return_value = [mock_gateway]
    import_service.gateway_service.update_gateway.side_effect = Exception("Update failed")

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the gateway and add warning about update failure
    assert status.skipped_entities == 1
    assert any("Could not update gateway" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_gateway_conflict_rename_strategy(import_service, mock_db):
    """Test gateway RENAME conflict strategy."""
    gateway_data = {"name": "conflict_gateway", "url": "https://gateway.example.com", "description": "Conflict gateway", "transport": "SSE"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"gateways": [gateway_data]}, "metadata": {"entity_counts": {"gateways": 1}}}

    # Setup conflict on first call, success on second (renamed) call
    import_service.gateway_service.register_gateway.side_effect = [
        GatewayNameConflictError("conflict_gateway"),  # First call conflicts
        MagicMock(),  # Second call (with renamed gateway) succeeds
    ]

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.RENAME, imported_by="test_user")

    # Should create the renamed gateway
    assert status.created_entities == 1
    assert any("Renamed gateway" in warning for warning in status.warnings)
    assert import_service.gateway_service.register_gateway.call_count == 2


@pytest.mark.asyncio
async def test_server_dry_run_processing(import_service, mock_db):
    """Test server dry-run processing."""
    server_data = {"name": "test_server", "description": "Test server", "tool_ids": ["tool1", "tool2"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Execute dry-run import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, dry_run=True, imported_by="test_user")

    # Should add dry run warning and not call service
    assert any("Would import server: test_server" in warning for warning in status.warnings)
    import_service.server_service.register_server.assert_not_called()


@pytest.mark.asyncio
async def test_server_conflict_skip_strategy(import_service, mock_db):
    """Test server SKIP conflict strategy."""
    server_data = {"name": "existing_server", "description": "Existing server", "tool_ids": ["tool1"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict
    import_service.server_service.register_server.side_effect = ServerNameConflictError("existing_server")
    import_service.tool_service.list_tools.return_value = ([], None)

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.SKIP, imported_by="test_user")

    # Should skip the server and add warning
    assert status.skipped_entities == 1
    assert any("Skipped existing server: existing_server" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_server_conflict_update_success(import_service, mock_db):
    """Test server UPDATE conflict strategy success."""
    server_data = {"name": "update_server", "description": "Updated server", "tool_ids": ["tool1", "tool2"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict and existing server
    import_service.server_service.register_server.side_effect = ServerNameConflictError("update_server")
    import_service.tool_service.list_tools.return_value = ([], None)
    mock_server = MagicMock()
    mock_server.name = "update_server"
    mock_server.id = "server_id"
    import_service.server_service.list_servers.return_value = [mock_server]
    import_service.server_service.update_server.return_value = MagicMock()

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should update the server
    assert status.updated_entities == 1
    import_service.server_service.update_server.assert_called_once()


@pytest.mark.asyncio
async def test_server_conflict_update_not_found(import_service, mock_db):
    """Test server UPDATE conflict strategy when existing server not found."""
    server_data = {"name": "missing_server", "description": "Missing server", "tool_ids": ["tool1"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict and empty list from service
    import_service.server_service.register_server.side_effect = ServerNameConflictError("missing_server")
    import_service.tool_service.list_tools.return_value = ([], None)
    import_service.server_service.list_servers.return_value = []  # Empty list

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the server and add warning
    assert status.skipped_entities == 1
    assert any("Could not find existing server to update" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_server_conflict_update_exception(import_service, mock_db):
    """Test server UPDATE conflict strategy when update operation fails."""
    server_data = {"name": "error_server", "description": "Error server", "tool_ids": ["tool1"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict, existing server, but update fails
    import_service.server_service.register_server.side_effect = ServerNameConflictError("error_server")
    import_service.tool_service.list_tools.return_value = ([], None)
    mock_server = MagicMock()
    mock_server.name = "error_server"
    mock_server.id = "server_id"
    import_service.server_service.list_servers.return_value = [mock_server]
    import_service.server_service.update_server.side_effect = Exception("Update failed")

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should skip the server and add warning about update failure
    assert status.skipped_entities == 1
    assert any("Could not update server" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_server_conflict_rename_strategy(import_service, mock_db):
    """Test server RENAME conflict strategy."""
    server_data = {"name": "conflict_server", "description": "Conflict server", "tool_ids": ["tool1"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict on first call, success on second (renamed) call
    import_service.server_service.register_server.side_effect = [
        ServerNameConflictError("conflict_server"),  # First call conflicts
        MagicMock(),  # Second call (with renamed server) succeeds
    ]
    import_service.tool_service.list_tools.return_value = ([], None)

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.RENAME, imported_by="test_user")

    # Should create the renamed server
    assert status.created_entities == 1
    assert any("Renamed server" in warning for warning in status.warnings)
    assert import_service.server_service.register_server.call_count == 2


@pytest.mark.asyncio
async def test_server_conflict_fail_strategy(import_service, mock_db):
    """Test server FAIL conflict strategy."""
    server_data = {"name": "fail_server", "description": "Fail server", "tool_ids": ["tool1"]}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [server_data]}, "metadata": {"entity_counts": {"servers": 1}}}

    # Setup conflict
    import_service.server_service.register_server.side_effect = ServerNameConflictError("fail_server")
    import_service.tool_service.list_tools.return_value = ([], None)

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.FAIL, imported_by="test_user")

    # Should fail the server
    assert status.failed_entities == 1
    assert len(status.errors) > 0


@pytest.mark.asyncio
async def test_prompt_dry_run_processing(import_service, mock_db):
    """Test prompt dry-run processing."""
    prompt_data = {"name": "test_prompt", "template": "Hello {{name}}", "description": "Test prompt"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Execute dry-run import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, dry_run=True, imported_by="test_user")

    # Should add dry run warning and not call service
    assert any("Would import prompt: test_prompt" in warning for warning in status.warnings)
    import_service.prompt_service.register_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_prompt_conflict_skip_strategy(import_service, mock_db):
    """Test prompt SKIP conflict strategy."""
    prompt_data = {"name": "existing_prompt", "template": "Hello {{user}}", "description": "Existing prompt"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Bulk method handles conflicts internally
    import_service.prompt_service.register_prompts_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.SKIP, imported_by="test_user")

    # Should skip the prompt
    assert status.skipped_entities == 1


@pytest.mark.asyncio
async def test_prompt_conflict_update_success(import_service, mock_db):
    """Test prompt UPDATE conflict strategy success."""
    prompt_data = {"name": "update_prompt", "template": "Updated template", "description": "Updated prompt"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Bulk method handles updates internally
    import_service.prompt_service.register_prompts_bulk.return_value = {
        "created": 0, "updated": 1, "skipped": 0, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should update the prompt
    assert status.updated_entities == 1


@pytest.mark.asyncio
async def test_prompt_conflict_rename_strategy(import_service, mock_db):
    """Test prompt RENAME conflict strategy."""
    prompt_data = {"name": "conflict_prompt", "template": "Conflict template", "description": "Conflict prompt"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Bulk method handles rename strategy internally
    import_service.prompt_service.register_prompts_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.RENAME, imported_by="test_user")

    # Should create the renamed prompt
    assert status.created_entities == 1


@pytest.mark.asyncio
async def test_prompt_conflict_fail_strategy(import_service, mock_db):
    """Test prompt FAIL conflict strategy."""
    prompt_data = {"name": "fail_prompt", "template": "Fail template", "description": "Fail prompt"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"prompts": [prompt_data]}, "metadata": {"entity_counts": {"prompts": 1}}}

    # Bulk method handles fail strategy internally
    import_service.prompt_service.register_prompts_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 1,
        "errors": ["Prompt name conflict: fail_prompt"]
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.FAIL, imported_by="test_user")

    # Should fail the prompt
    assert status.failed_entities == 1
    assert len(status.errors) > 0


@pytest.mark.asyncio
async def test_resource_dry_run_processing(import_service, mock_db):
    """Test resource dry-run processing."""
    resource_data = {"name": "test_resource", "uri": "/api/test", "description": "Test resource", "mime_type": "application/json"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Execute dry-run import
    status = await import_service.import_configuration(db=mock_db, import_data=import_data, dry_run=True, imported_by="test_user")

    # Should add dry run warning and not call service
    assert any("Would import resource: /api/test" in warning for warning in status.warnings)
    import_service.resource_service.register_resource.assert_not_called()


@pytest.mark.asyncio
async def test_resource_conflict_skip_strategy(import_service, mock_db):
    """Test resource SKIP conflict strategy."""
    resource_data = {"name": "existing_resource", "uri": "/api/existing", "description": "Existing resource", "mime_type": "application/json"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Bulk method handles conflicts internally
    import_service.resource_service.register_resources_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.SKIP, imported_by="test_user")

    # Should skip the resource
    assert status.skipped_entities == 1


@pytest.mark.asyncio
async def test_resource_conflict_update_success(import_service, mock_db):
    """Test resource UPDATE conflict strategy success."""
    resource_data = {"name": "update_resource", "uri": "/api/update", "description": "Updated resource", "mime_type": "application/json"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Bulk method handles updates internally
    import_service.resource_service.register_resources_bulk.return_value = {
        "created": 0, "updated": 1, "skipped": 0, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.UPDATE, imported_by="test_user")

    # Should update the resource
    assert status.updated_entities == 1


@pytest.mark.asyncio
async def test_resource_conflict_rename_strategy(import_service, mock_db):
    """Test resource RENAME conflict strategy."""
    resource_data = {"name": "conflict_resource", "uri": "/api/conflict", "description": "Conflict resource", "mime_type": "application/json"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Bulk method handles rename strategy internally
    import_service.resource_service.register_resources_bulk.return_value = {
        "created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.RENAME, imported_by="test_user")

    # Should create the renamed resource
    assert status.created_entities == 1


@pytest.mark.asyncio
async def test_resource_conflict_fail_strategy(import_service, mock_db):
    """Test resource FAIL conflict strategy."""
    resource_data = {"name": "fail_resource", "uri": "/api/fail", "description": "Fail resource", "mime_type": "application/json"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"resources": [resource_data]}, "metadata": {"entity_counts": {"resources": 1}}}

    # Bulk method handles fail strategy internally
    import_service.resource_service.register_resources_bulk.return_value = {
        "created": 0, "updated": 0, "skipped": 0, "failed": 1,
        "errors": ["Resource URI conflict: /api/fail"]
    }

    status = await import_service.import_configuration(db=mock_db, import_data=import_data, conflict_strategy=ConflictStrategy.FAIL, imported_by="test_user")

    # Should fail the resource
    assert status.failed_entities == 1
    assert len(status.errors) > 0


@pytest.mark.asyncio
async def test_root_dry_run_processing(import_service, mock_db):
    """Test root dry-run processing."""
    root_data = {"uri": "file:///test", "name": "Test Root"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"roots": [root_data]}, "metadata": {"entity_counts": {"roots": 1}}}

    # Mock flush for dry run (even though it won't be called)
    mock_db.flush.return_value = None

    # Execute dry-run import
    status = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        dry_run=True,
        imported_by="test_user",
    )

    # Should add dry run warning and not call service
    assert any("Would import root: file:///test" in warning for warning in status.warnings)
    import_service.root_service.add_root.assert_not_called()


@pytest.mark.asyncio
async def test_root_conflict_skip_strategy(import_service, mock_db):
    """Test root SKIP conflict strategy."""
    root_data = {"uri": "file:///existing", "name": "Existing Root"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"roots": [root_data]}, "metadata": {"entity_counts": {"roots": 1}}}

    # Setup conflict
    import_service.root_service.add_root.side_effect = Exception("Root already exists")
    mock_db.flush.return_value = None  # Mock flush method

    status = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        conflict_strategy=ConflictStrategy.SKIP,
        imported_by="test_user",
    )

    # Should skip the root and add warning
    assert status.skipped_entities == 1
    assert any("Skipped existing root: file:///existing" in warning for warning in status.warnings)


@pytest.mark.asyncio
async def test_root_conflict_fail_strategy(import_service, mock_db):
    """Test root FAIL conflict strategy."""
    root_data = {"uri": "file:///fail", "name": "Fail Root"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"roots": [root_data]}, "metadata": {"entity_counts": {"roots": 1}}}

    # Setup conflict
    import_service.root_service.add_root.side_effect = Exception("Root already exists")
    mock_db.flush.return_value = None  # Mock flush method

    status = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        conflict_strategy=ConflictStrategy.FAIL,
        imported_by="test_user",
    )

    # Should fail the root
    assert status.failed_entities == 1
    assert len(status.errors) > 0


@pytest.mark.asyncio
async def test_root_conflict_update_or_rename_strategy(import_service, mock_db):
    """Test root UPDATE/RENAME conflict strategy (both should raise ImportError)."""
    root_data = {"uri": "file:///conflict", "name": "Conflict Root"}

    import_data = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"roots": [root_data]}, "metadata": {"entity_counts": {"roots": 1}}}

    # Setup conflict
    import_service.root_service.add_root.side_effect = Exception("Root already exists")
    mock_db.flush.return_value = None  # Mock flush method

    # Test UPDATE strategy
    status_update = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        conflict_strategy=ConflictStrategy.UPDATE,
        imported_by="test_user",
    )

    # Should fail the root (UPDATE not supported for roots)
    assert status_update.failed_entities == 1
    assert len(status_update.errors) > 0

    # Reset mock for RENAME test
    import_service.root_service.add_root.side_effect = Exception("Root already exists")

    # Test RENAME strategy
    status_rename = await import_service.import_configuration(
        db=mock_db,  # Use mock_db instead of None
        import_data=import_data,
        conflict_strategy=ConflictStrategy.RENAME,
        imported_by="test_user",
    )

    # Should fail the root (RENAME not supported for roots)
    assert status_rename.failed_entities == 1
    assert len(status_rename.errors) > 0


@pytest.mark.asyncio
async def test_gateway_auth_conversion_basic(import_service):
    """Test gateway conversion with basic auth."""
    # Standard
    import base64

    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Create basic auth data
    basic_auth = {"Authorization": "Basic " + base64.b64encode(b"username:password").decode("utf-8")}
    encrypted_auth = encode_auth(basic_auth)

    gateway_data = {"name": "basic_gateway", "url": "https://example.com", "auth_type": "basic", "auth_value": encrypted_auth}

    gateway_create = import_service._convert_to_gateway_create(gateway_data)
    assert gateway_create.name == "basic_gateway"
    assert gateway_create.auth_type == "basic"
    assert gateway_create.auth_username == "username"
    assert gateway_create.auth_password == "password"


@pytest.mark.asyncio
async def test_gateway_auth_conversion_bearer(import_service):
    """Test gateway conversion with bearer auth."""
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Create bearer auth data
    bearer_auth = {"Authorization": "Bearer test_token_123"}
    encrypted_auth = encode_auth(bearer_auth)

    gateway_data = {"name": "bearer_gateway", "url": "https://example.com", "auth_type": "bearer", "auth_value": encrypted_auth}

    gateway_create = import_service._convert_to_gateway_create(gateway_data)
    assert gateway_create.name == "bearer_gateway"
    assert gateway_create.auth_type == "bearer"
    assert gateway_create.auth_token == "test_token_123"


@pytest.mark.asyncio
async def test_gateway_auth_conversion_authheaders_single(import_service):
    """Test gateway conversion with single custom auth header."""
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Create auth headers data (single header)
    headers_auth = {"X-API-Key": "api_key_value"}
    encrypted_auth = encode_auth(headers_auth)

    gateway_data = {"name": "headers_gateway", "url": "https://example.com", "auth_type": "authheaders", "auth_value": encrypted_auth}

    gateway_create = import_service._convert_to_gateway_create(gateway_data)
    assert gateway_create.name == "headers_gateway"
    assert gateway_create.auth_type == "authheaders"
    assert gateway_create.auth_header_key == "X-API-Key"
    assert gateway_create.auth_header_value == "api_key_value"


@pytest.mark.asyncio
async def test_gateway_auth_conversion_authheaders_multiple(import_service):
    """Test gateway conversion with multiple custom auth headers."""
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Create auth headers data (multiple headers)
    headers_auth = {"X-API-Key": "api_key_value", "X-Client-ID": "client_123"}
    encrypted_auth = encode_auth(headers_auth)

    gateway_data = {"name": "multi_headers_gateway", "url": "https://example.com", "auth_type": "authheaders", "auth_value": encrypted_auth}

    gateway_create = import_service._convert_to_gateway_create(gateway_data)
    assert gateway_create.name == "multi_headers_gateway"
    assert gateway_create.auth_type == "authheaders"
    assert hasattr(gateway_create, "auth_headers")
    # Should have multiple headers in the new format
    assert len(gateway_create.auth_headers) == 2


@pytest.mark.asyncio
async def test_gateway_auth_conversion_decode_error(import_service):
    """Test gateway conversion with invalid auth data."""
    gateway_data = {"name": "error_gateway", "url": "https://example.com", "auth_type": "basic", "auth_value": "invalid_encrypted_data"}

    # Should raise ValidationError because auth fields are missing after decode failure
    with pytest.raises(Exception):  # ValidationError or similar
        import_service._convert_to_gateway_create(gateway_data)


@pytest.mark.asyncio
async def test_gateway_update_auth_conversion(import_service):
    """Test gateway update conversion with auth data."""
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Test with bearer auth
    bearer_auth = {"Authorization": "Bearer update_token_456"}
    encrypted_auth = encode_auth(bearer_auth)

    gateway_data = {
        "name": "update_gateway",
        "url": "https://example.com",
        "transport": "SSE",  # Required field
        "auth_type": "bearer",
        "auth_value": encrypted_auth,
    }

    gateway_update = import_service._convert_to_gateway_update(gateway_data)
    assert gateway_update.name == "update_gateway"
    assert gateway_update.auth_type == "bearer"
    assert gateway_update.auth_token == "update_token_456"


@pytest.mark.asyncio
async def test_gateway_update_auth_decode_error(import_service):
    """Test gateway update conversion with invalid auth data."""
    gateway_data = {
        "name": "update_error_gateway",
        "url": "https://example.com",
        "transport": "SSE",  # Required field
        "auth_type": "bearer",
        "auth_value": "invalid_encrypted_data_update",
    }

    # Should raise ValidationError because auth token is missing after decode failure
    with pytest.raises(Exception):  # ValidationError or similar
        import_service._convert_to_gateway_update(gateway_data)


@pytest.mark.asyncio
async def test_server_update_conversion(import_service, mock_db):
    """Test server update schema conversion."""
    server_data = {"name": "update_server", "description": "Updated server description", "tool_ids": ["tool1", "tool2", "tool3"], "tags": ["server", "update"]}

    # Mock the list_tools method to return empty list (no tools to resolve)
    import_service.tool_service.list_tools.return_value = ([], None)

    server_update = await import_service._convert_to_server_update(mock_db, server_data)
    assert server_update.name == "update_server"
    assert server_update.description == "Updated server description"
    assert server_update.associated_tools is None  # None because no tools found to resolve
    assert server_update.tags == [{'id':'server','label':'server'}, {'id':'update','label':'update'}]


@pytest.mark.asyncio
async def test_prompt_update_conversion_with_schema(import_service):
    """Test prompt update conversion with input schema."""
    prompt_data = {
        "name": "update_prompt",
        "template": "Updated template: {{name}} {{value}}",
        "description": "Updated prompt description",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Name parameter"}, "value": {"type": "number", "description": "Value parameter"}},
            "required": ["name"],
        },
        "tags": ["prompt", "update"],
    }

    prompt_update = import_service._convert_to_prompt_update(prompt_data)
    assert prompt_update.name == "update_prompt"
    assert prompt_update.template == "Updated template: {{name}} {{value}}"
    assert prompt_update.description == "Updated prompt description"
    assert prompt_update.arguments is not None
    assert len(prompt_update.arguments) == 2
    assert prompt_update.arguments[0].name == "name"
    assert prompt_update.arguments[0].required == True
    assert prompt_update.arguments[1].name == "value"
    assert prompt_update.arguments[1].required == False
    assert prompt_update.tags == [{'id':'prompt','label':'prompt'}, {'id':'update','label':'update'}]


@pytest.mark.asyncio
async def test_prompt_update_conversion_no_schema(import_service):
    """Test prompt update conversion without input schema."""
    prompt_data = {"name": "simple_prompt", "template": "Simple template", "description": "Simple prompt", "tags": ["simple"]}

    prompt_update = import_service._convert_to_prompt_update(prompt_data)
    assert prompt_update.name == "simple_prompt"
    assert prompt_update.template == "Simple template"
    assert prompt_update.description == "Simple prompt"
    assert prompt_update.arguments is None  # No arguments when no schema
    assert prompt_update.tags == [{'id':'simple','label':'simple'}]


@pytest.mark.asyncio
async def test_resource_update_conversion(import_service):
    """Test resource update schema conversion."""
    resource_data = {"name": "update_resource", "description": "Updated resource description", "mime_type": "application/xml", "content": "<xml>updated content</xml>", "tags": ["resource", "xml"]}

    resource_update = import_service._convert_to_resource_update(resource_data)
    assert resource_update.name == "update_resource"
    assert resource_update.description == "Updated resource description"
    assert resource_update.mime_type == "application/xml"
    assert resource_update.content == "<xml>updated content</xml>"
    assert resource_update.tags == [{'id':'resource','label':'resource'}, {'id':'xml','label':'xml'}]


@pytest.mark.asyncio
async def test_gateway_update_auth_conversion_basic_and_headers(import_service):
    """Test gateway update conversion with basic auth and custom headers."""
    # Standard
    import base64

    # First-Party
    from mcpgateway.utils.services_auth import encode_auth

    # Test basic auth in gateway update
    basic_auth = {"Authorization": "Basic " + base64.b64encode(b"user:pass").decode("utf-8")}
    encrypted_basic = encode_auth(basic_auth)

    basic_data = {"name": "basic_update_gateway", "url": "https://example.com", "transport": "SSE", "auth_type": "basic", "auth_value": encrypted_basic}

    basic_update = import_service._convert_to_gateway_update(basic_data)
    assert basic_update.auth_type == "basic"
    assert basic_update.auth_username == "user"
    assert basic_update.auth_password == "pass"

    # Test authheaders with single header in gateway update
    single_header_auth = {"X-API-Key": "single_key_value"}
    encrypted_single = encode_auth(single_header_auth)

    single_header_data = {"name": "single_header_gateway", "url": "https://example.com", "transport": "SSE", "auth_type": "authheaders", "auth_value": encrypted_single}

    single_update = import_service._convert_to_gateway_update(single_header_data)
    assert single_update.auth_type == "authheaders"
    assert single_update.auth_header_key == "X-API-Key"
    assert single_update.auth_header_value == "single_key_value"

    # Test authheaders with multiple headers in gateway update
    multi_headers_auth = {"X-API-Key": "key_value", "X-Client-ID": "client_value"}
    encrypted_multi = encode_auth(multi_headers_auth)

    multi_header_data = {"name": "multi_header_gateway", "url": "https://example.com", "transport": "SSE", "auth_type": "authheaders", "auth_value": encrypted_multi}

    multi_update = import_service._convert_to_gateway_update(multi_header_data)
    assert multi_update.auth_type == "authheaders"
    assert hasattr(multi_update, "auth_headers")
    assert len(multi_update.auth_headers) == 2



# ============================================================================
# Bulk Registration Tests (from test_bulk_registration.py)
# ============================================================================


def make_session():
    """Create an in-memory SQLite session for isolated tests."""
    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # First-Party
    from mcpgateway.db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


@pytest.mark.asyncio
async def test_register_tools_bulk_creates_and_returns_counts():
    """Test bulk tool registration creates tools and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Tool as DbTool
    from mcpgateway.services.tool_service import ToolService

    db = make_session()
    service = ToolService()
    service._notify_tool_added = AsyncMock()

    tools = [ToolCreate(name=f"tool{i}", url="http://example.com", integration_type="REST") for i in range(10)]

    result = await service.register_tools_bulk(db=db, tools=tools, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["created"] == 10
    # verify DB contains the created tools
    rows = db.execute(select(DbTool)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_tools_bulk_conflict_skip():
    """Test bulk tool registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Tool as DbTool
    from mcpgateway.services.tool_service import ToolService

    db = make_session()
    service = ToolService()
    service._notify_tool_added = AsyncMock()

    # Pre-create one tool
    first = ToolCreate(name="dup", url="http://a", integration_type="REST")
    await service.register_tool(db, first)

    # Bulk with a duplicate name should be skipped
    tools = [ToolCreate(name="dup", url="http://b", integration_type="REST"), ToolCreate(name="new", url="http://c", integration_type="REST")]
    result = await service.register_tools_bulk(db=db, tools=tools, created_by="tester", created_via="test", conflict_strategy="skip")

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbTool)).scalars().all()
    # Two or more tools expected (original + new)
    assert any(t.original_name == "dup" for t in rows)
    assert any(t.original_name == "new" for t in rows)



@pytest.mark.asyncio
async def test_register_prompts_bulk_creates_and_returns_counts():
    """Test bulk prompt registration creates prompts and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Prompt as DbPrompt
    from mcpgateway.services.prompt_service import PromptService
    from mcpgateway.schemas import PromptCreate

    db = make_session()
    service = PromptService()
    service._notify_prompt_added = AsyncMock()

    prompts = [
        PromptCreate(
            name=f"prompt{i}",
            template=f"Hello {{{{name{i}}}}}",
            description=f"Test prompt {i}"
        ) for i in range(10)
    ]

    result = await service.register_prompts_bulk(
        db=db,
        prompts=prompts,
        created_by="tester",
        created_via="test",
        conflict_strategy="skip"
    )

    assert result["created"] == 10
    # verify DB contains the created prompts
    rows = db.execute(select(DbPrompt)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_prompts_bulk_conflict_skip():
    """Test bulk prompt registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Prompt as DbPrompt
    from mcpgateway.services.prompt_service import PromptService
    from mcpgateway.schemas import PromptCreate

    db = make_session()
    service = PromptService()
    service._notify_prompt_added = AsyncMock()

    # Pre-create one prompt
    first = PromptCreate(name="dup_prompt", template="Hello {{name}}", description="Duplicate prompt")
    await service.register_prompt(db, first)

    # Bulk with a duplicate name should be skipped
    prompts = [
        PromptCreate(name="dup_prompt", template="Updated {{name}}", description="Duplicate prompt updated"),
        PromptCreate(name="new_prompt", template="New {{user}}", description="New prompt")
    ]
    result = await service.register_prompts_bulk(
        db=db,
        prompts=prompts,
        created_by="tester",
        created_via="test",
        conflict_strategy="skip"
    )

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbPrompt)).scalars().all()
    # Two or more prompts expected (original + new)
    assert any(p.name == "dup_prompt" for p in rows)
    assert any(p.name == "new_prompt" for p in rows)


@pytest.mark.asyncio
async def test_register_resources_bulk_creates_and_returns_counts():
    """Test bulk resource registration creates resources and returns correct counts."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Resource as DbResource
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.schemas import ResourceCreate

    db = make_session()
    service = ResourceService()
    service._notify_resource_added = AsyncMock()

    resources = [
        ResourceCreate(
            name=f"resource{i}",
            uri=f"file:///resource{i}.txt",
            description=f"Test resource {i}",
            mime_type="text/plain",
            content=f"Content for resource {i}"
        ) for i in range(10)
    ]

    result = await service.register_resources_bulk(
        db=db,
        resources=resources,
        created_by="tester",
        created_via="test",
        conflict_strategy="skip"
    )

    assert result["created"] == 10
    # verify DB contains the created resources
    rows = db.execute(select(DbResource)).scalars().all()
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_register_resources_bulk_conflict_skip():
    """Test bulk resource registration with skip conflict strategy."""
    # Third-Party
    from sqlalchemy import select

    # First-Party
    from mcpgateway.db import Resource as DbResource
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.schemas import ResourceCreate

    db = make_session()
    service = ResourceService()
    service._notify_resource_added = AsyncMock()

    # Pre-create one resource
    first = ResourceCreate(
        name="dup_resource",
        uri="file:///duplicate.txt",
        description="Duplicate resource",
        mime_type="text/plain",
        content="Original content"
    )
    await service.register_resource(db, first)

    # Bulk with a duplicate URI should be skipped
    resources = [
        ResourceCreate(
            name="dup_resource_updated",
            uri="file:///duplicate.txt",
            description="Duplicate resource updated",
            mime_type="text/plain",
            content="Updated content"
        ),
        ResourceCreate(
            name="new_resource",
            uri="file:///new.txt",
            description="New resource",
            mime_type="text/plain",
            content="New content"
        )
    ]
    result = await service.register_resources_bulk(
        db=db,
        resources=resources,
        created_by="tester",
        created_via="test",
        conflict_strategy="skip"
    )

    assert result["skipped"] >= 1
    assert result["created"] >= 1
    rows = db.execute(select(DbResource)).scalars().all()
    # Two or more resources expected (original + new)
    assert any(r.uri == "file:///duplicate.txt" for r in rows)
    assert any(r.uri == "file:///new.txt" for r in rows)
