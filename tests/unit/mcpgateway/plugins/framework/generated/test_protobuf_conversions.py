# -*- coding: utf-8 -*-
"""Tests for Pydantic to Protobuf conversions.

This module tests the model_dump_pb() and model_validate_pb() methods
for converting between Pydantic models and protobuf messages.
"""

# Standard
from typing import Any

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    PluginContext,
    PluginResult,
    PluginViolation,
)

# Check if protobuf is available
try:
    import google.protobuf  # noqa: F401

    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PROTOBUF_AVAILABLE, reason="protobuf not installed")


class TestGlobalContextConversion:
    """Test GlobalContext Pydantic <-> Protobuf conversion."""

    def test_global_context_basic_conversion(self):
        """Test basic GlobalContext conversion to protobuf and back."""
        # Create Pydantic model
        ctx = GlobalContext(
            request_id="req-123",
            user="alice",
            tenant_id="tenant-1",
            server_id="server-1",
        )

        # Convert to protobuf
        proto_ctx = ctx.model_dump_pb()

        # Verify protobuf fields
        assert proto_ctx.request_id == "req-123"
        assert proto_ctx.user == "alice"
        assert proto_ctx.tenant_id == "tenant-1"
        assert proto_ctx.server_id == "server-1"

        # Convert back to Pydantic
        restored = GlobalContext.model_validate_pb(proto_ctx)

        # Verify restoration
        assert restored.request_id == ctx.request_id
        assert restored.user == ctx.user
        assert restored.tenant_id == ctx.tenant_id
        assert restored.server_id == ctx.server_id
        assert restored == ctx

    def test_global_context_with_optional_fields(self):
        """Test GlobalContext with None values converts correctly."""
        ctx = GlobalContext(request_id="req-456")

        # Convert to protobuf
        proto_ctx = ctx.model_dump_pb()

        # Convert back to Pydantic
        restored = GlobalContext.model_validate_pb(proto_ctx)

        assert restored.request_id == "req-456"
        assert restored.user is None
        assert restored.tenant_id is None
        assert restored.server_id is None
        assert restored == ctx

    def test_global_context_with_state_and_metadata(self):
        """Test GlobalContext with state and metadata."""
        ctx = GlobalContext(
            request_id="req-789",
            state={"key1": "value1", "key2": "value2"},
            metadata={"meta1": "data1"},
        )

        # Convert to protobuf
        proto_ctx = ctx.model_dump_pb()

        # Convert back to Pydantic
        restored = GlobalContext.model_validate_pb(proto_ctx)

        assert restored.request_id == ctx.request_id
        assert restored.state == ctx.state
        assert restored.metadata == ctx.metadata
        assert restored == ctx

    def test_global_context_roundtrip(self):
        """Test that multiple roundtrips maintain data integrity."""
        original = GlobalContext(
            request_id="req-multi",
            user="bob",
            state={"test": "data"},
        )

        # Multiple roundtrips
        proto1 = original.model_dump_pb()
        restored1 = GlobalContext.model_validate_pb(proto1)
        proto2 = restored1.model_dump_pb()
        restored2 = GlobalContext.model_validate_pb(proto2)

        assert original == restored1 == restored2


class TestPluginViolationConversion:
    """Test PluginViolation Pydantic <-> Protobuf conversion."""

    def test_plugin_violation_basic_conversion(self):
        """Test basic PluginViolation conversion."""
        violation = PluginViolation(
            reason="Invalid input",
            description="The input contains prohibited content",
            code="PROHIBITED_CONTENT",
        )

        # Convert to protobuf
        proto_violation = violation.model_dump_pb()

        # Verify protobuf fields
        assert proto_violation.reason == "Invalid input"
        assert proto_violation.description == "The input contains prohibited content"
        assert proto_violation.code == "PROHIBITED_CONTENT"

        # Convert back to Pydantic
        restored = PluginViolation.model_validate_pb(proto_violation)

        assert restored.reason == violation.reason
        assert restored.description == violation.description
        assert restored.code == violation.code
        assert restored == violation

    def test_plugin_violation_with_details(self):
        """Test PluginViolation with complex details dict."""
        violation = PluginViolation(
            reason="Schema validation failed",
            description="Multiple fields failed validation",
            code="VALIDATION_ERROR",
            details={
                "field": "email",
                "error": "Invalid format",
                "nested": {"key": "value"},
            },
        )

        # Convert to protobuf
        proto_violation = violation.model_dump_pb()

        # Convert back to Pydantic
        restored = PluginViolation.model_validate_pb(proto_violation)

        assert restored.reason == violation.reason
        assert restored.details["field"] == "email"
        assert restored.details["error"] == "Invalid format"
        assert "nested" in restored.details

    def test_plugin_violation_with_plugin_name(self):
        """Test PluginViolation preserves plugin_name private attribute."""
        violation = PluginViolation(
            reason="Test",
            description="Test violation",
            code="TEST",
        )
        violation.plugin_name = "test_plugin"

        # Convert to protobuf
        proto_violation = violation.model_dump_pb()

        # Verify plugin_name in proto
        assert proto_violation.plugin_name == "test_plugin"

        # Convert back to Pydantic
        restored = PluginViolation.model_validate_pb(proto_violation)

        assert restored.plugin_name == "test_plugin"

    def test_plugin_violation_empty_details(self):
        """Test PluginViolation with empty details."""
        violation = PluginViolation(
            reason="Test",
            description="Test",
            code="TEST",
            details={},
        )

        proto_violation = violation.model_dump_pb()
        restored = PluginViolation.model_validate_pb(proto_violation)

        assert restored.details == {}


