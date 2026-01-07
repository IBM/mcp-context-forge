# -*- coding: utf-8 -*-
"""Tests for Tool hook Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for tool hook payload classes.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.hooks.tools import (
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestToolPreInvokePayloadConversion:
    """Test ToolPreInvokePayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion(self):
        """Test basic ToolPreInvokePayload conversion to protobuf and back."""
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={"input": "data", "count": 42},
        )

        # Convert to protobuf
        proto_payload = payload.model_dump_pb()

        # Verify protobuf fields
        assert proto_payload.name == "test_tool"

        # Convert back to Pydantic
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        # Verify restoration
        assert restored.name == payload.name
        assert restored.args == payload.args
        assert restored == payload

    def test_with_empty_args(self):
        """Test ToolPreInvokePayload with empty args."""
        payload = ToolPreInvokePayload(name="empty_tool")

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "empty_tool"
        assert restored.args == {}

    def test_with_headers(self):
        """Test ToolPreInvokePayload with HTTP headers."""
        from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload

        headers = HttpHeaderPayload({"Authorization": "Bearer token123", "Content-Type": "application/json"})
        payload = ToolPreInvokePayload(
            name="api_tool",
            args={"query": "test"},
            headers=headers,
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "api_tool"
        assert restored.args["query"] == "test"
        assert restored.headers["Authorization"] == "Bearer token123"
        assert restored.headers["Content-Type"] == "application/json"

    def test_with_nested_args(self):
        """Test ToolPreInvokePayload with nested argument structures."""
        payload = ToolPreInvokePayload(
            name="complex_tool",
            args={
                "operation": "calculate",
                "params": {"a": 5, "b": 10, "operation": "add"},
                "metadata": {"version": "1.0"},
            },
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "complex_tool"
        assert restored.args["operation"] == "calculate"
        assert "params" in restored.args
        assert "metadata" in restored.args

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload

        headers = HttpHeaderPayload({"X-Custom": "value"})
        original = ToolPreInvokePayload(
            name="roundtrip_tool",
            args={"data": "test", "count": 3},
            headers=headers,
        )

        # Multiple roundtrips
        proto1 = original.model_dump_pb()
        restored1 = ToolPreInvokePayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = ToolPreInvokePayload.model_validate_pb(proto2)

        assert original.name == restored2.name
        assert original.args == restored2.args
        assert restored2.headers["X-Custom"] == "value"


class TestToolPostInvokePayloadConversion:
    """Test ToolPostInvokePayload Pydantic <-> Protobuf conversion."""

    def test_basic_conversion_with_dict_result(self):
        """Test basic ToolPostInvokePayload with dict result."""
        payload = ToolPostInvokePayload(
            name="calculator",
            result={"result": 42, "status": "success"},
        )

        proto_payload = payload.model_dump_pb()
        assert proto_payload.name == "calculator"

        restored = ToolPostInvokePayload.model_validate_pb(proto_payload)
        assert restored.name == "calculator"
        assert restored.result["result"] == 42
        assert restored.result["status"] == "success"

    def test_with_string_result(self):
        """Test ToolPostInvokePayload with string result."""
        payload = ToolPostInvokePayload(
            name="text_tool",
            result="Hello World",
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPostInvokePayload.model_validate_pb(proto_payload)

        # String results are wrapped in "value" key during conversion
        assert restored.result == "Hello World"

    def test_with_numeric_result(self):
        """Test ToolPostInvokePayload with numeric result."""
        payload = ToolPostInvokePayload(
            name="math_tool",
            result=123.45,
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPostInvokePayload.model_validate_pb(proto_payload)

        assert restored.result == 123.45

    def test_with_complex_nested_result(self):
        """Test ToolPostInvokePayload with complex nested result."""
        payload = ToolPostInvokePayload(
            name="analytics_tool",
            result={
                "summary": {"total": 100, "processed": 95},
                "details": [{"id": 1, "status": "ok"}, {"id": 2, "status": "ok"}],
                "metadata": {"timestamp": "2024-01-01T00:00:00Z"},
            },
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPostInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "analytics_tool"
        assert "summary" in restored.result
        assert "details" in restored.result
        assert "metadata" in restored.result

    def test_with_none_result(self):
        """Test ToolPostInvokePayload with None result."""
        payload = ToolPostInvokePayload(
            name="void_tool",
            result=None,
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPostInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "void_tool"
        # Note: protobuf Struct converts None to empty dict {}
        assert restored.result == {} or restored.result is None

    def test_roundtrip_conversion(self):
        """Test that multiple roundtrips maintain data integrity."""
        original = ToolPostInvokePayload(
            name="data_tool",
            result={"key1": "value1", "key2": 123, "key3": [1, 2, 3]},
        )

        proto1 = original.model_dump_pb()
        restored1 = ToolPostInvokePayload.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = ToolPostInvokePayload.model_validate_pb(proto2)

        assert original.name == restored2.name
        # Dict comparison for complex results
        assert restored2.result["key1"] == "value1"
        assert restored2.result["key2"] == 123


class TestToolPayloadEdgeCases:
    """Test edge cases for tool payload conversions."""

    def test_tool_name_with_special_characters(self):
        """Test tool names with special characters."""
        payload = ToolPreInvokePayload(
            name="my-tool_v2.0",
            args={"test": "data"},
        )

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == "my-tool_v2.0"

    def test_empty_tool_name(self):
        """Test with empty tool name."""
        payload = ToolPreInvokePayload(name="", args={})

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert restored.name == ""

    def test_large_args_dict(self):
        """Test with large arguments dictionary."""
        large_args = {f"key_{i}": f"value_{i}" for i in range(100)}
        payload = ToolPreInvokePayload(name="bulk_tool", args=large_args)

        proto_payload = payload.model_dump_pb()
        restored = ToolPreInvokePayload.model_validate_pb(proto_payload)

        assert len(restored.args) == 100
        assert restored.args["key_50"] == "value_50"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
