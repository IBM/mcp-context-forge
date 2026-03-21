# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_schemas.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the MCP types module.
This module contains tests for the various MCP protocol type definitions
defined in the models.py module.
"""

# Standard
from datetime import datetime, timedelta, timezone
import json
import os
from unittest.mock import Mock

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.common.models import (
    ClientCapabilities,
    CreateMessageResult,
    ImageContent,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ListResourceTemplatesResult,
    LogLevel,
    Message,
    ModelHint,
    ModelPreferences,
    PromptArgument,
    PromptReference,
    PromptResult,
    Resource,
    ResourceContent,
    ResourceReference,
    ResourceTemplate,
    Role,
    Root,
    SamplingMessage,
    ServerCapabilities,
    TextContent,
    Tool,
    ToolResult,
)
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.schemas import (
    AdminGatewayCreate,
    AdminToolCreate,
    EventMessage,
    ListFilters,
    ResourceCreate,
    ServerCreate,
    ServerMetrics,
    ServerRead,
    ServerUpdate,
    StatusToggleRequest,
    StatusToggleResponse,
    TeamCreateRequest,
    TeamUpdateRequest,
    ToolCreate,
    ToolUpdate,
)

PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


class TestMCPTypes:
    """Test suite for MCP protocol types."""

    def test_role_enum(self):
        """Test Role enum values."""
        assert Role.ASSISTANT == "assistant"
        assert Role.USER == "user"

    def test_log_level_enum(self):
        """Test LogLevel enum values."""
        assert LogLevel.DEBUG == "debug"
        assert LogLevel.INFO == "info"
        assert LogLevel.NOTICE == "notice"
        assert LogLevel.WARNING == "warning"
        assert LogLevel.ERROR == "error"
        assert LogLevel.CRITICAL == "critical"
        assert LogLevel.ALERT == "alert"
        assert LogLevel.EMERGENCY == "emergency"

    def test_text_content(self):
        """Test TextContent model."""
        content = TextContent(type="text", text="Hello, world!")
        assert content.type == "text"
        assert content.text == "Hello, world!"

        # Test serialization
        json_str = content.model_dump_json()
        loaded = json.loads(json_str)
        assert loaded["type"] == "text"
        assert loaded["text"] == "Hello, world!"

        # Test missing required field
        with pytest.raises(ValidationError):
            TextContent(type="text")

    def test_image_content(self):
        """Test ImageContent model."""
        # ImageContent now uses base64-encoded string per MCP spec
        import base64

        binary_data = b"binary_image_data"
        base64_data = base64.b64encode(binary_data).decode('utf-8')

        content = ImageContent(
            type="image",
            data=base64_data,
            mime_type="image/png",
        )
        assert content.type == "image"
        assert content.data == base64_data
        assert content.mime_type == "image/png"

        # Test validation errors
        with pytest.raises(ValidationError):
            ImageContent(type="image", data="data")  # Missing mime_type

    def test_resource_content(self):
        """Test ResourceContent model."""
        # Text resource
        text_resource = ResourceContent(
            type="resource",
            id="res1",
            uri="file:///example.txt",
            mime_type="text/plain",
            text="Example content",
        )
        assert text_resource.type == "resource"
        assert text_resource.uri == "file:///example.txt"
        assert text_resource.mime_type == "text/plain"
        assert text_resource.text == "Example content"
        assert text_resource.blob is None

        # Binary resource
        binary_resource = ResourceContent(
            type="resource",
            id="res2",
            uri="file:///example.bin",
            mime_type="application/octet-stream",
            blob=b"binary_data",
        )
        assert binary_resource.type == "resource"
        assert binary_resource.uri == "file:///example.bin"
        assert binary_resource.mime_type == "application/octet-stream"
        assert binary_resource.text is None
        assert binary_resource.blob == b"binary_data"

        # Minimal required fields
        minimal = ResourceContent(
            type="resource",
            id="res3",
            uri="file:///example",
        )
        assert minimal.type == "resource"
        assert minimal.uri == "file:///example"
        assert minimal.mime_type is None
        assert minimal.text is None
        assert minimal.blob is None

    def test_message(self):
        """Test Message model with different content types."""
        text_message = Message(
            role=Role.USER,
            content=TextContent(type="text", text="Hello, world!"),
        )
        assert text_message.role == Role.USER
        assert text_message.content.type == "text"
        assert text_message.content.text == "Hello, world!"

        # ImageContent now uses base64-encoded string per MCP spec
        import base64

        binary_data = b"binary_image_data"
        base64_data = base64.b64encode(binary_data).decode('utf-8')

        image_message = Message(
            role=Role.ASSISTANT,
            content=ImageContent(
                type="image",
                data=base64_data,
                mime_type="image/png",
            ),
        )
        assert image_message.role == Role.ASSISTANT
        assert image_message.content.type == "image"
        assert image_message.content.data == base64_data

    def test_prompt_argument(self):
        """Test PromptArgument model."""
        # Full argument
        arg = PromptArgument(
            name="language",
            description="Programming language",
            required=True,
        )
        assert arg.name == "language"
        assert arg.description == "Programming language"
        assert arg.required is True

        # Minimal argument
        minimal = PromptArgument(name="limit")
        assert minimal.name == "limit"
        assert minimal.description is None
        assert minimal.required is False

    def test_prompt_result(self):
        """Test PromptResult model."""
        result = PromptResult(
            messages=[
                Message(
                    role=Role.USER,
                    content=TextContent(type="text", text="Hello, world!"),
                ),
                Message(
                    role=Role.ASSISTANT,
                    content=TextContent(type="text", text="Hi there!"),
                ),
            ],
            description="Example prompt result",
        )
        assert len(result.messages) == 2
        assert result.messages[0].role == Role.USER
        assert result.messages[1].role == Role.ASSISTANT
        assert result.description == "Example prompt result"

        # Test with minimal fields
        minimal = PromptResult(
            messages=[
                Message(
                    role=Role.USER,
                    content=TextContent(type="text", text="Query"),
                ),
            ],
        )
        assert len(minimal.messages) == 1
        assert minimal.description is None

    def test_tool_result(self):
        """Test ToolResult model."""
        result = ToolResult(
            content=[
                TextContent(type="text", text="Result data"),
                ImageContent(
                    type="image",
                    data=b"image_data",
                    mime_type="image/jpeg",
                ),
            ],
            is_error=False,
        )
        assert len(result.content) == 2
        assert result.content[0].type == "text"
        assert result.content[1].type == "image"
        assert result.is_error is False

        # Test error result
        error_result = ToolResult(
            content=[TextContent(type="text", text="Error message")],
            is_error=True,
        )
        assert len(error_result.content) == 1
        assert error_result.is_error is True

    def test_resource(self):
        """Test Resource model."""
        resource = Resource(
            uri="file:///example.txt",
            name="Example Resource",
            description="An example resource",
            mime_type="text/plain",
            size=1024,
        )
        assert resource.uri == "file:///example.txt"
        assert resource.name == "Example Resource"
        assert resource.description == "An example resource"
        assert resource.mime_type == "text/plain"
        assert resource.size == 1024

        # Test minimal fields
        minimal = Resource(
            uri="file:///example.bin",
            name="Minimal Example",
        )
        assert minimal.uri == "file:///example.bin"
        assert minimal.name == "Minimal Example"
        assert minimal.description is None
        assert minimal.mime_type is None
        assert minimal.size is None

    def test_resource_template(self):
        """Test ResourceTemplate model."""
        template = ResourceTemplate(
            uri_template="file:///data/{user}/{file}",
            name="User Data Template",
            description="Template for user data files",
            mime_type="application/octet-stream",
        )
        assert template.uri_template == "file:///data/{user}/{file}"
        assert template.name == "User Data Template"
        assert template.description == "Template for user data files"
        assert template.mime_type == "application/octet-stream"

        # Test minimal fields
        minimal = ResourceTemplate(
            uri_template="file:///logs/{date}.log",
            name="Log Template",
        )
        assert minimal.uri_template == "file:///logs/{date}.log"
        assert minimal.name == "Log Template"
        assert minimal.description is None
        assert minimal.mime_type is None

    def test_list_resource_templates_result(self):
        """Test ListResourceTemplatesResult model."""
        result = ListResourceTemplatesResult(
            _meta={"version": "1.0"},
            next_cursor="abc123",
            resource_templates=[
                ResourceTemplate(
                    uri_template="file:///data/{user}/{file}",
                    name="User Data Template",
                ),
                ResourceTemplate(
                    uri_template="file:///logs/{date}.log",
                    name="Log Template",
                ),
            ],
        )
        assert result.meta == {"version": "1.0"}
        assert result.next_cursor == "abc123"
        assert len(result.resource_templates) == 2
        assert result.resource_templates[0].name == "User Data Template"
        assert result.resource_templates[1].name == "Log Template"

        # Test minimal fields
        minimal = ListResourceTemplatesResult(
            resource_templates=[
                ResourceTemplate(
                    uri_template="file:///data/{file}",
                    name="Simple Template",
                ),
            ],
        )
        assert minimal.meta is None
        assert minimal.next_cursor is None
        assert len(minimal.resource_templates) == 1

    def test_root(self):
        """Test Root model."""
        root = Root(
            uri="file:///data",
            name="Data Directory",
        )
        assert root.uri == "file:///data"
        assert root.name == "Data Directory"

        # Test minimal fields
        minimal = Root(uri="file:///logs")
        assert minimal.uri == "file:///logs"
        assert minimal.name is None

    def test_implementation(self):
        """Test Implementation model."""
        impl = Implementation(name="Test Gateway", version="1.0.0")
        assert impl.name == "Test Gateway"
        assert impl.version == "1.0.0"

    def test_model_hint(self):
        """Test ModelHint model."""
        hint = ModelHint(name="gpt-4")
        assert hint.name == "gpt-4"

        # Test empty hint
        empty = ModelHint()
        assert empty.name is None

    def test_model_preferences(self):
        """Test ModelPreferences model."""
        prefs = ModelPreferences(
            cost_priority=0.8,
            speed_priority=0.5,
            intelligence_priority=0.2,
            hints=[ModelHint(name="claude-3")],
        )
        assert prefs.cost_priority == 0.8
        assert prefs.speed_priority == 0.5
        assert prefs.intelligence_priority == 0.2
        assert len(prefs.hints) == 1
        assert prefs.hints[0].name == "claude-3"

        # Test minimal fields
        minimal = ModelPreferences(
            cost_priority=0.5,
            speed_priority=0.5,
            intelligence_priority=0.5,
        )
        assert minimal.cost_priority == 0.5
        assert minimal.speed_priority == 0.5
        assert minimal.intelligence_priority == 0.5
        assert len(minimal.hints) == 0

        # Test validation (priorities must be between 0 and 1)
        with pytest.raises(ValidationError):
            ModelPreferences(
                cost_priority=1.5,  # Invalid: > 1
                speed_priority=0.5,
                intelligence_priority=0.5,
            )

    def test_client_capabilities(self):
        """Test ClientCapabilities model."""
        caps = ClientCapabilities(
            roots={"listChanged": True},
            sampling={"supports_temperature": True},
            experimental={"feature": {"enabled": True}},
        )
        assert caps.roots == {"listChanged": True}
        assert caps.sampling == {"supports_temperature": True}
        assert caps.experimental == {"feature": {"enabled": True}}

        # Test minimal fields
        minimal = ClientCapabilities()
        assert minimal.roots is None
        assert minimal.sampling is None
        assert minimal.experimental is None

    def test_server_capabilities(self):
        """Test ServerCapabilities model."""
        caps = ServerCapabilities(
            prompts={"listChanged": True},
            resources={"subscribe": True, "listChanged": True},
            tools={"listChanged": True},
            logging={"setLevel": True},
            experimental={"feature": {"enabled": True}},
        )
        assert caps.prompts == {"listChanged": True}
        assert caps.resources == {"subscribe": True, "listChanged": True}
        assert caps.tools == {"listChanged": True}
        assert caps.logging == {"setLevel": True}
        assert caps.experimental == {"feature": {"enabled": True}}

        # Test minimal fields
        minimal = ServerCapabilities()
        assert minimal.prompts is None
        assert minimal.resources is None
        assert minimal.tools is None
        assert minimal.logging is None
        assert minimal.experimental is None

    def test_initialize_request(self):
        """Test InitializeRequest model."""
        request = InitializeRequest(
            protocol_version=PROTOCOL_VERSION,
            capabilities=ClientCapabilities(roots={"listChanged": True}),
            client_info=Implementation(name="Test Client", version="1.0.0"),
        )
        assert request.protocol_version == PROTOCOL_VERSION
        assert request.capabilities.roots == {"listChanged": True}
        assert request.client_info.name == "Test Client"
        assert request.client_info.version == "1.0.0"

        # Test with field aliases
        dict_data = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": True}},
            "clientInfo": {"name": "Test Client", "version": "1.0.0"},
        }
        from_dict = InitializeRequest.model_validate(dict_data)
        assert from_dict.protocol_version == PROTOCOL_VERSION
        assert from_dict.capabilities.roots == {"listChanged": True}
        assert from_dict.client_info.name == "Test Client"

    def test_initialize_result(self):
        """Test InitializeResult model."""
        result = InitializeResult(
            protocol_version=PROTOCOL_VERSION,
            capabilities=ServerCapabilities(
                prompts={"listChanged": True},
                resources={"subscribe": True},
                tools={"listChanged": True},
            ),
            server_info=Implementation(name="Test Server", version="1.0.0"),
            instructions="Example instructions for the client.",
        )
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.capabilities.prompts == {"listChanged": True}
        assert result.capabilities.resources == {"subscribe": True}
        assert result.capabilities.tools == {"listChanged": True}
        assert result.server_info.name == "Test Server"
        assert result.server_info.version == "1.0.0"
        assert result.instructions == "Example instructions for the client."

        # Test with field aliases
        dict_data = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "prompts": {"listChanged": True},
                "resources": {"subscribe": True},
                "tools": {"listChanged": True},
            },
            "serverInfo": {"name": "Test Server", "version": "1.0.0"},
        }
        from_dict = InitializeResult.model_validate(dict_data)
        assert from_dict.protocol_version == PROTOCOL_VERSION
        assert from_dict.capabilities.prompts == {"listChanged": True}
        assert from_dict.server_info.name == "Test Server"
        assert from_dict.instructions is None

    def test_sampling_message(self):
        """Test SamplingMessage model."""
        message = SamplingMessage(
            role=Role.USER,
            content=TextContent(type="text", text="Sample text"),
        )
        assert message.role == Role.USER
        assert message.content.type == "text"
        assert message.content.text == "Sample text"

    def test_create_message_result(self):
        """Test CreateMessageResult model."""
        result = CreateMessageResult(
            content=TextContent(type="text", text="Generated response"),
            model="claude-3",
            role=Role.ASSISTANT,
            stop_reason="maxTokens",
        )
        assert result.content.type == "text"
        assert result.content.text == "Generated response"
        assert result.model == "claude-3"
        assert result.role == Role.ASSISTANT
        assert result.stop_reason == "maxTokens"

        # Test minimal fields
        minimal = CreateMessageResult(
            content=TextContent(type="text", text="Response"),
            model="gpt-4",
            role=Role.ASSISTANT,
        )
        assert minimal.content.text == "Response"
        assert minimal.model == "gpt-4"
        assert minimal.role == Role.ASSISTANT
        assert minimal.stop_reason is None

    def test_prompt_reference(self):
        """Test PromptReference model."""
        ref = PromptReference(type="ref/prompt", name="example-prompt")
        assert ref.type == "ref/prompt"
        assert ref.name == "example-prompt"

    def test_resource_reference(self):
        """Test ResourceReference model."""
        ref = ResourceReference(type="ref/resource", uri="file:///example.txt")
        assert ref.type == "ref/resource"
        assert ref.uri == "file:///example.txt"

    def test_tool(self):
        """Test Tool model."""
        tool = Tool(
            name="example-tool",
            url="http://localhost:8000/tool",
            description="An example tool",
            integration_type="MCP",
            request_type="SSE",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            auth_type="bearer",
            auth_token="example-token",
        )
        assert tool.name == "example-tool"
        assert str(tool.url) == "http://localhost:8000/tool"
        assert tool.description == "An example tool"
        assert tool.integration_type == "MCP"
        assert tool.request_type == "SSE"
        assert tool.headers == {"Content-Type": "application/json"}
        assert tool.input_schema == {"type": "object", "properties": {"query": {"type": "string"}}}
        assert tool.auth_type == "bearer"
        assert tool.auth_token == "example-token"

        # Test minimal fields
        minimal = Tool(
            name="minimal-tool",
            url="http://localhost:8000/minimal",
        )
        assert minimal.name == "minimal-tool"
        assert str(minimal.url) == "http://localhost:8000/minimal"
        assert minimal.description is None
        assert minimal.integration_type == "MCP"  # Default value
        assert minimal.request_type == "SSE"  # Default value
        assert minimal.headers == {}  # Default value
        assert minimal.input_schema == {"type": "object", "properties": {}}  # Default value
        assert minimal.auth_type is None
        assert minimal.auth_username is None
        assert minimal.auth_password is None
        assert minimal.auth_token is None


class TestEventAndAdminSchemas:
    """Test event and admin schemas."""

    def test_event_message(self):
        """Test EventMessage model."""
        now = datetime.now(timezone.utc)

        event = EventMessage(
            type="resource_updated",
            data={"uri": "/test/resource.txt", "content": "Updated content"},
            timestamp=now,
        )

        assert event.type == "resource_updated"
        assert event.data == {"uri": "/test/resource.txt", "content": "Updated content"}
        assert event.timestamp == now

        # Test with default timestamp
        default_event = EventMessage(
            type="tool_added",
            data={"name": "new-tool", "url": "http://example.com/tool"},
        )

        assert default_event.type == "tool_added"
        assert default_event.data == {"name": "new-tool", "url": "http://example.com/tool"}
        assert isinstance(default_event.timestamp, datetime)

    def test_admin_tool_create(self):
        """Test AdminToolCreate model."""
        tool = AdminToolCreate(
            name="admin-tool",
            url="http://example.com/admin-tool",
            description="Admin tool",
            integration_type="MCP",
            headers='{"Content-Type": "application/json"}',
            input_schema='{"type": "object", "properties": {"query": {"type": "string"}}}',
        )

        assert tool.name == "admin-tool"
        assert tool.url == "http://example.com/admin-tool"
        assert tool.description == "Admin tool"
        assert tool.integration_type == "MCP"

        # JSON string fields should be parsed into dictionaries
        assert isinstance(tool.headers, dict)
        assert tool.headers == {"Content-Type": "application/json"}
        assert isinstance(tool.input_schema, dict)
        assert tool.input_schema["type"] == "object"

        # Test with invalid JSON
        with pytest.raises(ValidationError):
            AdminToolCreate(
                name="invalid-tool",
                url="http://example.com/invalid",
                headers="invalid json",
            )

    def test_admin_gateway_create(self):
        """Test AdminGatewayCreate model."""
        gateway = AdminGatewayCreate(
            name="Admin Gateway",
            url="http://admin-gateway.example.com",
            description="Admin gateway instance",
        )

        assert gateway.name == "Admin Gateway"
        assert gateway.url == "http://admin-gateway.example.com"
        assert gateway.description == "Admin gateway instance"

        # Minimal gateway
        minimal = AdminGatewayCreate(
            name="Minimal Admin Gateway",
            url="http://minimal-admin.example.com",
        )

        assert minimal.name == "Minimal Admin Gateway"
        assert minimal.url == "http://minimal-admin.example.com"
        assert minimal.description is None


class TestServerSchemas:
    """Test server-related schemas."""

    def test_server_create(self):
        """Test ServerCreate model."""
        server = ServerCreate(
            name="Test Server",
            description="Test server instance",
            icon="http://example.com/server.png",
            associated_tools=["1", "2", "3"],
            associated_resources=["4", "5"],
            associated_prompts=["6"],
        )

        assert server.name == "Test Server"
        assert server.description == "Test server instance"
        assert server.icon == "http://example.com/server.png"
        assert server.associated_tools == ["1", "2", "3"]
        assert server.associated_resources == ["4", "5"]
        assert server.associated_prompts == ["6"]

        # Test with comma-separated strings for associations
        csv_server = ServerCreate(
            name="CSV Server",
            description="Server with comma-separated values",
            associated_tools="1,2,3",
            associated_resources="4,5",
            associated_prompts="6",
        )

        assert csv_server.name == "CSV Server"
        assert csv_server.associated_tools == ["1", "2", "3"]
        assert csv_server.associated_resources == ["4", "5"]
        assert csv_server.associated_prompts == ["6"]

        # Minimal server
        minimal = ServerCreate(
            name="Minimal Server",
        )

        assert minimal.name == "Minimal Server"
        assert minimal.description is None
        assert minimal.icon is None
        assert minimal.associated_tools is None
        assert minimal.associated_resources is None
        assert minimal.associated_prompts is None

    def test_server_update(self):
        """Test ServerUpdate model."""
        update = ServerUpdate(
            name="Updated Server",
            description="Updated description",
            icon="http://example.com/updated.png",
            associated_tools=["10", "11"],
            associated_resources=["12", "13"],
            associated_prompts=["14"],
        )

        assert update.name == "Updated Server"
        assert update.description == "Updated description"
        assert update.icon == "http://example.com/updated.png"
        assert update.associated_tools == ["10", "11"]
        assert update.associated_resources == ["12", "13"]
        assert update.associated_prompts == ["14"]

        # Test with comma-separated strings
        csv_update = ServerUpdate(
            associated_tools="10,11",
            associated_resources="12,13",
            associated_prompts="14",
        )

        assert csv_update.name is None
        assert csv_update.description is None
        assert csv_update.icon is None
        assert csv_update.associated_tools == ["10", "11"]
        assert csv_update.associated_resources == ["12", "13"]
        assert csv_update.associated_prompts == ["14"]

    def test_server_read(self):
        """Test ServerRead model."""
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        server = ServerRead(
            id="1",
            name="Test Server",
            description="Test server instance",
            icon="http://example.com/server.png",
            created_at=one_hour_ago,
            updated_at=now,
            enabled=True,
            associated_tools=["1", "2", "3"],
            associated_resources=["4", "5"],
            associated_prompts=["6"],
            metrics=ServerMetrics(
                total_executions=100,
                successful_executions=95,
                failed_executions=5,
                failure_rate=0.05,
                min_response_time=0.1,
                max_response_time=2.0,
                avg_response_time=0.5,
                last_execution_time=now,
            ),
        )

        assert server.id == "1"
        assert server.name == "Test Server"
        assert server.description == "Test server instance"
        assert server.icon == "http://example.com/server.png"
        assert server.created_at == one_hour_ago
        assert server.updated_at == now
        assert server.enabled is True
        assert server.associated_tools == ["1", "2", "3"]
        assert server.associated_resources == ["4", "5"]
        assert server.associated_prompts == ["6"]
        assert server.metrics.total_executions == 100
        assert server.metrics.successful_executions == 95

        # Test root validator for associated IDs
        server_with_objects = ServerRead(
            id="f1548803b0ff4bf7833b762b0a8c5c34",
            name="Object Server",
            description="Server with object associations",
            icon="http://example.com/object_server.png",
            created_at=one_hour_ago,
            updated_at=now,
            enabled=True,
            associated_tools=[Mock(id="10"), Mock(id="11")],
            associated_resources=[Mock(id="12")],
            associated_prompts=[Mock(id="13")],
            metrics=ServerMetrics(
                total_executions=10,
                successful_executions=10,
                failed_executions=0,
                failure_rate=0.0,
            ),
        )

        assert server_with_objects.associated_tools == ["10", "11"]
        assert server_with_objects.associated_resources == ["12"]
        assert server_with_objects.associated_prompts == ["13"]


class TestToggleAndListSchemas:
    """Test status toggle and list filter schemas."""

    def test_status_toggle_request(self):
        """Test StatusToggleRequest model."""
        request = StatusToggleRequest(activate=True)
        assert request.activate is True

        request_off = StatusToggleRequest(activate=False)
        assert request_off.activate is False

    def test_status_toggle_response(self):
        """Test StatusToggleResponse model."""
        response = StatusToggleResponse(
            id=1,
            name="Test Item",
            is_active=True,
            message="Item activated successfully",
        )

        assert response.id == 1
        assert response.name == "Test Item"
        assert response.is_active is True
        assert response.message == "Item activated successfully"

    def test_list_filters(self):
        """Test ListFilters model."""
        filters = ListFilters(include_inactive=True)
        assert filters.include_inactive is True

        # Test default value
        default_filters = ListFilters()
        assert default_filters.include_inactive is False


DANGEROUS_HTML = "<script>alert('xss')</script>"
SAFE_STRING = "Hello, this is safe."
SAFE_BYTES = b"Some binary safe content"
DANGEROUS_HTML_BYTES = DANGEROUS_HTML.encode("utf-8")
NON_UTF8_BYTES = b"\x80\x81\x82"


# Tests for ResourceCreate
def test_resource_create_with_safe_string():
    r = ResourceCreate(uri="some-uri", name="test.txt", content=SAFE_STRING)
    assert isinstance(r.content, str)


def test_resource_create_with_dangerous_html_string():
    with pytest.raises(ValueError, match="Content contains HTML tags"):
        ResourceCreate(uri="some-uri", name="dangerous.html", content=DANGEROUS_HTML)


def test_resource_create_with_safe_bytes():
    r = ResourceCreate(uri="some-uri", name="test.bin", content=SAFE_BYTES)
    assert isinstance(r.content, bytes)


def test_resource_create_with_dangerous_html_bytes():
    with pytest.raises(ValueError, match="Content contains HTML tags"):
        ResourceCreate(uri="some-uri", name="dangerous.html", content=DANGEROUS_HTML_BYTES)


def test_resource_create_with_non_utf8_bytes():
    with pytest.raises(ValueError, match="Content must be UTF-8 decodable"):
        ResourceCreate(uri="some-uri", name="nonutf8.bin", content=NON_UTF8_BYTES)


class TestTeamXSSValidation:
    """Test XSS prevention in team schemas."""

    def test_team_name_blocks_script_tag(self):
        """Script tags in team name should be rejected (via strict pattern)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="<script>alert(1)</script>", description="test")

    def test_team_name_blocks_img_onerror(self):
        """Event handlers in team name should be rejected (via strict pattern)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="<img src=x onerror=alert(1)>", description="test")

    def test_team_name_blocks_iframe(self):
        """Iframe tags in team name should be rejected (via strict pattern)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="<iframe src='evil.com'></iframe>", description="test")

    def test_team_description_blocks_script(self):
        """Script tags in description should be rejected."""
        with pytest.raises(ValidationError, match="contains HTML tags"):
            TeamCreateRequest(name="Valid Team", description="<script>alert(1)</script>")

    def test_team_name_blocks_javascript_url(self):
        """javascript: URLs in team name should be rejected (via strict pattern since ':' not allowed)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="javascript:alert(1)", description="test")

    def test_team_name_blocks_special_characters(self):
        """Special characters like < > should be rejected."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="Team <Engineering>", description="test")

    def test_team_name_blocks_ampersand(self):
        """Ampersand should be rejected (strict mode)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamCreateRequest(name="R&D Team", description="test")

    def test_valid_team_name_allowed(self):
        """Normal team names should pass validation."""
        team = TeamCreateRequest(name="Engineering Team", description="Our engineering team")
        assert team.name == "Engineering Team"

    def test_valid_team_name_with_allowed_chars(self):
        """Names with allowed special chars should pass."""
        team = TeamCreateRequest(name="Dev_Team-2024.v1", description="Development team")
        assert team.name == "Dev_Team-2024.v1"

    def test_update_team_name_blocks_xss(self):
        """TeamUpdateRequest should also block XSS (via strict pattern)."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamUpdateRequest(name="<script>alert(1)</script>")

    def test_update_team_description_blocks_xss(self):
        """TeamUpdateRequest description should block XSS."""
        with pytest.raises(ValidationError, match="contains HTML tags"):
            TeamUpdateRequest(description="<iframe src='evil'></iframe>")

    def test_update_team_name_blocks_special_characters(self):
        """TeamUpdateRequest should block special characters."""
        with pytest.raises(ValidationError, match="can only contain"):
            TeamUpdateRequest(name="Team <Test>")

    def test_description_blocks_javascript_url(self):
        """javascript: URLs in description should be rejected via XSS check."""
        with pytest.raises(ValidationError, match="contains script patterns"):
            TeamCreateRequest(name="Valid Team", description="Click javascript:alert(1)")

    def test_description_blocks_onerror_event(self):
        """Event handlers in description should be rejected via XSS check."""
        with pytest.raises(ValidationError, match="contains script patterns"):
            TeamCreateRequest(name="Valid Team", description='test onerror="alert(1)"')


