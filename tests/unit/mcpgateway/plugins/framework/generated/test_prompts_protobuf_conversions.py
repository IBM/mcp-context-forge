# -*- coding: utf-8 -*-
"""Tests for Prompt hook Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for prompt hook payload classes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework.hooks.prompts import (
    PromptPosthookPayload,
    PromptPrehookPayload,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestPromptPrehookPayloadConversion:
    """Test PromptPrehookPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic PromptPrehookPayload conversion to protobuf and back."""
        payload = PromptPrehookPayload(
            prompt_id="prompt-123",
            args={"user": "alice", "context": "testing"},
        )

        # Convert to protobuf
        proto_payload = payload.model_dump_pb()

        # Verify protobuf fields
        assert proto_payload.prompt_id == "prompt-123"

        # Convert back to Pydantic
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        # Verify restoration
        assert restored.prompt_id == payload.prompt_id
        assert restored.args == payload.args
        assert restored == payload

    def test_with_empty_args(self):
        """Test PromptPrehookPayload with empty args."""
        payload = PromptPrehookPayload(prompt_id="prompt-456")

        proto_payload = payload.model_dump_pb()
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        assert restored.prompt_id == "prompt-456"
        assert restored.args == {}

    def test_with_multiple_args(self):
        """Test PromptPrehookPayload with multiple arguments."""
        payload = PromptPrehookPayload(
            prompt_id="prompt-789",
            args={
                "name": "Bob",
                "time": "morning",
                "location": "office",
                "mood": "happy",
            },
        )

        proto_payload = payload.model_dump_pb()
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        assert restored.prompt_id == "prompt-789"
        assert restored.args["name"] == "Bob"
        assert restored.args["time"] == "morning"
        assert len(restored.args) == 4

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        original = PromptPrehookPayload(
            prompt_id="roundtrip",
            args={"key1": "value1", "key2": "value2"},
        )

        proto1 = original.model_dump_pb()
        restored1 = PromptPrehookPayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = PromptPrehookPayload.model_validate_pb(proto2)

        assert original == restored1 == restored2


class TestPromptPosthookPayloadConversion:
    """Test PromptPosthookPayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic PromptPosthookPayload conversion with PromptResult."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Hello World"))
        result = PromptResult(messages=[msg])
        payload = PromptPosthookPayload(prompt_id="prompt-123", result=result)

        proto_payload = payload.model_dump_pb()
        assert proto_payload.prompt_id == "prompt-123"

        restored = PromptPosthookPayload.model_validate_pb(proto_payload)
        assert restored.prompt_id == "prompt-123"
        assert len(restored.result.messages) == 1
        assert restored.result.messages[0].content.text == "Hello World"

    def test_with_multiple_messages(self):
        """Test PromptPosthookPayload with multiple messages."""
        msg1 = Message(role=Role.USER, content=TextContent(type="text", text="Question"))
        msg2 = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Answer"))
        result = PromptResult(messages=[msg1, msg2])
        payload = PromptPosthookPayload(prompt_id="prompt-456", result=result)

        proto_payload = payload.model_dump_pb()
        restored = PromptPosthookPayload.model_validate_pb(proto_payload)

        assert len(restored.result.messages) == 2
        assert restored.result.messages[0].role == Role.USER
        assert restored.result.messages[1].role == Role.ASSISTANT

    def test_with_assistant_message(self):
        """Test PromptPosthookPayload with assistant message."""
        msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="I am a helpful assistant"))
        result = PromptResult(messages=[msg])
        payload = PromptPosthookPayload(prompt_id="assistant-prompt", result=result)

        proto_payload = payload.model_dump_pb()
        restored = PromptPosthookPayload.model_validate_pb(proto_payload)

        assert restored.result.messages[0].role == Role.ASSISTANT
        assert "helpful assistant" in restored.result.messages[0].content.text

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        msg = Message(role=Role.USER, content=TextContent(type="text", text="Test message"))
        result = PromptResult(messages=[msg])
        original = PromptPosthookPayload(prompt_id="roundtrip", result=result)

        proto1 = original.model_dump_pb()
        restored1 = PromptPosthookPayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = PromptPosthookPayload.model_validate_pb(proto2)

        assert original.prompt_id == restored2.prompt_id
        assert len(restored2.result.messages) == 1
        assert restored2.result.messages[0].content.text == "Test message"


class TestPromptPayloadEdgeCases:
    """Test edge cases for prompt payload conversions."""

    def test_empty_prompt_id(self):
        """Test with empty prompt ID."""
        payload = PromptPrehookPayload(prompt_id="", args={})

        proto_payload = payload.model_dump_pb()
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        assert restored.prompt_id == ""

    def test_prompt_id_with_special_characters(self):
        """Test prompt ID with special characters."""
        payload = PromptPrehookPayload(
            prompt_id="my-prompt_v2.0:test",
            args={"key": "value"},
        )

        proto_payload = payload.model_dump_pb()
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        assert restored.prompt_id == "my-prompt_v2.0:test"

    def test_large_args_dict(self):
        """Test with large arguments dictionary."""
        large_args = {f"arg_{i}": f"value_{i}" for i in range(50)}
        payload = PromptPrehookPayload(prompt_id="bulk-prompt", args=large_args)

        proto_payload = payload.model_dump_pb()
        restored = PromptPrehookPayload.model_validate_pb(proto_payload)

        assert len(restored.args) == 50
        assert restored.args["arg_25"] == "value_25"

    def test_empty_message_list(self):
        """Test PromptPosthookPayload with empty message list."""
        result = PromptResult(messages=[])
        payload = PromptPosthookPayload(prompt_id="empty", result=result)

        proto_payload = payload.model_dump_pb()
        restored = PromptPosthookPayload.model_validate_pb(proto_payload)

        assert len(restored.result.messages) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
