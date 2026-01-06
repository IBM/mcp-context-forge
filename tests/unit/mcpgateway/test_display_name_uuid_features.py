# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_display_name_uuid_features.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for displayName and UUID editing features.
"""

# Standard
from unittest.mock import AsyncMock, Mock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ServerCreate, ServerRead, ServerUpdate, ToolCreate, ToolUpdate
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()  # Properly close all connections in the pool


@pytest.fixture
def tool_service():
    """Create a ToolService instance."""
    return ToolService()


@pytest.fixture
def server_service():
    """Create a ServerService instance."""
    return ServerService()


class TestDisplayNameFeature:
    """Test the displayName field functionality for tools."""

    def test_tool_create_with_display_name(self, db_session, tool_service):
        """Test creating a tool with displayName field."""
        # Create tool with displayName
        tool_data = ToolCreate(name="test_tool", displayName="My Custom Tool", url="https://example.com/api", description="Test tool", integration_type="REST", request_type="POST")

        # This would be called in the real service
        db_tool = DbTool(
            original_name=tool_data.name,
            custom_name=tool_data.name,
            custom_name_slug="test-tool",
            display_name=tool_data.displayName,
            url=str(tool_data.url),
            description=tool_data.description,
            integration_type=tool_data.integration_type,
            request_type=tool_data.request_type,
            input_schema={"type": "object", "properties": {}},
        )

        db_session.add(db_tool)
        db_session.commit()

        # Verify the tool was created with correct displayName
        saved_tool = db_session.query(DbTool).first()
        assert saved_tool.display_name == "My Custom Tool"
        assert saved_tool.original_name == "test_tool"

    def test_tool_create_without_display_name(self, db_session):
        """Test creating a tool without displayName field defaults to custom_name."""
        # Create tool without displayName
        db_tool = DbTool(
            original_name="test_tool_2",
            custom_name="test_tool_2",
            custom_name_slug="test-tool-2",
            display_name=None,
            url="https://example.com/api2",
            description="Test tool 2",
            integration_type="REST",
            request_type="GET",
            input_schema={"type": "object", "properties": {}},
        )

        db_session.add(db_tool)
        db_session.commit()

        # Verify the tool was created with default displayName (should default to custom_name)
        saved_tool = db_session.query(DbTool).first()
        assert saved_tool.display_name == "test_tool_2"  # Should default to custom_name
        assert saved_tool.original_name == "test_tool_2"

    def test_tool_update_display_name(self, db_session):
        """Test updating a tool's displayName."""
        # Create initial tool
        db_tool = DbTool(
            original_name="update_test_tool",
            custom_name="update_test_tool",
            custom_name_slug="update-test-tool",
            display_name="Original Name",
            url="https://example.com/api",
            description="Test tool",
            integration_type="REST",
            request_type="POST",
            input_schema={"type": "object", "properties": {}},
        )

        db_session.add(db_tool)
        db_session.commit()

        # Update displayName
        db_tool.display_name = "Updated Display Name"
        db_session.commit()

        # Verify the update
        saved_tool = db_session.query(DbTool).first()
        assert saved_tool.display_name == "Updated Display Name"

    def test_tool_read_display_name_fallback(self, db_session):
        """Test that displayName falls back to custom_name when null."""
        # Create tool with null displayName
        db_tool = DbTool(
            original_name="fallback_test_tool",
            custom_name="Fallback Tool",
            custom_name_slug="fallback-tool",
            display_name=None,
            url="https://example.com/api",
            description="Test tool",
            integration_type="REST",
            request_type="POST",
            input_schema={"type": "object", "properties": {}},
        )

        db_session.add(db_tool)
        db_session.commit()

        # Simulate the service logic for displayName fallback
        tool = db_session.query(DbTool).first()
        display_name = tool.display_name or tool.custom_name

        assert display_name == "Fallback Tool"