class TestSchemaValidators:
    """Targeted validator coverage for tool/resource/global config schemas."""

    def test_tool_create_request_type_by_integration(self):
        """MCP and A2A integrations should accept only allowed request types."""
        with pytest.raises(ValidationError, match="Cannot manually create MCP tools"):
            ToolCreate(name="mcp-tool", integration_type="MCP", request_type="STDIO", url="http://example.com")

        with pytest.raises(ValidationError, match="Cannot manually create A2A tools"):
            ToolCreate(name="a2a-tool", integration_type="A2A", request_type="POST", url="http://example.com")

        with pytest.raises(ValidationError, match="not allowed"):
            ToolCreate(name="bad-tool", integration_type="REST", request_type="SSE", url="http://example.com")

    def test_tool_create_auth_assembly(self):
        """Auth fields should assemble into encoded auth values."""
        basic_tool = ToolCreate(
            name="basic-tool",
            integration_type="REST",
            request_type="GET",
            url="http://example.com",
            auth_type="basic",
            auth_username="user",
            auth_password="pass",
        )
        assert basic_tool.auth.auth_type == "basic"
        assert basic_tool.auth.auth_value

        bearer_tool = ToolCreate(
            name="bearer-tool",
            integration_type="REST",
            request_type="GET",
            url="http://example.com",
            auth_type="bearer",
            auth_token="token123",
        )
        assert bearer_tool.auth.auth_type == "bearer"
        assert bearer_tool.auth.auth_value

        headers_tool = ToolCreate(
            name="headers-tool",
            integration_type="REST",
            request_type="GET",
            url="http://example.com",
            auth_type="authheaders",
            auth_header_key="X-Auth",
            auth_header_value="secret",
        )
        assert headers_tool.auth.auth_type == "authheaders"
        assert headers_tool.auth.auth_value

        empty_headers_tool = ToolCreate(
            name="headers-tool-empty",
            integration_type="REST",
            request_type="GET",
            url="http://example.com",
            auth_type="authheaders",
        )
        assert empty_headers_tool.auth.auth_type == "authheaders"
        assert empty_headers_tool.auth.auth_value is None

    def test_tool_create_sets_default_timeout(self):
        """REST passthrough tools should default timeout_ms when missing."""
        tool = ToolCreate(name="rest-tool", integration_type="REST", request_type="GET", url="http://example.com")
        assert tool.timeout_ms == 20000

    def test_tool_update_extracts_base_url_and_path(self):
        """ToolUpdate should parse URL into base_url and path_template."""
        update = ToolUpdate(integration_type="REST", url="https://example.com/api/v1")
        assert update.base_url == "https://example.com"
        assert update.path_template == "/api/v1"

    def test_tool_update_validation_errors(self):
        """ToolUpdate validators should reject invalid passthrough configs."""
        with pytest.raises(ValidationError, match="path_template must start"):
            ToolUpdate(path_template="no-leading-slash")

        with pytest.raises(ValidationError, match="timeout_ms must be a positive integer"):
            ToolUpdate(timeout_ms=0)

        with pytest.raises(ValidationError, match="Invalid host/scheme"):
            ToolUpdate(allowlist=["not a host"])

        with pytest.raises(ValidationError, match="Unknown plugin"):
            ToolUpdate(plugin_chain_pre=["unknown_plugin"])

    def test_tool_update_validator_helpers(self):
        """Directly exercise allowlist/plugin validators for edge cases."""
        assert ToolUpdate.validate_allowlist(None) is None
        with pytest.raises(ValueError, match="allowlist must be a list"):
            ToolUpdate.validate_allowlist("not-a-list")
        with pytest.raises(ValueError, match="Invalid type in allowlist"):
            ToolUpdate.validate_allowlist([123])

        with pytest.raises(ValueError, match="Unknown plugin"):
            ToolUpdate.validate_plugin_chain(["unknown_plugin"])

    def test_resource_description_truncation(self):
        """ResourceCreate should truncate overly long descriptions."""
        long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 5)
        resource = ResourceCreate(uri="resource://test", name="resource", description=long_desc, content="data")  # noqa: F841

    def test_gateway_create_with_valid_gateway_modes(self):
        """Test GatewayCreate accepts valid gateway_mode values."""
        from mcpgateway.schemas import GatewayCreate

        # Test with cache mode (default)
        gateway = GatewayCreate(
            name="Test Gateway",
            url="https://example.com",
            transport="SSE",
            gateway_mode="cache",
        )
        assert gateway.gateway_mode == "cache"

        # Test with direct_proxy mode
        gateway = GatewayCreate(
            name="Test Gateway",
            url="https://example.com",
            transport="SSE",
            gateway_mode="direct_proxy",
        )
        assert gateway.gateway_mode == "direct_proxy"

        # Test default value
        gateway = GatewayCreate(
            name="Test Gateway",
            url="https://example.com",
            transport="SSE",
        )
        assert gateway.gateway_mode == "cache"

    def test_gateway_create_with_invalid_gateway_mode(self):
        """Test GatewayCreate rejects invalid gateway_mode values."""
        from mcpgateway.schemas import GatewayCreate

        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(
                name="Test Gateway",
                url="https://example.com",
                transport="SSE",
                gateway_mode="invalid_mode",
            )

        # Check that the error mentions the pattern validation
        assert "gateway_mode" in str(exc_info.value)

    def test_gateway_update_with_valid_gateway_modes(self):
        """Test GatewayUpdate accepts valid gateway_mode values."""
        from mcpgateway.schemas import GatewayUpdate

        # Test updating to cache mode
        update = GatewayUpdate(gateway_mode="cache")
        assert update.gateway_mode == "cache"

        # Test updating to direct_proxy mode
        update = GatewayUpdate(gateway_mode="direct_proxy")
        assert update.gateway_mode == "direct_proxy"

        # Test None (no update)
        update = GatewayUpdate()
        assert update.gateway_mode is None

    def test_gateway_update_with_invalid_gateway_mode(self):
        """Test GatewayUpdate rejects invalid gateway_mode values."""
        from mcpgateway.schemas import GatewayUpdate

        with pytest.raises(ValidationError) as exc_info:
            GatewayUpdate(gateway_mode="invalid_mode")

        # Check that the error mentions the pattern validation
        assert "gateway_mode" in str(exc_info.value)

    def test_gateway_read_includes_gateway_mode(self):
        """Test GatewayRead includes gateway_mode field with default."""
        from mcpgateway.schemas import GatewayRead

        # Test with explicit cache mode
        gateway = GatewayRead(
            id="gw-123",
            name="Test Gateway",
            slug="test-gateway",
            url="https://example.com",
            transport="STREAMABLEHTTP",
            gateway_mode="cache",
        )
        assert gateway.gateway_mode == "cache"

        # Test with direct_proxy mode
        gateway = GatewayRead(
            id="gw-123",
            name="Test Gateway",
            slug="test-gateway",
            url="https://example.com",
            transport="STREAMABLEHTTP",
            gateway_mode="direct_proxy",
        )
        assert gateway.gateway_mode == "direct_proxy"