class TestPluginResultConversion:
    """Test PluginResult Pydantic <-> Protobuf conversion."""

    def test_plugin_result_basic_conversion(self):
        """Test basic PluginResult conversion."""
        result: PluginResult[Any] = PluginResult(
            continue_processing=True,
            metadata={"key": "value"},
        )

        # Convert to protobuf
        proto_result = result.model_dump_pb()

        # Verify protobuf fields
        assert proto_result.continue_processing is True

        # Convert back to Pydantic
        restored = PluginResult.model_validate_pb(proto_result)

        assert restored.continue_processing == result.continue_processing
        assert restored.metadata == result.metadata

    def test_plugin_result_with_violation(self):
        """Test PluginResult with nested PluginViolation."""
        violation = PluginViolation(
            reason="Access denied",
            description="User lacks permission",
            code="ACCESS_DENIED",
        )
        result: PluginResult[Any] = PluginResult(
            continue_processing=False,
            violation=violation,
        )

        # Convert to protobuf
        proto_result = result.model_dump_pb()

        # Verify nested violation
        assert proto_result.HasField("violation")
        assert proto_result.violation.reason == "Access denied"

        # Convert back to Pydantic
        restored = PluginResult.model_validate_pb(proto_result)

        assert restored.continue_processing is False
        assert restored.violation is not None
        assert restored.violation.reason == "Access denied"
        assert restored.violation.code == "ACCESS_DENIED"

    def test_plugin_result_continue_false(self):
        """Test PluginResult with continue_processing=False."""
        result: PluginResult[Any] = PluginResult(continue_processing=False)

        proto_result = result.model_dump_pb()
        restored = PluginResult.model_validate_pb(proto_result)

        assert restored.continue_processing is False

    def test_plugin_result_with_metadata(self):
        """Test PluginResult with metadata dict."""
        result: PluginResult[Any] = PluginResult(
            metadata={"plugin": "test", "duration_ms": "100"},
        )

        proto_result = result.model_dump_pb()
        restored = PluginResult.model_validate_pb(proto_result)

        assert restored.metadata["plugin"] == "test"
        assert restored.metadata["duration_ms"] == "100"


class TestPluginContextConversion:
    """Test PluginContext Pydantic <-> Protobuf conversion."""

    def test_plugin_context_basic_conversion(self):
        """Test basic PluginContext conversion."""
        global_ctx = GlobalContext(request_id="req-123")
        ctx = PluginContext(global_context=global_ctx)

        # Convert to protobuf
        proto_ctx = ctx.model_dump_pb()

        # Verify nested global_context
        assert proto_ctx.global_context.request_id == "req-123"

        # Convert back to Pydantic
        restored = PluginContext.model_validate_pb(proto_ctx)

        assert restored.global_context.request_id == "req-123"
        assert restored.state == {}
        assert restored.metadata == {}

    def test_plugin_context_with_state(self):
        """Test PluginContext with state data."""
        global_ctx = GlobalContext(request_id="req-456")
        ctx = PluginContext(
            global_context=global_ctx,
            state={
                "counter": 42,
                "data": {"nested": "value"},
            },
        )

        # Convert to protobuf
        proto_ctx = ctx.model_dump_pb()

        # Convert back to Pydantic
        restored = PluginContext.model_validate_pb(proto_ctx)

        assert "counter" in restored.state
        assert "data" in restored.state

    def test_plugin_context_with_metadata(self):
        """Test PluginContext with metadata."""
        global_ctx = GlobalContext(request_id="req-789")
        ctx = PluginContext(
            global_context=global_ctx,
            metadata={"plugin_version": "1.0.0"},
        )

        proto_ctx = ctx.model_dump_pb()
        restored = PluginContext.model_validate_pb(proto_ctx)

        assert "plugin_version" in restored.metadata

    def test_plugin_context_complex(self):
        """Test PluginContext with complex nested data."""
        global_ctx = GlobalContext(
            request_id="req-complex",
            user="alice",
            state={"global_key": "global_value"},
        )
        ctx = PluginContext(
            global_context=global_ctx,
            state={
                "local_key": "local_value",
                "nested": {"deep": {"key": "value"}},
            },
            metadata={"timestamp": "2024-01-01"},
        )

        # Roundtrip conversion
        proto_ctx = ctx.model_dump_pb()
        restored = PluginContext.model_validate_pb(proto_ctx)

        assert restored.global_context.request_id == "req-complex"
        assert restored.global_context.user == "alice"
        assert "local_key" in restored.state
        assert "timestamp" in restored.metadata


class TestConversionEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_global_context(self):
        """Test conversion with minimal required fields."""
        ctx = GlobalContext(request_id="")

        proto_ctx = ctx.model_dump_pb()
        restored = GlobalContext.model_validate_pb(proto_ctx)

        assert restored.request_id == ""

    def test_violation_with_empty_strings(self):
        """Test PluginViolation with empty strings."""
        violation = PluginViolation(reason="", description="", code="")

        proto_violation = violation.model_dump_pb()
        restored = PluginViolation.model_validate_pb(proto_violation)

        assert restored.reason == ""
        assert restored.description == ""
        assert restored.code == ""

    def test_plugin_result_defaults(self):
        """Test PluginResult with all default values."""
        result: PluginResult[Any] = PluginResult()

        proto_result = result.model_dump_pb()
        restored = PluginResult.model_validate_pb(proto_result)

        assert restored.continue_processing is True
        assert restored.modified_payload is None
        assert restored.violation is None
        assert restored.metadata == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
