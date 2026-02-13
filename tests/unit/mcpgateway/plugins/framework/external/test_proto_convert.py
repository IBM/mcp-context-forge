# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/test_proto_convert.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for proto_convert conversion utilities.
Tests for Pydantic <-> Protobuf conversion functions.
"""

# Third-Party
import pytest

try:
    from google.protobuf import json_format
    from google.protobuf.struct_pb2 import Struct

    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
    from mcpgateway.plugins.framework.external.proto_convert import (
        proto_context_to_dict,
        proto_context_to_pydantic,
        proto_global_context_to_pydantic,
        proto_violation_to_pydantic,
        pydantic_context_to_proto,
        pydantic_global_context_to_proto,
        pydantic_result_to_proto_base,
        pydantic_violation_to_proto,
        update_pydantic_context_from_proto,
        update_pydantic_result_from_proto_base,
    )

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed")

# First-Party
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    PluginContext,
    PluginResult,
    PluginViolation,
)


class TestPydanticGlobalContextToProto:
    """Tests for pydantic_global_context_to_proto."""

    def test_basic_conversion(self):
        """Test basic global context conversion."""
        ctx = GlobalContext(request_id="req-1", server_id="srv-1", tenant_id="tenant-1")
        proto = pydantic_global_context_to_proto(ctx)
        assert proto.request_id == "req-1"
        assert proto.server_id == "srv-1"
        assert proto.tenant_id == "tenant-1"

    def test_user_string(self):
        """Test conversion with string user field."""
        ctx = GlobalContext(request_id="req-1", user="admin@example.com")
        proto = pydantic_global_context_to_proto(ctx)
        assert proto.user_string == "admin@example.com"

    def test_user_dict(self):
        """Test conversion with dict user field."""
        ctx = GlobalContext(request_id="req-1", user={"name": "admin", "role": "super"})
        proto = pydantic_global_context_to_proto(ctx)
        user_dict = json_format.MessageToDict(proto.user_struct)
        assert user_dict["name"] == "admin"
        assert user_dict["role"] == "super"

    def test_user_none(self):
        """Test conversion with None user field."""
        ctx = GlobalContext(request_id="req-1", user=None)
        proto = pydantic_global_context_to_proto(ctx)
        assert not proto.HasField("user_string")
        assert not proto.HasField("user_struct")

    def test_with_metadata(self):
        """Test conversion with metadata."""
        ctx = GlobalContext(request_id="req-1", metadata={"key": "value"})
        proto = pydantic_global_context_to_proto(ctx)
        meta = json_format.MessageToDict(proto.metadata)
        assert meta["key"] == "value"

    def test_with_state(self):
        """Test conversion with state."""
        ctx = GlobalContext(request_id="req-1", state={"counter": 42})
        proto = pydantic_global_context_to_proto(ctx)
        state = json_format.MessageToDict(proto.state)
        assert state["counter"] == 42

    def test_none_optional_fields(self):
        """Test conversion with None optional fields."""
        ctx = GlobalContext(request_id="req-1", server_id=None, tenant_id=None)
        proto = pydantic_global_context_to_proto(ctx)
        assert proto.server_id == ""
        assert proto.tenant_id == ""


class TestProtoGlobalContextToPydantic:
    """Tests for proto_global_context_to_pydantic."""

    def test_basic_conversion(self):
        """Test basic proto to pydantic conversion."""
        proto = plugin_service_pb2.GlobalContext(
            request_id="req-1", server_id="srv-1", tenant_id="tenant-1"
        )
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.request_id == "req-1"
        assert ctx.server_id == "srv-1"
        assert ctx.tenant_id == "tenant-1"

    def test_user_string(self):
        """Test conversion with user_string field."""
        proto = plugin_service_pb2.GlobalContext(request_id="req-1")
        proto.user_string = "admin@example.com"
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.user == "admin@example.com"

    def test_user_struct(self):
        """Test conversion with user_struct field."""
        proto = plugin_service_pb2.GlobalContext(request_id="req-1")
        user_struct = Struct()
        json_format.ParseDict({"name": "admin", "role": "super"}, user_struct)
        proto.user_struct.CopyFrom(user_struct)
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.user["name"] == "admin"
        assert ctx.user["role"] == "super"

    def test_with_metadata(self):
        """Test conversion with metadata."""
        proto = plugin_service_pb2.GlobalContext(request_id="req-1")
        json_format.ParseDict({"key": "value"}, proto.metadata)
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.metadata["key"] == "value"

    def test_with_state(self):
        """Test conversion with state."""
        proto = plugin_service_pb2.GlobalContext(request_id="req-1")
        json_format.ParseDict({"counter": 42}, proto.state)
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.state["counter"] == 42

    def test_empty_optional_fields(self):
        """Test conversion with empty optional fields."""
        proto = plugin_service_pb2.GlobalContext(request_id="req-1")
        ctx = proto_global_context_to_pydantic(proto)
        assert ctx.server_id is None
        assert ctx.tenant_id is None
        assert ctx.user is None
        assert ctx.metadata == {}
        assert ctx.state == {}


class TestPydanticContextToProto:
    """Tests for pydantic_context_to_proto."""

    def test_basic_conversion(self):
        """Test basic context conversion."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1", server_id="srv-1"),
            state={"key": "value"},
        )
        proto = pydantic_context_to_proto(ctx)
        assert proto.global_context.request_id == "req-1"
        state = json_format.MessageToDict(proto.state)
        assert state["key"] == "value"

    def test_with_metadata(self):
        """Test context conversion with metadata."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1"),
            metadata={"meta_key": "meta_value"},
        )
        proto = pydantic_context_to_proto(ctx)
        meta = json_format.MessageToDict(proto.metadata)
        assert meta["meta_key"] == "meta_value"

    def test_empty_state_and_metadata(self):
        """Test context conversion with empty state and metadata."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1"),
        )
        proto = pydantic_context_to_proto(ctx)
        assert not proto.state.fields
        assert not proto.metadata.fields