# ---------------------------------------------------------------------------
# Dynamic Server / Rule Schemas
# ---------------------------------------------------------------------------


class TestDynamicRuleCreate:
    """Tests for DynamicRuleCreate schema."""

    def test_valid_tag_rule(self):
        """Create a tag rule with all valid fields."""
        from mcpgateway.schemas import DynamicRuleCreate

        rule = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")
        assert rule.rule_type == "tag"
        assert rule.entity_type == "tool"
        assert rule.value == "finance"

    def test_valid_regex_rule(self):
        """Create a regex rule targeting resources."""
        from mcpgateway.schemas import DynamicRuleCreate

        rule = DynamicRuleCreate(rule_type="regex", entity_type="resource", value="^finance.*")
        assert rule.rule_type == "regex"
        assert rule.entity_type == "resource"
        assert rule.value == "^finance.*"

    def test_valid_llm_rule(self):
        """Create an LLM rule targeting prompts."""
        from mcpgateway.schemas import DynamicRuleCreate

        rule = DynamicRuleCreate(rule_type="llm", entity_type="prompt", value="financial analysis")
        assert rule.rule_type == "llm"
        assert rule.entity_type == "prompt"

    def test_all_entity_types_accepted(self):
        """All three entity_type literals are accepted."""
        from mcpgateway.schemas import DynamicRuleCreate

        for entity_type in ("tool", "resource", "prompt"):
            rule = DynamicRuleCreate(rule_type="tag", entity_type=entity_type, value="v")
            assert rule.entity_type == entity_type

    def test_all_rule_types_accepted(self):
        """All three rule_type literals are accepted."""
        from mcpgateway.schemas import DynamicRuleCreate

        for rule_type in ("tag", "regex", "llm"):
            rule = DynamicRuleCreate(rule_type=rule_type, entity_type="tool", value="v")
            assert rule.rule_type == rule_type

    def test_invalid_rule_type_rejected(self):
        """Unknown rule_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError) as exc_info:
            DynamicRuleCreate(rule_type="fuzzy", entity_type="tool", value="v")
        assert "rule_type" in str(exc_info.value)

    def test_invalid_entity_type_rejected(self):
        """Unknown entity_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError) as exc_info:
            DynamicRuleCreate(rule_type="tag", entity_type="gateway", value="v")
        assert "entity_type" in str(exc_info.value)

    def test_empty_value_rejected(self):
        """Blank value must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError) as exc_info:
            DynamicRuleCreate(rule_type="tag", entity_type="tool", value="")
        assert "value" in str(exc_info.value)

    def test_whitespace_only_value_rejected(self):
        """Whitespace-only value must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError):
            DynamicRuleCreate(rule_type="tag", entity_type="tool", value="   ")

    def test_missing_rule_type_rejected(self):
        """Omitting rule_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError):
            DynamicRuleCreate(entity_type="tool", value="v")

    def test_missing_entity_type_rejected(self):
        """Omitting entity_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError):
            DynamicRuleCreate(rule_type="tag", value="v")

    def test_missing_value_rejected(self):
        """Omitting value must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleCreate

        with pytest.raises(ValidationError):
            DynamicRuleCreate(rule_type="tag", entity_type="tool")

    def test_value_is_stripped(self):
        """Leading/trailing whitespace on value is stripped by ConfigDict."""
        from mcpgateway.schemas import DynamicRuleCreate

        rule = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="  finance  ")
        assert rule.value == "finance"

    def test_roundtrip_serialization(self):
        """model_dump and reconstruction produce identical objects."""
        from mcpgateway.schemas import DynamicRuleCreate

        original = DynamicRuleCreate(rule_type="regex", entity_type="resource", value=".*")
        data = original.model_dump()
        reconstructed = DynamicRuleCreate(**data)
        assert reconstructed == original


class TestDynamicRuleRead:
    """Tests for DynamicRuleRead schema."""

    def _make_rule(self, **kwargs):
        from mcpgateway.schemas import DynamicRuleRead

        defaults = {
            "id": "rule-1",
            "rule_type": "tag",
            "entity_type": "tool",
            "value": "finance",
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        return DynamicRuleRead(**defaults)

    def test_valid_creation(self):
        """DynamicRuleRead accepts all required fields."""
        rule = self._make_rule()
        assert rule.id == "rule-1"
        assert rule.rule_type == "tag"
        assert rule.entity_type == "tool"
        assert rule.value == "finance"
        assert rule.created_at == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_all_rule_types_accepted(self):
        """All rule_type literals round-trip correctly."""
        for rt in ("tag", "regex", "llm"):
            rule = self._make_rule(rule_type=rt)
            assert rule.rule_type == rt

    def test_all_entity_types_accepted(self):
        """All entity_type literals round-trip correctly."""
        for et in ("tool", "resource", "prompt"):
            rule = self._make_rule(entity_type=et)
            assert rule.entity_type == et

    def test_invalid_rule_type_rejected(self):
        """Invalid rule_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleRead

        with pytest.raises(ValidationError) as exc_info:
            DynamicRuleRead(
                id="r1", rule_type="bad", entity_type="tool",
                value="v", created_at=datetime.now(timezone.utc),
            )
        assert "rule_type" in str(exc_info.value)

    def test_invalid_entity_type_rejected(self):
        """Invalid entity_type must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleRead

        with pytest.raises(ValidationError) as exc_info:
            DynamicRuleRead(
                id="r1", rule_type="tag", entity_type="unknown",
                value="v", created_at=datetime.now(timezone.utc),
            )
        assert "entity_type" in str(exc_info.value)

    def test_missing_id_rejected(self):
        """Omitting id must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleRead

        with pytest.raises(ValidationError):
            DynamicRuleRead(
                rule_type="tag", entity_type="tool",
                value="v", created_at=datetime.now(timezone.utc),
            )

    def test_missing_created_at_rejected(self):
        """Omitting created_at must raise ValidationError."""
        from mcpgateway.schemas import DynamicRuleRead

        with pytest.raises(ValidationError):
            DynamicRuleRead(id="r1", rule_type="tag", entity_type="tool", value="v")

    def test_created_at_preserves_timezone(self):
        """created_at retains the supplied timezone info."""
        ts = datetime(2024, 6, 15, 12, 30, tzinfo=timezone.utc)
        rule = self._make_rule(created_at=ts)
        assert rule.created_at == ts

    def test_model_dump_contains_all_fields(self):
        """model_dump includes all five fields."""
        rule = self._make_rule()
        data = rule.model_dump()
        for key in ("id", "rule_type", "entity_type", "value", "created_at"):
            assert key in data