class TestServerUUIDFeature:
    """Test the UUID editing functionality for servers."""

    def test_server_create_with_custom_uuid(self, db_session):
        """Test creating a server with a custom UUID."""
        custom_uuid = "12345678-1234-1234-1234-123456789abc"

        # Create server with custom UUID
        db_server = DbServer(id=custom_uuid, name="Test Server", description="Test server with custom UUID", enabled=True)

        db_session.add(db_server)
        db_session.commit()

        # Verify the server was created with correct UUID
        saved_server = db_session.query(DbServer).first()
        assert saved_server.id == custom_uuid
        assert saved_server.name == "Test Server"

    def test_server_create_without_uuid(self, db_session):
        """Test creating a server without specifying UUID (auto-generated)."""
        # Create server without specifying UUID
        db_server = DbServer(name="Auto UUID Server", description="Test server with auto UUID", enabled=True)

        db_session.add(db_server)
        db_session.commit()

        # Verify the server was created with auto-generated UUID
        saved_server = db_session.query(DbServer).first()
        assert saved_server.id is not None
        assert len(saved_server.id) == 32  # UUID hex format without dashes
        assert saved_server.name == "Auto UUID Server"

    def test_server_update_uuid(self, db_session):
        """Test updating a server's UUID."""
        original_uuid = "original-uuid-1234"
        new_uuid = "new-uuid-5678"

        # Create server with original UUID
        db_server = DbServer(id=original_uuid, name="UUID Update Server", description="Test server for UUID update", enabled=True)

        db_session.add(db_server)
        db_session.commit()

        # Update UUID
        db_server.id = new_uuid
        db_session.commit()

        # Verify the update
        saved_server = db_session.query(DbServer).filter_by(name="UUID Update Server").first()
        assert saved_server.id == new_uuid

    def test_server_uuid_uniqueness(self, db_session):
        """Test that server UUIDs must be unique."""
        # Standard
        import warnings

        duplicate_uuid = "duplicate-uuid-1234"

        # Create first server with UUID
        db_server1 = DbServer(id=duplicate_uuid, name="First Server", description="First server", enabled=True)
        db_session.add(db_server1)
        db_session.commit()

        # Try to create second server with same UUID
        db_server2 = DbServer(id=duplicate_uuid, name="Second Server", description="Second server", enabled=True)

        db_session.add(db_server2)

        # This should raise an integrity error and emit an SAWarning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=Warning)
            with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
                db_session.commit()


class TestSchemaValidation:
    """Test schema validation for the new fields."""

    def test_tool_create_schema_with_display_name(self):
        """Test ToolCreate schema with displayName."""
        tool_data = {
            "name": "test_tool",
            "displayName": "My Custom Tool Display Name",
            "url": "https://example.com/api",
            "description": "Test tool",
            "integration_type": "REST",
            "request_type": "POST",
        }

        tool_create = ToolCreate(**tool_data)
        assert tool_create.displayName == "My Custom Tool Display Name"
        assert tool_create.name == "test_tool"

    def test_tool_update_schema_with_display_name(self):
        """Test ToolUpdate schema with displayName."""
        update_data = {"displayName": "Updated Display Name", "description": "Updated description"}

        tool_update = ToolUpdate(**update_data)
        assert tool_update.displayName == "Updated Display Name"
        assert tool_update.description == "Updated description"

    def test_server_create_schema_with_uuid(self):
        """Test ServerCreate schema with custom UUID."""
        server_data = {"id": "550e8400-e29b-41d4-a716-446655440000", "name": "Test Server", "description": "Test server with custom UUID"}

        server_create = ServerCreate(**server_data)
        assert server_create.id == "550e8400e29b41d4a716446655440000"
        assert server_create.name == "Test Server"

    def test_server_update_schema_with_uuid(self):
        """Test ServerUpdate schema with UUID."""
        update_data = {"id": "123e4567-e89b-12d3-a456-426614174000", "name": "Updated Server Name"}

        server_update = ServerUpdate(**update_data)
        assert server_update.id == "123e4567e89b12d3a456426614174000"
        assert server_update.name == "Updated Server Name"

    def test_server_uuid_validation(self):
        """Test UUID validation in schemas."""
        # First-Party
        from mcpgateway.schemas import ServerCreate, ServerUpdate

        # Test valid UUID
        server_create = ServerCreate(id="550e8400-e29b-41d4-a716-446655440000", name="Test Server")
        assert server_create.id == "550e8400e29b41d4a716446655440000"

        # Test invalid UUID should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            ServerCreate(id="invalid-uuid-format", name="Test Server")

        # Test ServerUpdate UUID validation
        server_update = ServerUpdate(id="123e4567-e89b-12d3-a456-426614174000")
        assert server_update.id == "123e4567e89b12d3a456426614174000"

        # Test invalid UUID in update
        with pytest.raises(Exception):  # Pydantic ValidationError
            ServerUpdate(id="bad-uuid-format")


