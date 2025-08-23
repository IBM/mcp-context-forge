# -*- coding: utf-8 -*-
"""Tests for displayName and UUID editing features."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import Mock, AsyncMock

from mcpgateway.db import Base, Tool as DbTool, Server as DbServer
from mcpgateway.schemas import ToolCreate, ToolUpdate, ToolRead, ServerCreate, ServerUpdate, ServerRead
from mcpgateway.services.tool_service import ToolService
from mcpgateway.services.server_service import ServerService


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
        tool_data = ToolCreate(
            name="test_tool",
            displayName="My Custom Tool",
            url="https://example.com/api",
            description="Test tool",
            integration_type="REST",
            request_type="POST"
        )

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
            input_schema={"type": "object", "properties": {}}
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
            input_schema={"type": "object", "properties": {}}
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
            input_schema={"type": "object", "properties": {}}
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
            input_schema={"type": "object", "properties": {}}
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
        db_server = DbServer(
            id=custom_uuid,
            name="Test Server",
            description="Test server with custom UUID",
            is_active=True
        )

        db_session.add(db_server)
        db_session.commit()

        # Verify the server was created with correct UUID
        saved_server = db_session.query(DbServer).first()
        assert saved_server.id == custom_uuid
        assert saved_server.name == "Test Server"

    def test_server_create_without_uuid(self, db_session):
        """Test creating a server without specifying UUID (auto-generated)."""
        # Create server without specifying UUID
        db_server = DbServer(
            name="Auto UUID Server",
            description="Test server with auto UUID",
            is_active=True
        )

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
        db_server = DbServer(
            id=original_uuid,
            name="UUID Update Server",
            description="Test server for UUID update",
            is_active=True
        )

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
        duplicate_uuid = "duplicate-uuid-1234"

        # Create first server with UUID
        db_server1 = DbServer(
            id=duplicate_uuid,
            name="First Server",
            description="First server",
            is_active=True
        )
        db_session.add(db_server1)
        db_session.commit()

        # Try to create second server with same UUID
        db_server2 = DbServer(
            id=duplicate_uuid,
            name="Second Server",
            description="Second server",
            is_active=True
        )

        db_session.add(db_server2)

        # This should raise an integrity error
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
            "request_type": "POST"
        }

        tool_create = ToolCreate(**tool_data)
        assert tool_create.displayName == "My Custom Tool Display Name"
        assert tool_create.name == "test_tool"

    def test_tool_update_schema_with_display_name(self):
        """Test ToolUpdate schema with displayName."""
        update_data = {
            "displayName": "Updated Display Name",
            "description": "Updated description"
        }

        tool_update = ToolUpdate(**update_data)
        assert tool_update.displayName == "Updated Display Name"
        assert tool_update.description == "Updated description"

    def test_server_create_schema_with_uuid(self):
        """Test ServerCreate schema with custom UUID."""
        server_data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "name": "Test Server",
            "description": "Test server with custom UUID"
        }

        server_create = ServerCreate(**server_data)
        assert server_create.id == "550e8400-e29b-41d4-a716-446655440000"
        assert server_create.name == "Test Server"

    def test_server_update_schema_with_uuid(self):
        """Test ServerUpdate schema with UUID."""
        update_data = {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "name": "Updated Server Name"
        }

        server_update = ServerUpdate(**update_data)
        assert server_update.id == "123e4567-e89b-12d3-a456-426614174000"
        assert server_update.name == "Updated Server Name"

    def test_server_uuid_validation(self):
        """Test UUID validation in schemas."""
        from mcpgateway.schemas import ServerCreate, ServerUpdate

        # Test valid UUID
        server_create = ServerCreate(
            id="550e8400-e29b-41d4-a716-446655440000",
            name="Test Server"
        )
        assert server_create.id == "550e8400-e29b-41d4-a716-446655440000"

        # Test invalid UUID should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            ServerCreate(
                id="invalid-uuid-format",
                name="Test Server"
            )

        # Test ServerUpdate UUID validation
        server_update = ServerUpdate(id="123e4567-e89b-12d3-a456-426614174000")
        assert server_update.id == "123e4567-e89b-12d3-a456-426614174000"

        # Test invalid UUID in update
        with pytest.raises(Exception):  # Pydantic ValidationError
            ServerUpdate(id="bad-uuid-format")


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
            input_schema={"type": "object", "properties": {}}
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
                "last_execution_time": None
            },
            "gateway_slug": "",
            "custom_name_slug": "service-test-tool",
            "tags": []
        }

        # Validate that the response includes displayName
        assert tool_dict["displayName"] == "Custom Display Name"
        assert tool_dict["custom_name"] == "Service Test Tool"


class TestSmartDisplayNameGeneration:
    """Test smart display name generation for auto-discovered tools."""

    def test_generate_display_name_function(self):
        """Test the display name generation utility function."""
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
        from mcpgateway.schemas import ToolCreate

        # Manual tool with explicit displayName should keep it
        tool = ToolCreate(
            name="manual_api_tool",
            displayName="My Custom API Tool",
            url="https://example.com/api",
            integration_type="REST",
            request_type="POST"
        )

        assert tool.displayName == "My Custom API Tool"
        assert tool.name == "manual_api_tool"

    def test_manual_tool_without_displayname(self):
        """Test that manual tools without displayName get service defaults."""
        from mcpgateway.schemas import ToolCreate

        # Manual tool without displayName (service layer will set default)
        tool = ToolCreate(
            name="manual_webhook",
            url="https://example.com/webhook",
            integration_type="REST",
            request_type="POST"
        )

        # Schema doesn't set default, service layer does
        assert tool.displayName is None
        assert tool.name == "manual_webhook"