class TestProtoContextToPydantic:
    """Tests for proto_context_to_pydantic."""

    def test_basic_conversion(self):
        """Test basic proto context to pydantic."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        proto.global_context.server_id = "srv-1"
        json_format.ParseDict({"key": "value"}, proto.state)

        ctx = proto_context_to_pydantic(proto)
        assert ctx.global_context.request_id == "req-1"
        assert ctx.state["key"] == "value"

    def test_empty_fields(self):
        """Test proto context with empty fields."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        ctx = proto_context_to_pydantic(proto)
        assert ctx.state == {}
        assert ctx.metadata == {}


class TestProtoContextToDict:
    """Tests for proto_context_to_dict."""

    def test_basic_conversion(self):
        """Test basic proto context to dict."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        proto.global_context.server_id = "srv-1"
        proto.global_context.tenant_id = "tenant-1"
        json_format.ParseDict({"key": "value"}, proto.state)

        result = proto_context_to_dict(proto)
        assert result["global_context"]["request_id"] == "req-1"
        assert result["global_context"]["server_id"] == "srv-1"
        assert result["state"]["key"] == "value"

    def test_with_user_string(self):
        """Test proto context to dict with user string."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        proto.global_context.user_string = "admin"
        result = proto_context_to_dict(proto)
        assert result["global_context"]["user"] == "admin"

    def test_with_user_struct(self):
        """Test proto context to dict with user struct."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        user_struct = Struct()
        json_format.ParseDict({"name": "admin"}, user_struct)
        proto.global_context.user_struct.CopyFrom(user_struct)
        result = proto_context_to_dict(proto)
        assert result["global_context"]["user"]["name"] == "admin"

    def test_empty_fields(self):
        """Test proto context to dict with empty fields."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        result = proto_context_to_dict(proto)
        assert result["global_context"]["user"] is None
        assert result["global_context"]["metadata"] == {}
        assert result["global_context"]["state"] == {}
        assert result["state"] == {}
        assert result["metadata"] == {}

    def test_with_metadata_and_state(self):
        """Test proto context to dict with metadata and state."""
        proto = plugin_service_pb2.PluginContext()
        proto.global_context.request_id = "req-1"
        json_format.ParseDict({"meta": "data"}, proto.global_context.metadata)
        json_format.ParseDict({"gc_state": "val"}, proto.global_context.state)
        json_format.ParseDict({"ctx_state": "val2"}, proto.state)
        json_format.ParseDict({"ctx_meta": "val3"}, proto.metadata)

        result = proto_context_to_dict(proto)
        assert result["global_context"]["metadata"]["meta"] == "data"
        assert result["global_context"]["state"]["gc_state"] == "val"
        assert result["state"]["ctx_state"] == "val2"
        assert result["metadata"]["ctx_meta"] == "val3"