class TestDynamicServerCreate:
    """Tests for DynamicServerCreate schema."""

    def test_minimal_valid_creation(self):
        """name only — other fields take defaults."""
        from mcpgateway.schemas import DynamicServerCreate

        server = DynamicServerCreate(name="my-server")
        assert server.name == "my-server"
        assert server.description is None
        assert server.rules == []
        assert server.refresh_interval is None
        assert server.visibility == "public"

    def test_full_creation_with_rules(self):
        """All fields provided including rules list."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerCreate

        rule = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance")
        server = DynamicServerCreate(
            name="finance-server",
            description="Finance tools",
            rules=[rule],
            refresh_interval=300,
            visibility="private",
        )
        assert server.name == "finance-server"
        assert server.description == "Finance tools"
        assert len(server.rules) == 1
        assert server.refresh_interval == 300
        assert server.visibility == "private"

    def test_empty_name_rejected(self):
        """Empty name string must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError) as exc_info:
            DynamicServerCreate(name="")
        assert "name" in str(exc_info.value)

    def test_whitespace_only_name_rejected(self):
        """Whitespace-only name must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError):
            DynamicServerCreate(name="   ")

    def test_missing_name_rejected(self):
        """Omitting name must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError):
            DynamicServerCreate()

    def test_name_is_stripped(self):
        """str_strip_whitespace trims the name."""
        from mcpgateway.schemas import DynamicServerCreate

        server = DynamicServerCreate(name="  my-server  ")
        assert server.name == "my-server"

    def test_refresh_interval_zero_rejected(self):
        """refresh_interval=0 violates ge=1 constraint."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError) as exc_info:
            DynamicServerCreate(name="s", refresh_interval=0)
        assert "refresh_interval" in str(exc_info.value)

    def test_refresh_interval_negative_rejected(self):
        """Negative refresh_interval violates ge=1 constraint."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError):
            DynamicServerCreate(name="s", refresh_interval=-10)

    def test_refresh_interval_one_accepted(self):
        """refresh_interval=1 is the minimum valid value."""
        from mcpgateway.schemas import DynamicServerCreate

        server = DynamicServerCreate(name="s", refresh_interval=1)
        assert server.refresh_interval == 1

    def test_rules_default_is_empty_list(self):
        """rules defaults to an empty list (not None)."""
        from mcpgateway.schemas import DynamicServerCreate

        server = DynamicServerCreate(name="s")
        assert server.rules == []
        assert isinstance(server.rules, list)

    def test_multiple_rules_accepted(self):
        """Multiple rules of different types are all accepted."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerCreate

        rules = [
            DynamicRuleCreate(rule_type="tag", entity_type="tool", value="finance"),
            DynamicRuleCreate(rule_type="regex", entity_type="resource", value=".*"),
            DynamicRuleCreate(rule_type="llm", entity_type="prompt", value="show me prompts"),
        ]
        server = DynamicServerCreate(name="multi", rules=rules)
        assert len(server.rules) == 3

    def test_invalid_rule_in_list_rejected(self):
        """An invalid rule inside the list must cause ValidationError."""
        from mcpgateway.schemas import DynamicServerCreate

        with pytest.raises(ValidationError):
            DynamicServerCreate(name="s", rules=[{"rule_type": "bad", "entity_type": "tool", "value": "v"}])

    def test_roundtrip_serialization(self):
        """model_dump → reconstruction produces identical object."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerCreate

        original = DynamicServerCreate(
            name="test",
            description="desc",
            rules=[DynamicRuleCreate(rule_type="tag", entity_type="tool", value="v")],
            refresh_interval=60,
            visibility="private",
        )
        data = original.model_dump()
        reconstructed = DynamicServerCreate(**data)
        assert reconstructed == original


