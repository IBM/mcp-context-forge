# -*- coding: utf-8 -*-
"""Tests for Agent hook Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for agent hook payload classes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, Role, TextContent
from mcpgateway.plugins.framework.hooks.agents import (
    AgentPostInvokePayload,
    AgentPreInvokePayload,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestAgentPreInvokePayloadConversion:
    """Test AgentPreInvokePayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic AgentPreInvokePayload conversion to protobuf and back."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Hello"))
        payload = AgentPreInvokePayload(agent_id="agent-123", messages=[msg])

        # Convert to protobuf
        proto_payload = payload.model_dump_pb()

        # Verify protobuf fields
        assert proto_payload.agent_id == "agent-123"
        assert len(proto_payload.messages) == 1

        # Convert back to Pydantic
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        # Verify restoration
        assert restored.agent_id == payload.agent_id
        assert len(restored.messages) == 1
        assert restored.messages[0].content.text == "Hello"

    def test_with_empty_messages(self):
        """Test AgentPreInvokePayload with empty messages list."""
        payload = AgentPreInvokePayload(agent_id="agent-456", messages=[])

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.agent_id == "agent-456"
        assert len(restored.messages) == 0

    def test_with_tools(self):
        """Test AgentPreInvokePayload with tools list."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Query"))
        payload = AgentPreInvokePayload(
            agent_id="agent-789",
            messages=[msg],
            tools=["search", "calculator", "weather"],
        )

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.tools) == 3
        assert "search" in restored.tools
        assert "calculator" in restored.tools
        assert "weather" in restored.tools

    def test_with_headers(self):
        """Test AgentPreInvokePayload with HTTP headers."""
        from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload

        msg = Message(role=Role.USER, content=TextContent(type="text", text="Request"))
        headers = HttpHeaderPayload({"Authorization": "Bearer token", "X-Request-ID": "req-123"})
        payload = AgentPreInvokePayload(
            agent_id="agent-api",
            messages=[msg],
            headers=headers,
        )

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.headers["Authorization"] == "Bearer token"
        assert restored.headers["X-Request-ID"] == "req-123"

    def test_with_model_override(self):
        """Test AgentPreInvokePayload with model override."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Test"))
        payload = AgentPreInvokePayload(
            agent_id="agent-model",
            messages=[msg],
            model="claude-3-5-sonnet-20241022",
        )

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.model == "claude-3-5-sonnet-20241022"

    def test_with_system_prompt(self):
        """Test AgentPreInvokePayload with system prompt."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Help"))
        payload = AgentPreInvokePayload(
            agent_id="agent-sys",
            messages=[msg],
            system_prompt="You are a helpful assistant specialized in Python programming.",
        )

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert "helpful assistant" in restored.system_prompt
        assert "Python programming" in restored.system_prompt

    def test_with_parameters(self):
        """Test AgentPreInvokePayload with LLM parameters."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Generate"))
        payload = AgentPreInvokePayload(
            agent_id="agent-params",
            messages=[msg],
            parameters={"temperature": 0.7, "max_tokens": 1000, "top_p": 0.9},
        )

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert "temperature" in restored.parameters
        assert "max_tokens" in restored.parameters
        assert "top_p" in restored.parameters

    def test_with_multiple_messages(self):
        """Test AgentPreInvokePayload with conversation history."""
        messages = [
            Message(role=Role.USER, content=TextContent(type="text", text="Hello")),
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Hi there!")),
            Message(role=Role.USER, content=TextContent(type="text", text="How are you?")),
        ]
        payload = AgentPreInvokePayload(agent_id="agent-conv", messages=messages)

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.messages) == 3
        assert restored.messages[0].role == Role.USER
        assert restored.messages[1].role == Role.ASSISTANT
        assert restored.messages[2].role == Role.USER

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Test"))
        original = AgentPreInvokePayload(
            agent_id="agent-roundtrip",
            messages=[msg],
            tools=["tool1", "tool2"],
            model="test-model",
            parameters={"key": "value"},
        )

        proto1 = original.model_dump_pb()
        restored1 = AgentPreInvokePayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = AgentPreInvokePayload.model_validate_pb(proto2)

        assert original.agent_id == restored2.agent_id
        assert len(restored2.messages) == 1
        assert len(restored2.tools) == 2
        assert restored2.model == "test-model"