class TestPydanticViolationToProto:
    """Tests for pydantic_violation_to_proto."""

    def test_basic_conversion(self):
        """Test basic violation conversion."""
        violation = PluginViolation(
            reason="blocked",
            description="Content blocked",
            code="BLOCKED",
        )
        violation.plugin_name = "TestPlugin"
        proto = pydantic_violation_to_proto(violation)
        assert proto.reason == "blocked"
        assert proto.description == "Content blocked"
        assert proto.code == "BLOCKED"
        assert proto.plugin_name == "TestPlugin"

    def test_with_details(self):
        """Test violation conversion with details."""
        violation = PluginViolation(
            reason="blocked",
            description="Content blocked",
            code="BLOCKED",
            details={"severity": "high", "category": "security"},
        )
        proto = pydantic_violation_to_proto(violation)
        details = json_format.MessageToDict(proto.details)
        assert details["severity"] == "high"

    def test_with_mcp_error_code(self):
        """Test violation conversion with mcp error code."""
        violation = PluginViolation(
            reason="error",
            description="Error occurred",
            code="ERR",
            mcp_error_code=-32600,
        )
        proto = pydantic_violation_to_proto(violation)
        assert proto.mcp_error_code == -32600

    def test_none_optional_fields(self):
        """Test violation conversion with None optional fields."""
        violation = PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
            mcp_error_code=None,
        )
        # plugin_name defaults to "" via PrivateAttr
        proto = pydantic_violation_to_proto(violation)
        assert proto.plugin_name == ""
        assert proto.mcp_error_code == 0


class TestProtoViolationToPydantic:
    """Tests for proto_violation_to_pydantic."""

    def test_basic_conversion(self):
        """Test basic proto violation to pydantic."""
        proto = plugin_service_pb2.PluginViolation(
            reason="blocked",
            description="Content blocked",
            code="BLOCKED",
            plugin_name="TestPlugin",
            mcp_error_code=-32600,
        )
        violation = proto_violation_to_pydantic(proto)
        assert violation.reason == "blocked"
        assert violation.description == "Content blocked"
        assert violation.code == "BLOCKED"
        assert violation.plugin_name == "TestPlugin"
        assert violation.mcp_error_code == -32600

    def test_with_details(self):
        """Test proto violation to pydantic with details."""
        proto = plugin_service_pb2.PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
        )
        json_format.ParseDict({"severity": "high"}, proto.details)
        violation = proto_violation_to_pydantic(proto)
        assert violation.details["severity"] == "high"

    def test_empty_details(self):
        """Test proto violation to pydantic with empty details."""
        proto = plugin_service_pb2.PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
        )
        violation = proto_violation_to_pydantic(proto)
        assert violation.details == {}

    def test_no_plugin_name(self):
        """Test proto violation to pydantic without plugin_name."""
        proto = plugin_service_pb2.PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
        )
        violation = proto_violation_to_pydantic(proto)
        # Empty string from proto should not set plugin_name
        assert violation.plugin_name is None or violation.plugin_name == ""

    def test_zero_mcp_error_code(self):
        """Test proto violation to pydantic with zero mcp_error_code."""
        proto = plugin_service_pb2.PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
            mcp_error_code=0,
        )
        violation = proto_violation_to_pydantic(proto)
        assert violation.mcp_error_code is None


class TestPydanticResultToProtoBase:
    """Tests for pydantic_result_to_proto_base."""

    def test_basic_conversion(self):
        """Test basic result conversion."""
        result = PluginResult(continue_processing=True)
        proto = pydantic_result_to_proto_base(result)
        assert proto.continue_processing is True

    def test_with_violation(self):
        """Test result conversion with violation."""
        violation = PluginViolation(
            reason="blocked",
            description="Blocked",
            code="BLOCKED",
        )
        result = PluginResult(continue_processing=False, violation=violation)
        proto = pydantic_result_to_proto_base(result)
        assert proto.continue_processing is False
        assert proto.violation.reason == "blocked"

    def test_with_metadata(self):
        """Test result conversion with metadata."""
        result = PluginResult(continue_processing=True, metadata={"key": "value"})
        proto = pydantic_result_to_proto_base(result)
        meta = json_format.MessageToDict(proto.metadata)
        assert meta["key"] == "value"

    def test_no_violation_no_metadata(self):
        """Test result conversion without violation or metadata."""
        result = PluginResult(continue_processing=True)
        proto = pydantic_result_to_proto_base(result)
        assert not proto.HasField("violation")
        assert not proto.metadata.fields


