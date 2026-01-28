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
