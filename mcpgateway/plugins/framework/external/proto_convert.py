# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/proto_convert.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Conversion utilities between Pydantic models and protobuf messages.

This module provides efficient conversion functions that use explicit protobuf
messages where possible, falling back to Struct for dynamic fields.
"""

from typing import Optional

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
from mcpgateway.plugins.framework.models import (
    GlobalContext as PydanticGlobalContext,
    PluginContext as PydanticPluginContext,
    PluginResult,
    PluginViolation as PydanticPluginViolation,
)


def pydantic_global_context_to_proto(ctx: PydanticGlobalContext) -> plugin_service_pb2.GlobalContext:
    """Convert Pydantic GlobalContext to protobuf GlobalContext.

    Args:
        ctx: The Pydantic GlobalContext model.

    Returns:
        The protobuf GlobalContext message.
    """
    proto_ctx = plugin_service_pb2.GlobalContext(
        request_id=ctx.request_id,
        server_id=ctx.server_id or "",
        tenant_id=ctx.tenant_id or "",
    )

    # Handle user field (can be string or dict)
    if ctx.user is not None:
        if isinstance(ctx.user, str):
            proto_ctx.user_string = ctx.user
        elif isinstance(ctx.user, dict):
            json_format.ParseDict(ctx.user, proto_ctx.user_struct)

    # Handle dynamic fields with Struct
    if ctx.metadata:
        json_format.ParseDict(ctx.metadata, proto_ctx.metadata)
    if ctx.state:
        json_format.ParseDict(ctx.state, proto_ctx.state)

    return proto_ctx


def proto_global_context_to_pydantic(proto_ctx: plugin_service_pb2.GlobalContext) -> PydanticGlobalContext:
    """Convert protobuf GlobalContext to Pydantic GlobalContext.

    Args:
        proto_ctx: The protobuf GlobalContext message.

    Returns:
        The Pydantic GlobalContext model.
    """
    # Handle user field
    user = None
    if proto_ctx.HasField("user_string"):
        user = proto_ctx.user_string
    elif proto_ctx.HasField("user_struct"):
        user = json_format.MessageToDict(proto_ctx.user_struct)

    return PydanticGlobalContext(
        request_id=proto_ctx.request_id,
        server_id=proto_ctx.server_id or None,
        tenant_id=proto_ctx.tenant_id or None,
        user=user,
        metadata=json_format.MessageToDict(proto_ctx.metadata) if proto_ctx.metadata.fields else {},
        state=json_format.MessageToDict(proto_ctx.state) if proto_ctx.state.fields else {},
    )


def pydantic_context_to_proto(ctx: PydanticPluginContext) -> plugin_service_pb2.PluginContext:
    """Convert Pydantic PluginContext to protobuf PluginContext.

    Args:
        ctx: The Pydantic PluginContext model.

    Returns:
        The protobuf PluginContext message.
    """
    proto_ctx = plugin_service_pb2.PluginContext(
        global_context=pydantic_global_context_to_proto(ctx.global_context),
    )

    if ctx.state:
        json_format.ParseDict(ctx.state, proto_ctx.state)
    if ctx.metadata:
        json_format.ParseDict(ctx.metadata, proto_ctx.metadata)

    return proto_ctx


def proto_context_to_pydantic(proto_ctx: plugin_service_pb2.PluginContext) -> PydanticPluginContext:
    """Convert protobuf PluginContext to Pydantic PluginContext.

    Args:
        proto_ctx: The protobuf PluginContext message.

    Returns:
        The Pydantic PluginContext model.
    """
    return PydanticPluginContext(
        global_context=proto_global_context_to_pydantic(proto_ctx.global_context),
        state=json_format.MessageToDict(proto_ctx.state) if proto_ctx.state.fields else {},
        metadata=json_format.MessageToDict(proto_ctx.metadata) if proto_ctx.metadata.fields else {},
    )


def proto_context_to_dict(proto_ctx: plugin_service_pb2.PluginContext) -> dict:
    """Convert protobuf PluginContext directly to dict (for server use).

    This avoids the intermediate Pydantic model when only a dict is needed.

    Args:
        proto_ctx: The protobuf PluginContext message.

    Returns:
        Dictionary representation of the context.
    """
    gc = proto_ctx.global_context

    # Handle user field
    user = None
    if gc.HasField("user_string"):
        user = gc.user_string
    elif gc.HasField("user_struct"):
        user = json_format.MessageToDict(gc.user_struct)

    return {
        "global_context": {
            "request_id": gc.request_id,
            "server_id": gc.server_id or None,
            "tenant_id": gc.tenant_id or None,
            "user": user,
            "metadata": json_format.MessageToDict(gc.metadata) if gc.metadata.fields else {},
            "state": json_format.MessageToDict(gc.state) if gc.state.fields else {},
        },
        "state": json_format.MessageToDict(proto_ctx.state) if proto_ctx.state.fields else {},
        "metadata": json_format.MessageToDict(proto_ctx.metadata) if proto_ctx.metadata.fields else {},
    }


def pydantic_violation_to_proto(violation: PydanticPluginViolation) -> plugin_service_pb2.PluginViolation:
    """Convert Pydantic PluginViolation to protobuf PluginViolation.

    Args:
        violation: The Pydantic PluginViolation model.

    Returns:
        The protobuf PluginViolation message.
    """
    proto_violation = plugin_service_pb2.PluginViolation(
        reason=violation.reason,
        description=violation.description,
        code=violation.code,
        plugin_name=violation.plugin_name or "",
        mcp_error_code=violation.mcp_error_code or 0,
    )

    if violation.details:
        json_format.ParseDict(violation.details, proto_violation.details)

    return proto_violation


def proto_violation_to_pydantic(proto_violation: plugin_service_pb2.PluginViolation) -> PydanticPluginViolation:
    """Convert protobuf PluginViolation to Pydantic PluginViolation.

    Args:
        proto_violation: The protobuf PluginViolation message.

    Returns:
        The Pydantic PluginViolation model.
    """
    violation = PydanticPluginViolation(
        reason=proto_violation.reason,
        description=proto_violation.description,
        code=proto_violation.code,
        details=json_format.MessageToDict(proto_violation.details) if proto_violation.details.fields else {},
        mcp_error_code=proto_violation.mcp_error_code if proto_violation.mcp_error_code else None,
    )
    if proto_violation.plugin_name:
        violation.plugin_name = proto_violation.plugin_name
    return violation


def pydantic_result_to_proto_base(result: PluginResult) -> plugin_service_pb2.PluginResultBase:
    """Convert common PluginResult fields to protobuf PluginResultBase.

    Args:
        result: The Pydantic PluginResult model.

    Returns:
        The protobuf PluginResultBase message with common fields.
    """
    proto_result = plugin_service_pb2.PluginResultBase(
        continue_processing=result.continue_processing,
    )

    if result.violation:
        proto_result.violation.CopyFrom(pydantic_violation_to_proto(result.violation))

    if result.metadata:
        json_format.ParseDict(result.metadata, proto_result.metadata)

    return proto_result


def update_pydantic_result_from_proto_base(
    result: PluginResult,
    proto_base: plugin_service_pb2.PluginResultBase,
) -> None:
    """Update a Pydantic PluginResult with values from PluginResultBase.

    Args:
        result: The Pydantic PluginResult to update.
        proto_base: The protobuf PluginResultBase with common fields.
    """
    result.continue_processing = proto_base.continue_processing

    if proto_base.HasField("violation"):
        result.violation = proto_violation_to_pydantic(proto_base.violation)

    if proto_base.metadata.fields:
        result.metadata = json_format.MessageToDict(proto_base.metadata)


def update_pydantic_context_from_proto(
    ctx: PydanticPluginContext,
    proto_ctx: plugin_service_pb2.PluginContext,
) -> None:
    """Update a Pydantic PluginContext in-place from protobuf PluginContext.

    Args:
        ctx: The Pydantic PluginContext to update.
        proto_ctx: The protobuf PluginContext with updated values.
    """
    ctx.state = json_format.MessageToDict(proto_ctx.state) if proto_ctx.state.fields else {}
    ctx.metadata = json_format.MessageToDict(proto_ctx.metadata) if proto_ctx.metadata.fields else {}

    # Update global context state
    if proto_ctx.global_context.state.fields:
        ctx.global_context.state = json_format.MessageToDict(proto_ctx.global_context.state)