class TestUpdatePydanticResultFromProtoBase:
    """Tests for update_pydantic_result_from_proto_base."""

    def test_basic_update(self):
        """Test basic result update from proto."""
        result = PluginResult(continue_processing=True)
        proto = plugin_service_pb2.PluginResultBase(continue_processing=False)
        update_pydantic_result_from_proto_base(result, proto)
        assert result.continue_processing is False

    def test_update_with_violation(self):
        """Test result update with violation."""
        result = PluginResult(continue_processing=True)
        proto = plugin_service_pb2.PluginResultBase(continue_processing=False)
        proto.violation.CopyFrom(
            plugin_service_pb2.PluginViolation(
                reason="blocked",
                description="Blocked",
                code="BLOCKED",
            )
        )
        update_pydantic_result_from_proto_base(result, proto)
        assert result.violation is not None
        assert result.violation.reason == "blocked"

    def test_update_with_metadata(self):
        """Test result update with metadata."""
        result = PluginResult(continue_processing=True)
        proto = plugin_service_pb2.PluginResultBase(continue_processing=True)
        json_format.ParseDict({"key": "updated"}, proto.metadata)
        update_pydantic_result_from_proto_base(result, proto)
        assert result.metadata["key"] == "updated"


class TestUpdatePydanticContextFromProto:
    """Tests for update_pydantic_context_from_proto."""

    def test_update_state(self):
        """Test updating context state."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1"),
            state={"old": "value"},
        )
        proto = plugin_service_pb2.PluginContext()
        json_format.ParseDict({"new": "value"}, proto.state)

        update_pydantic_context_from_proto(ctx, proto)
        assert ctx.state["new"] == "value"
        assert "old" not in ctx.state

    def test_update_metadata(self):
        """Test updating context metadata."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1"),
            metadata={"old": "meta"},
        )
        proto = plugin_service_pb2.PluginContext()
        json_format.ParseDict({"new": "meta"}, proto.metadata)

        update_pydantic_context_from_proto(ctx, proto)
        assert ctx.metadata["new"] == "meta"

    def test_update_global_context_state(self):
        """Test updating global context state."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1", state={"old": "gc_state"}),
        )
        proto = plugin_service_pb2.PluginContext()
        json_format.ParseDict({"new": "gc_state"}, proto.global_context.state)

        update_pydantic_context_from_proto(ctx, proto)
        assert ctx.global_context.state["new"] == "gc_state"

    def test_empty_proto_clears_fields(self):
        """Test empty proto fields clear the context."""
        ctx = PluginContext(
            global_context=GlobalContext(request_id="req-1"),
            state={"existing": "value"},
            metadata={"existing": "meta"},
        )
        proto = plugin_service_pb2.PluginContext()

        update_pydantic_context_from_proto(ctx, proto)
        assert ctx.state == {}
        assert ctx.metadata == {}


class TestRoundTrip:
    """Tests for round-trip conversions."""

    def test_global_context_round_trip(self):
        """Test GlobalContext round-trip conversion."""
        original = GlobalContext(
            request_id="req-1",
            server_id="srv-1",
            tenant_id="tenant-1",
            user="admin",
            metadata={"key": "value"},
            state={"counter": 1},
        )
        proto = pydantic_global_context_to_proto(original)
        result = proto_global_context_to_pydantic(proto)

        assert result.request_id == original.request_id
        assert result.server_id == original.server_id
        assert result.tenant_id == original.tenant_id
        assert result.user == original.user
        assert result.metadata == original.metadata

    def test_plugin_context_round_trip(self):
        """Test PluginContext round-trip conversion."""
        original = PluginContext(
            global_context=GlobalContext(request_id="req-1", server_id="srv-1"),
            state={"key": "value"},
            metadata={"meta": "data"},
        )
        proto = pydantic_context_to_proto(original)
        result = proto_context_to_pydantic(proto)

        assert result.global_context.request_id == original.global_context.request_id
        assert result.state == original.state
        assert result.metadata == original.metadata

    def test_violation_round_trip(self):
        """Test PluginViolation round-trip conversion."""
        original = PluginViolation(
            reason="blocked",
            description="Content blocked by policy",
            code="BLOCKED",
            plugin_name="TestPlugin",
            mcp_error_code=-32600,
            details={"severity": "high"},
        )
        proto = pydantic_violation_to_proto(original)
        result = proto_violation_to_pydantic(proto)

        assert result.reason == original.reason
        assert result.description == original.description
        assert result.code == original.code
        assert result.plugin_name == original.plugin_name
        assert result.mcp_error_code == original.mcp_error_code
        assert result.details == original.details