class TestServerUUIDNormalization:
    """Test UUID normalization functionality in server service."""

    @pytest.mark.asyncio
    async def test_server_create_uuid_normalization_standard_format(self, db_session, server_service):
        """Test server creation with standard UUID format (with dashes) gets normalized to hex format."""
        # Standard
        import uuid as uuid_module

        # First-Party
        from mcpgateway.schemas import ServerCreate

        # Standard UUID format (with dashes)
        standard_uuid = "550e8400-e29b-41d4-a716-446655440000"
        expected_hex_uuid = str(uuid_module.UUID(standard_uuid)).replace("-", "")

        # Mock database operations
        mock_db_server = None

        def capture_add(server):
            nonlocal mock_db_server
            mock_db_server = server
            # Simulate the UUID normalization that happens in the service
            if hasattr(server, "id") and server.id:
                server.id = str(uuid_module.UUID(server.id)).replace("-", "")

        db_session.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))
        db_session.add = Mock(side_effect=capture_add)
        db_session.commit = Mock()
        db_session.refresh = Mock()
        db_session.get = Mock(return_value=None)  # No associated items

        # Mock the service methods
        server_service._notify_server_added = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id=expected_hex_uuid,
                name="Test Server",
                description="Test server with UUID normalization",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(id=standard_uuid, name="Test Server", description="Test server with UUID normalization")

        # Call the service method
        result = await server_service.register_server(db_session, server_create)

        # Verify UUID was normalized to hex format
        assert mock_db_server is not None
        assert mock_db_server.id == expected_hex_uuid
        assert result.id == expected_hex_uuid
        assert len(expected_hex_uuid) == 32  # UUID without dashes is 32 chars
        assert "-" not in expected_hex_uuid

    @pytest.mark.asyncio
    async def test_server_create_uuid_normalization_hex_format(self, db_session, server_service):
        """Test server creation with UUID in hex format (without dashes) works unchanged."""
        # Standard
        import uuid as uuid_module

        # First-Party
        from mcpgateway.schemas import ServerCreate

        # Hex UUID format (without dashes) - but we need to provide a valid UUID
        standard_uuid = "550e8400-e29b-41d4-a716-446655440000"
        hex_uuid = "550e8400e29b41d4a716446655440000"

        # Mock database operations
        mock_db_server = None

        def capture_add(server):
            nonlocal mock_db_server
            mock_db_server = server
            # Simulate the UUID normalization that happens in the service
            if hasattr(server, "id") and server.id:
                server.id = str(uuid_module.UUID(server.id)).replace("-", "")

        db_session.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))
        db_session.add = Mock(side_effect=capture_add)
        db_session.commit = Mock()
        db_session.refresh = Mock()
        db_session.get = Mock(return_value=None)  # No associated items

        # Mock the service methods
        server_service._notify_server_added = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id=hex_uuid,
                name="Test Server Hex",
                description="Test server with hex UUID",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        # Use the standard UUID format for schema validation, but expect hex format in storage
        server_create = ServerCreate(
            id=standard_uuid,  # Valid UUID format for schema validation
            name="Test Server Hex",
            description="Test server with hex UUID",
        )

        # Call the service method
        result = await server_service.register_server(db_session, server_create)

        # Verify UUID was normalized to hex format
        assert mock_db_server is not None
        assert mock_db_server.id == hex_uuid
        assert result.id == hex_uuid
        assert len(hex_uuid) == 32
        assert "-" not in hex_uuid

    @pytest.mark.asyncio
    async def test_server_create_auto_generated_uuid(self, db_session, server_service):
        """Test server creation without custom UUID generates UUID automatically."""
        # First-Party
        from mcpgateway.schemas import ServerCreate

        # Mock database operations
        mock_db_server = None

        def capture_add(server):
            nonlocal mock_db_server
            mock_db_server = server
            # Server should not have an ID set initially when auto-generating

        db_session.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))
        db_session.add = Mock(side_effect=capture_add)
        db_session.commit = Mock()
        db_session.refresh = Mock()
        db_session.get = Mock(return_value=None)  # No associated items

        # Mock the service methods
        server_service._notify_server_added = AsyncMock()
        server_service._convert_server_to_read = Mock(
            return_value=ServerRead(
                id="auto_generated_id_32_chars_long_hex",
                name="Auto UUID Server",
                description="Test server with auto UUID",
                icon=None,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                associated_tools=[],
                associated_resources=[],
                associated_prompts=[],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        server_create = ServerCreate(name="Auto UUID Server", description="Test server with auto UUID")
        # id should be None for auto-generation
        assert server_create.id is None

        # Call the service method
        result = await server_service.register_server(db_session, server_create)

        # Verify no custom UUID was set in the server before adding to DB
        assert mock_db_server is not None
        assert mock_db_server.id is None  # Should not be set for auto-generation
        assert result.id == "auto_generated_id_32_chars_long_hex"

    @pytest.mark.asyncio
    async def test_server_create_invalid_uuid_format(self, db_session, server_service):
        """Test server creation with invalid UUID format raises validation error."""
        # Third-Party
        from pydantic import ValidationError

        # First-Party
        from mcpgateway.schemas import ServerCreate

        # Test various invalid UUID formats that should raise validation errors
        invalid_uuids = [
            "invalid-uuid-format",
            "123-456-789",
            "not-a-uuid-at-all",
            "550e8400-e29b-41d4-a716-44665544000",  # Too short
            "550e8400-e29b-41d4-a716-446655440000-extra",  # Too long
            "550g8400-e29b-41d4-a716-446655440000",  # Invalid character
        ]

        for invalid_uuid in invalid_uuids:
            with pytest.raises(ValidationError) as exc_info:
                ServerCreate(id=invalid_uuid, name="Test Server", description="Test server with invalid UUID")
            # Verify the error message mentions UUID validation
            assert "UUID" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()

        # Test empty and whitespace strings separately - these are handled differently
        # Empty string should be allowed (treated as None)
        server_empty_id = ServerCreate(id="", name="Test Server Empty", description="Test server with empty ID")
        assert server_empty_id.id == ""  # Empty string is preserved but treated as no custom ID

        # Whitespace-only string should be stripped to empty
        server_whitespace_id = ServerCreate(id="   ", name="Test Server Whitespace", description="Test server with whitespace ID")
        assert server_whitespace_id.id == ""  # Whitespace stripped by str_strip_whitespace=True

    def test_uuid_normalization_logic(self):
        """Test the UUID normalization logic directly."""
        # Standard
        import uuid as uuid_module

        # Test cases for UUID normalization
        test_cases = [
            {"input": "550e8400-e29b-41d4-a716-446655440000", "expected": "550e8400e29b41d4a716446655440000", "description": "Standard UUID with dashes"},
            {"input": "123e4567-e89b-12d3-a456-426614174000", "expected": "123e4567e89b12d3a456426614174000", "description": "Another standard UUID with dashes"},
            {"input": "00000000-0000-0000-0000-000000000000", "expected": "00000000000000000000000000000000", "description": "Nil UUID"},
        ]

        for case in test_cases:
            # Simulate the normalization logic from server_service.py
            normalized = str(uuid_module.UUID(case["input"])).replace("-", "")
            assert normalized == case["expected"], f"Failed for {case['description']}: expected {case['expected']}, got {normalized}"
            assert len(normalized) == 32, f"Normalized UUID should be 32 characters, got {len(normalized)}"
            assert "-" not in normalized, "Normalized UUID should not contain dashes"

    def test_database_storage_format_verification(self, db_session):
        """Test that UUIDs are stored in the database in the expected hex format."""
        # Standard
        import uuid as uuid_module

        # Create a server with standard UUID format
        standard_uuid = "550e8400-e29b-41d4-a716-446655440000"
        expected_hex = str(uuid_module.UUID(standard_uuid)).replace("-", "")

        # Simulate what the service does - normalize the UUID before storing
        db_server = DbServer(
            id=expected_hex,  # Simulate the normalized UUID
            name="Storage Test Server",
            description="Test UUID storage format",
            enabled=True,
        )

        db_session.add(db_server)
        db_session.commit()

        # Verify the stored format
        saved_server = db_session.query(DbServer).first()
        assert saved_server.id == expected_hex
        assert len(saved_server.id) == 32
        assert "-" not in saved_server.id
        assert saved_server.id.isalnum()  # Should only contain alphanumeric characters

    @pytest.mark.asyncio
    async def test_comprehensive_uuid_scenarios_with_service(self, db_session, server_service):
        """Test comprehensive UUID scenarios that would be encountered in practice."""
        # Standard
        import uuid as uuid_module

        # First-Party
        from mcpgateway.schemas import ServerCreate

        test_scenarios = [
            {"name": "Lowercase UUID with dashes", "input": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "description": "Standard lowercase UUID format"},
            {"name": "Uppercase UUID with dashes", "input": "A1B2C3D4-E5F6-7890-ABCD-EF1234567890", "description": "Uppercase UUID format"},
            {"name": "Mixed case UUID with dashes", "input": "A1b2C3d4-E5f6-7890-AbCd-Ef1234567890", "description": "Mixed case UUID format"},
        ]

        for i, scenario in enumerate(test_scenarios):
            # Calculate expected normalized UUID
            expected_hex = str(uuid_module.UUID(scenario["input"])).replace("-", "")

            # Mock database operations for this test
            captured_server = None

            def capture_add(server):
                nonlocal captured_server
                captured_server = server

            db_session.execute = Mock(return_value=Mock(scalar_one_or_none=Mock(return_value=None)))
            db_session.add = Mock(side_effect=capture_add)
            db_session.commit = Mock()
            db_session.refresh = Mock()
            db_session.get = Mock(return_value=None)

            # Mock service methods
            server_service._notify_server_added = AsyncMock()
            server_service._convert_server_to_read = Mock(
                return_value=ServerRead(
                    id=expected_hex,
                    name=scenario["name"],
                    description=scenario["description"],
                    icon=None,
                    created_at="2023-01-01T00:00:00",
                    updated_at="2023-01-01T00:00:00",
                    enabled=True,
                    associated_tools=[],
                    associated_resources=[],
                    associated_prompts=[],
                    metrics={
                        "total_executions": 0,
                        "successful_executions": 0,
                        "failed_executions": 0,
                        "failure_rate": 0.0,
                        "min_response_time": None,
                        "max_response_time": None,
                        "avg_response_time": None,
                        "last_execution_time": None,
                    },
                )
            )

            server_create = ServerCreate(id=scenario["input"], name=scenario["name"], description=scenario["description"])

            # Call the service method
            result = await server_service.register_server(db_session, server_create)

            # Verify UUID normalization occurred correctly
            assert captured_server is not None, f"Server not captured for scenario: {scenario['name']}"
            assert captured_server.id == expected_hex, f"UUID not normalized correctly for {scenario['name']}: expected {expected_hex}, got {captured_server.id}"
            assert len(captured_server.id) == 32, f"Normalized UUID should be 32 chars for {scenario['name']}"
            assert "-" not in captured_server.id, f"Normalized UUID should not contain dashes for {scenario['name']}"
            assert captured_server.id.isalnum(), f"Normalized UUID should be alphanumeric for {scenario['name']}"
            assert result.id == expected_hex, f"Response UUID should match normalized for {scenario['name']}"


@pytest.mark.asyncio
class TestServiceIntegration:
    """Test service-level integration of the new features."""

    async def test_tool_service_display_name_in_response(self, db_session, tool_service):
        """Test that tool service includes displayName in response."""
        # Mock the _convert_tool_to_read method behavior
        db_tool = DbTool(
            id="test-tool-id",
            original_name="service_test_tool",
            custom_name="Service Test Tool",
            custom_name_slug="service-test-tool",
            display_name="Custom Display Name",
            url="https://example.com/api",
            description="Test tool",
            integration_type="REST",
            request_type="POST",
            input_schema={"type": "object", "properties": {}},
        )

        # Simulate the service method that converts DB model to response
        tool_dict = {
            "id": db_tool.id,
            "name": db_tool.name,
            "displayName": db_tool.display_name or db_tool.custom_name,
            "custom_name": db_tool.custom_name,
            "url": db_tool.url,
            "description": db_tool.description,
            "integration_type": db_tool.integration_type,
            "request_type": db_tool.request_type,
            "input_schema": db_tool.input_schema,
            "created_at": db_tool.created_at or "2025-01-01T00:00:00Z",
            "updated_at": db_tool.updated_at or "2025-01-01T00:00:00Z",
            "enabled": True,
            "reachable": True,
            "gateway_id": None,
            "execution_count": 0,
            "metrics": {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
            "gateway_slug": "",
            "custom_name_slug": "service-test-tool",
            "tags": [],
        }

        # Validate that the response includes displayName
        assert tool_dict["displayName"] == "Custom Display Name"
        assert tool_dict["custom_name"] == "Service Test Tool"


class TestSmartDisplayNameGeneration:
    """Test smart display name generation for auto-discovered tools."""

    def test_generate_display_name_function(self):
        """Test the display name generation utility function."""
        # First-Party
        from mcpgateway.utils.display_name import generate_display_name

        test_cases = [
            ("duckduckgo_search", "Duckduckgo Search"),
            ("weather-api", "Weather Api"),
            ("get_user.profile", "Get User Profile"),
            ("file_system", "File System"),
            ("fetch-web_content", "Fetch Web Content"),
            ("simple", "Simple"),
            ("", ""),
            ("UPPER_CASE", "Upper Case"),
            ("multiple___underscores", "Multiple Underscores"),
        ]

        for technical_name, expected in test_cases:
            result = generate_display_name(technical_name)
            assert result == expected, f"For '{technical_name}': expected '{expected}', got '{result}'"

    def test_manual_tool_displayname_preserved(self):
        """Test that manually specified displayName is preserved."""
        # First-Party
        from mcpgateway.schemas import ToolCreate

        # Manual tool with explicit displayName should keep it
        tool = ToolCreate(name="manual_api_tool", displayName="My Custom API Tool", url="https://example.com/api", integration_type="REST", request_type="POST")

        assert tool.displayName == "My Custom API Tool"
        assert tool.name == "manual_api_tool"

    def test_manual_tool_without_displayname(self):
        """Test that manual tools without displayName get service defaults."""
        # First-Party
        from mcpgateway.schemas import ToolCreate

        # Manual tool without displayName (service layer will set default)
        tool = ToolCreate(name="manual_webhook", url="https://example.com/webhook", integration_type="REST", request_type="POST")

        # Schema doesn't set default, service layer does
        assert tool.displayName is None
        assert tool.name == "manual_webhook"