class TestDynamicServerRead:
    """Tests for DynamicServerRead schema."""

    def _make_server(self, **kwargs):
        from mcpgateway.schemas import DynamicServerRead

        defaults = {
            "id": "srv-1",
            "name": "finance",
            "rules": [],
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        return DynamicServerRead(**defaults)

    def test_minimal_valid_creation(self):
        """id, name, rules (empty), created_at are sufficient."""
        server = self._make_server()
        assert server.id == "srv-1"
        assert server.name == "finance"
        assert server.rules == []
        assert server.description is None
        assert server.refresh_interval is None
        assert server.visibility == "public"
        assert server.created_by is None

    def test_full_creation(self):
        """All fields accepted when provided."""
        from mcpgateway.schemas import DynamicRuleRead, DynamicServerRead

        rule = DynamicRuleRead(
            id="r1", rule_type="tag", entity_type="tool",
            value="finance", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        server = DynamicServerRead(
            id="srv-2",
            name="full-server",
            description="A complete server",
            rules=[rule],
            refresh_interval=120,
            visibility="private",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            created_by="admin@example.com",
        )
        assert server.id == "srv-2"
        assert server.description == "A complete server"
        assert len(server.rules) == 1
        assert server.rules[0].id == "r1"
        assert server.refresh_interval == 120
        assert server.visibility == "private"
        assert server.created_by == "admin@example.com"

    def test_missing_id_rejected(self):
        """Omitting id must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerRead

        with pytest.raises(ValidationError):
            DynamicServerRead(
                name="s", rules=[],
                created_at=datetime.now(timezone.utc),
            )

    def test_missing_name_rejected(self):
        """Omitting name must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerRead

        with pytest.raises(ValidationError):
            DynamicServerRead(
                id="s1", rules=[],
                created_at=datetime.now(timezone.utc),
            )

    def test_missing_created_at_rejected(self):
        """Omitting created_at must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerRead

        with pytest.raises(ValidationError):
            DynamicServerRead(id="s1", name="s", rules=[])

    def test_rules_list_contains_rule_read_objects(self):
        """Rules list is populated with DynamicRuleRead instances."""
        from mcpgateway.schemas import DynamicRuleRead

        rule_data = {
            "id": "r1", "rule_type": "regex", "entity_type": "resource",
            "value": ".*", "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        server = self._make_server(rules=[rule_data])
        assert isinstance(server.rules[0], DynamicRuleRead)

    def test_created_at_preserves_timezone(self):
        """created_at retains UTC timezone."""
        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        server = self._make_server(created_at=ts)
        assert server.created_at == ts

    def test_model_dump_includes_rules(self):
        """model_dump serializes nested rules list."""
        from mcpgateway.schemas import DynamicRuleRead

        rule = DynamicRuleRead(
            id="r1", rule_type="tag", entity_type="tool",
            value="v", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        server = self._make_server(rules=[rule])
        data = server.model_dump()
        assert isinstance(data["rules"], list)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["id"] == "r1"


class TestDynamicServerUpdate:
    """Tests for DynamicServerUpdate schema."""

    def test_empty_update_valid(self):
        """All fields optional — empty update is valid."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate()
        assert update.name is None
        assert update.description is None
        assert update.rules is None
        assert update.refresh_interval is None
        assert update.visibility is None

    def test_name_only_update(self):
        """Only name supplied — other fields remain None."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate(name="new-name")
        assert update.name == "new-name"
        assert update.description is None

    def test_description_only_update(self):
        """Only description supplied."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate(description="updated description")
        assert update.description == "updated description"
        assert update.name is None

    def test_rules_replace_semantics(self):
        """Supplying rules replaces the full list (full-replace)."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerUpdate

        rules = [DynamicRuleCreate(rule_type="tag", entity_type="tool", value="hr")]
        update = DynamicServerUpdate(rules=rules)
        assert update.rules is not None
        assert len(update.rules) == 1

    def test_rules_none_means_unchanged(self):
        """rules=None signals no change to the existing list."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate(description="only desc")
        assert update.rules is None

    def test_empty_name_rejected(self):
        """Empty string name must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerUpdate

        with pytest.raises(ValidationError) as exc_info:
            DynamicServerUpdate(name="")
        assert "name" in str(exc_info.value)

    def test_whitespace_only_name_rejected(self):
        """Whitespace-only name must raise ValidationError."""
        from mcpgateway.schemas import DynamicServerUpdate

        with pytest.raises(ValidationError):
            DynamicServerUpdate(name="   ")

    def test_refresh_interval_zero_rejected(self):
        """refresh_interval=0 violates ge=1 constraint."""
        from mcpgateway.schemas import DynamicServerUpdate

        with pytest.raises(ValidationError) as exc_info:
            DynamicServerUpdate(refresh_interval=0)
        assert "refresh_interval" in str(exc_info.value)

    def test_refresh_interval_negative_rejected(self):
        """Negative refresh_interval is rejected."""
        from mcpgateway.schemas import DynamicServerUpdate

        with pytest.raises(ValidationError):
            DynamicServerUpdate(refresh_interval=-5)

    def test_refresh_interval_one_accepted(self):
        """refresh_interval=1 is the minimum valid value."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate(refresh_interval=1)
        assert update.refresh_interval == 1

    def test_name_is_stripped(self):
        """str_strip_whitespace trims leading/trailing whitespace."""
        from mcpgateway.schemas import DynamicServerUpdate

        update = DynamicServerUpdate(name="  trimmed  ")
        assert update.name == "trimmed"

    def test_full_update(self):
        """All fields provided simultaneously."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerUpdate

        rules = [DynamicRuleCreate(rule_type="llm", entity_type="prompt", value="find summaries")]
        update = DynamicServerUpdate(
            name="new-name",
            description="new desc",
            rules=rules,
            refresh_interval=600,
            visibility="private",
        )
        assert update.name == "new-name"
        assert update.description == "new desc"
        assert len(update.rules) == 1
        assert update.refresh_interval == 600
        assert update.visibility == "private"

    def test_roundtrip_serialization(self):
        """model_dump → reconstruction produces identical object."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerUpdate

        original = DynamicServerUpdate(
            name="x",
            rules=[DynamicRuleCreate(rule_type="tag", entity_type="resource", value="tag1")],
        )
        data = original.model_dump()
        reconstructed = DynamicServerUpdate(**data)
        assert reconstructed == original


class TestDynamicCatalogResponse:
    """Tests for DynamicCatalogResponse schema."""

    def _make_catalog(self, **kwargs):
        from mcpgateway.schemas import DynamicCatalogResponse

        defaults = {
            "server_id": "srv-1",
            "server_name": "finance",
            "evaluated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        return DynamicCatalogResponse(**defaults)

    def test_minimal_valid_creation(self):
        """server_id and server_name are sufficient; lists default to empty."""
        cat = self._make_catalog()
        assert cat.server_id == "srv-1"
        assert cat.server_name == "finance"
        assert cat.tools == []
        assert cat.resources == []
        assert cat.prompts == []

    def test_full_creation_with_all_lists(self):
        """All list fields populated correctly."""
        cat = self._make_catalog(
            tools=["calc", "exchange"],
            resources=["rates-doc"],
            prompts=["summarise"],
        )
        assert cat.tools == ["calc", "exchange"]
        assert cat.resources == ["rates-doc"]
        assert cat.prompts == ["summarise"]

    def test_evaluated_at_defaults_to_now(self):
        """evaluated_at has a default_factory producing a UTC datetime."""
        from mcpgateway.schemas import DynamicCatalogResponse

        before = datetime.now(timezone.utc)
        cat = DynamicCatalogResponse(server_id="s1", server_name="s")
        after = datetime.now(timezone.utc)
        assert before <= cat.evaluated_at <= after

    def test_evaluated_at_explicit_value(self):
        """An explicitly supplied evaluated_at is preserved."""
        ts = datetime(2023, 6, 1, 10, 0, tzinfo=timezone.utc)
        cat = self._make_catalog(evaluated_at=ts)
        assert cat.evaluated_at == ts

    def test_missing_server_id_rejected(self):
        """Omitting server_id must raise ValidationError."""
        from mcpgateway.schemas import DynamicCatalogResponse

        with pytest.raises(ValidationError):
            DynamicCatalogResponse(
                server_name="s",
                evaluated_at=datetime.now(timezone.utc),
            )

    def test_missing_server_name_rejected(self):
        """Omitting server_name must raise ValidationError."""
        from mcpgateway.schemas import DynamicCatalogResponse

        with pytest.raises(ValidationError):
            DynamicCatalogResponse(
                server_id="s1",
                evaluated_at=datetime.now(timezone.utc),
            )

    def test_tools_list_accepts_multiple_entries(self):
        """tools accepts any number of string entries."""
        cat = self._make_catalog(tools=["a", "b", "c", "d"])
        assert len(cat.tools) == 4

    def test_resources_list_independent_of_tools(self):
        """resources and tools are independent lists."""
        cat = self._make_catalog(tools=["t1"], resources=["r1", "r2"])
        assert cat.tools == ["t1"]
        assert cat.resources == ["r1", "r2"]

    def test_prompts_list_independent(self):
        """prompts list is independent of tools and resources."""
        cat = self._make_catalog(prompts=["p1", "p2", "p3"])
        assert cat.prompts == ["p1", "p2", "p3"]
        assert cat.tools == []
        assert cat.resources == []

    def test_empty_lists_explicitly_provided(self):
        """Explicitly passing empty lists is equivalent to defaults."""
        cat = self._make_catalog(tools=[], resources=[], prompts=[])
        assert cat.tools == []
        assert cat.resources == []
        assert cat.prompts == []

    def test_model_dump_contains_all_fields(self):
        """model_dump includes all six expected keys."""
        cat = self._make_catalog(tools=["t1"])
        data = cat.model_dump()
        for key in ("server_id", "server_name", "tools", "resources", "prompts", "evaluated_at"):
            assert key in data

    def test_multiple_catalogs_have_independent_defaults(self):
        """Each instance gets its own list instances (no shared mutable state)."""
        from mcpgateway.schemas import DynamicCatalogResponse

        cat1 = DynamicCatalogResponse(server_id="s1", server_name="a")
        cat2 = DynamicCatalogResponse(server_id="s2", server_name="b")
        cat1.tools.append("tool-x")
        assert cat2.tools == []


class TestDynamicSchemaIntegration:
    """Integration tests combining multiple dynamic schemas."""

    def test_create_to_read_field_correspondence(self):
        """DynamicRuleCreate fields map to the corresponding DynamicRuleRead fields."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicRuleRead

        create = DynamicRuleCreate(rule_type="llm", entity_type="prompt", value="finance report")
        read = DynamicRuleRead(
            id="r99",
            rule_type=create.rule_type,
            entity_type=create.entity_type,
            value=create.value,
            created_at=datetime.now(timezone.utc),
        )
        assert read.rule_type == create.rule_type
        assert read.entity_type == create.entity_type
        assert read.value == create.value

    def test_server_create_rules_round_trip_to_server_read(self):
        """Rules from DynamicServerCreate can be promoted to DynamicServerRead."""
        from mcpgateway.schemas import (
            DynamicRuleCreate,
            DynamicRuleRead,
            DynamicServerCreate,
            DynamicServerRead,
        )

        rule_create = DynamicRuleCreate(rule_type="tag", entity_type="tool", value="hr")
        server_create = DynamicServerCreate(name="hr-server", rules=[rule_create])

        # Simulate persistence layer promoting to Read schema
        rule_read = DynamicRuleRead(
            id="r1",
            rule_type=rule_create.rule_type,
            entity_type=rule_create.entity_type,
            value=rule_create.value,
            created_at=datetime.now(timezone.utc),
        )
        server_read = DynamicServerRead(
            id="s1",
            name=server_create.name,
            description=server_create.description,
            rules=[rule_read],
            refresh_interval=server_create.refresh_interval,
            visibility=server_create.visibility,
            created_at=datetime.now(timezone.utc),
            created_by="tester@example.com",
        )
        assert server_read.name == "hr-server"
        assert len(server_read.rules) == 1
        assert server_read.rules[0].value == "hr"

    def test_server_update_allows_rule_replacement(self):
        """DynamicServerUpdate.rules can hold rules built from DynamicRuleCreate."""
        from mcpgateway.schemas import DynamicRuleCreate, DynamicServerUpdate

        new_rules = [
            DynamicRuleCreate(rule_type="regex", entity_type="resource", value="^hr-.*"),
            DynamicRuleCreate(rule_type="tag", entity_type="tool", value="payroll"),
        ]
        update = DynamicServerUpdate(name="updated-server", rules=new_rules)
        assert len(update.rules) == 2
        assert update.rules[0].rule_type == "regex"

    def test_catalog_response_reflects_server_read(self):
        """DynamicCatalogResponse can be constructed from DynamicServerRead metadata."""
        from mcpgateway.schemas import DynamicCatalogResponse, DynamicServerRead

        server = DynamicServerRead(
            id="s1",
            name="finance",
            rules=[],
            created_at=datetime.now(timezone.utc),
        )
        catalog = DynamicCatalogResponse(
            server_id=server.id,
            server_name=server.name,
            tools=["calc"],
            resources=[],
            prompts=[],
        )
        assert catalog.server_id == server.id
        assert catalog.server_name == server.name

    def test_all_six_classes_importable(self):
        """Smoke test: all six schema classes can be imported in one statement."""
        from mcpgateway.schemas import (  # noqa: F401
            DynamicCatalogResponse,
            DynamicRuleCreate,
            DynamicRuleRead,
            DynamicServerCreate,
            DynamicServerRead,
            DynamicServerUpdate,
        )