class TestAgentPostInvokePayloadConversion:
    """Test AgentPostInvokePayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic AgentPostInvokePayload conversion."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Response"))
        payload = AgentPostInvokePayload(agent_id="agent-123", messages=[msg])

        proto_payload = payload.model_dump_pb()
        assert proto_payload.agent_id == "agent-123"
        assert len(proto_payload.messages) == 1

        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)
        assert restored.agent_id == "agent-123"
        assert restored.messages[0].content.text == "Response"

    def test_with_empty_messages(self):
        """Test AgentPostInvokePayload with empty messages."""
        payload = AgentPostInvokePayload(agent_id="agent-empty", messages=[])

        proto_payload = payload.model_dump_pb()
        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.messages) == 0

    def test_with_tool_calls(self):
        """Test AgentPostInvokePayload with tool calls."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Let me search"))
        tool_calls = [
            {"name": "search", "arguments": {"query": "Python tutorials"}},
            {"name": "calculator", "arguments": {"operation": "add", "a": 5, "b": 3}},
        ]
        payload = AgentPostInvokePayload(agent_id="agent-tools", messages=[msg], tool_calls=tool_calls)

        proto_payload = payload.model_dump_pb()
        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.tool_calls) == 2
        assert restored.tool_calls[0]["name"] == "search"
        assert restored.tool_calls[1]["name"] == "calculator"
        assert restored.tool_calls[1]["arguments"]["a"] == 5

    def test_with_multiple_messages(self):
        """Test AgentPostInvokePayload with multiple response messages."""
        messages = [
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="First part")),
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Second part")),
        ]
        payload = AgentPostInvokePayload(agent_id="agent-multi", messages=messages)

        proto_payload = payload.model_dump_pb()
        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.messages) == 2
        assert restored.messages[0].content.text == "First part"
        assert restored.messages[1].content.text == "Second part"

    def test_with_complex_tool_calls(self):
        """Test AgentPostInvokePayload with complex nested tool calls."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Processing"))
        tool_calls = [
            {
                "name": "api_call",
                "arguments": {
                    "endpoint": "/v1/data",
                    "method": "POST",
                    "body": {"query": "test", "filters": {"active": True}},
                },
            }
        ]
        payload = AgentPostInvokePayload(agent_id="agent-complex", messages=[msg], tool_calls=tool_calls)

        proto_payload = payload.model_dump_pb()
        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.tool_calls) == 1
        assert "body" in restored.tool_calls[0]["arguments"]
        assert "filters" in restored.tool_calls[0]["arguments"]["body"]

    def test_without_tool_calls(self):
        """Test AgentPostInvokePayload without tool calls (None)."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Direct answer"))
        payload = AgentPostInvokePayload(agent_id="agent-direct", messages=[msg], tool_calls=None)

        proto_payload = payload.model_dump_pb()
        restored = AgentPostInvokePayload.model_validate_pb(proto_payload)

        assert restored.tool_calls is None

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Response"))
        tool_calls = [{"name": "test_tool", "arguments": {"arg": "value"}}]
        original = AgentPostInvokePayload(agent_id="agent-roundtrip", messages=[msg], tool_calls=tool_calls)

        proto1 = original.model_dump_pb()
        restored1 = AgentPostInvokePayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = AgentPostInvokePayload.model_validate_pb(proto2)

        assert original.agent_id == restored2.agent_id
        assert len(restored2.messages) == 1
        assert len(restored2.tool_calls) == 1


class TestAgentPayloadEdgeCases:
    """Test edge cases for agent payload conversions."""

    def test_empty_agent_id(self):
        """Test with empty agent ID."""
        payload = AgentPreInvokePayload(agent_id="", messages=[])

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.agent_id == ""

    def test_agent_id_with_special_characters(self):
        """Test agent ID with special characters."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Test"))
        payload = AgentPreInvokePayload(agent_id="agent-v2.0_prod:us-east-1", messages=[msg])

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.agent_id == "agent-v2.0_prod:us-east-1"

    def test_large_tools_list(self):
        """Test with large tools list."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Query"))
        tools = [f"tool_{i}" for i in range(100)]
        payload = AgentPreInvokePayload(agent_id="agent-many-tools", messages=[msg], tools=tools)

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.tools) == 100
        assert "tool_50" in restored.tools

    def test_long_conversation_history(self):
        """Test with long conversation history."""
        messages = [
            Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content=TextContent(type="text", text=f"Message {i}"))
            for i in range(50)
        ]
        payload = AgentPreInvokePayload(agent_id="agent-long-conv", messages=messages)

        proto_payload = payload.model_dump_pb()
        restored = AgentPreInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.messages) == 50
        assert restored.messages[25].content.text == "Message 25"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
