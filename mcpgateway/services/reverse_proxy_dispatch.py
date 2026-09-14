# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_dispatch.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared dispatch helper for PROXIED-gateway JSON-RPC calls over reverse-proxy sessions.

Every proxied tool call, prompt get, and resource read walks the same state
machine: resolve the process-local connection for a stable gateway ID, emit
``mcp_call_started`` telemetry, send the request, then map failure modes
(session timeout, connection loss, JSON-RPC error response) onto the caller's
typed exception. This module owns that machine exactly once; the tool and
prompt services build their request params and map the response payload to
typed results around it, while the resource read's typed dispatch and its
read-path placeholder helper live here beside the dispatcher.
"""

# Standard
from dataclasses import dataclass
import time
from typing import Callable, Optional
import uuid

# Third-Party
from mcp import types
from pydantic import ValidationError

# First-Party
from mcpgateway.common.models import BlobResourceContents, ResourceContent, ResourceContents, TextResourceContents
from mcpgateway.config import settings
from mcpgateway.db import Resource as DbResource
from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, is_internal_proxied_gateway, JsonRpcErrorResponse, JsonRpcRequest, ResponseMessage
from mcpgateway.services.reverse_proxy_relay import RelayUnavailableError
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionNotFoundError, get_reverse_proxy_session_manager, StableGatewayId
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.correlation_id import get_correlation_id

structured_logger = get_structured_logger("reverse_proxy_dispatch")

# Per-noun metadata key carrying the upstream item name in telemetry payloads,
# matching the key each service family has always emitted.
_NAME_METADATA_KEYS = {"tool": "tool_name", "prompt": "prompt_name", "resource": "resource_uri"}


@dataclass(frozen=True)
class ProxiedCallTelemetry:
    """Labels for the structured telemetry emitted around one proxied RPC.

    Attributes:
        component: Emitting service component name (e.g. ``"tool_service"``).
        noun: Caller family — ``"tool"`` | ``"prompt"`` | ``"resource"`` —
            used in event names (``{noun}_timeout``) and log messages.
        name: Original upstream item name (tool/prompt name or resource URI).
        gateway_id: Stable gateway identifier the call is dispatched to.
    """

    component: str
    noun: str
    name: str
    gateway_id: str


async def dispatch_proxied_rpc(
    stable_id: StableGatewayId,
    request: JsonRpcRequest,
    *,
    timeout_seconds: float,
    error_factory: Callable[[str], Exception],
    telemetry: ProxiedCallTelemetry,
    auth: DownstreamAuth | None = None,
) -> ResponseMessage:
    """Send one JSON-RPC request over the owning reverse-proxy session.

    Emits mcp_call_started / mcp_call_failed (or <noun>_timeout) structured
    telemetry, maps connection loss and JSON-RPC errors to the caller's typed
    exception via ``error_factory``, and never includes credential material
    or peer free text in exceptions or telemetry (MCP error code only).

    Args:
        stable_id: Stable gateway identifier used to resolve the live connection.
        request: Fully built outbound JSON-RPC request (params are caller-specific).
        timeout_seconds: Per-request timeout budget; policy is chosen by the caller.
        error_factory: Builds the caller's typed exception from a safe message.
        telemetry: Labels for the structured telemetry emitted around the call.
        auth: Optional stored gateway credentials forwarded downstream; never logged.

    Returns:
        The peer's response frame, guaranteed to carry a success payload.

    Raises:
        Exception: ``error_factory`` output when no live connection exists for
            the gateway, the connection drops mid-call, the distributed relay
            is unavailable, or the peer answers with a JSON-RPC error
            (surfaced as the MCP error code only).
    """
    session_manager = None
    connection_id = None
    if not settings.mcpgateway_reverse_proxy_distributed_enabled:
        session_manager = await get_reverse_proxy_session_manager()
        connection_id = session_manager.resolve_connection_id(stable_id)
        if connection_id is None:
            raise error_factory(f"No active reverse-proxy connection for gateway '{stable_id}'")

    correlation_id = get_correlation_id()
    mcp_start_time = time.time()
    base_metadata = {_NAME_METADATA_KEYS[telemetry.noun]: telemetry.name, "gateway_id": telemetry.gateway_id, "transport": "proxied"}
    structured_logger.log(
        level="INFO",
        message=f"MCP {telemetry.noun} call started: {telemetry.name}",
        component=telemetry.component,
        correlation_id=correlation_id,
        metadata={"event": "mcp_call_started", **base_metadata},
    )
    try:
        if settings.mcpgateway_reverse_proxy_distributed_enabled:
            from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

            relay = await get_reverse_proxy_relay()
            response = await relay.send_request_by_stable_id(stable_id, request, timeout_seconds=timeout_seconds, auth=auth)
        else:
            if session_manager is None or connection_id is None:
                raise error_factory(f"No active reverse-proxy connection for gateway '{stable_id}'")
            response = await session_manager.send_request(connection_id, request, timeout_seconds=timeout_seconds, auth=auth)
    except RelayUnavailableError:
        raise error_factory(f"Reverse-proxy relay unavailable for gateway '{telemetry.gateway_id}'") from None
    except TimeoutError:
        mcp_duration_ms = (time.time() - mcp_start_time) * 1000
        structured_logger.log(
            level="WARNING",
            message=f"MCP proxied {telemetry.noun} call timed out: {telemetry.name}",
            component=telemetry.component,
            correlation_id=correlation_id,
            duration_ms=mcp_duration_ms,
            metadata={"event": f"{telemetry.noun}_timeout", **base_metadata, "timeout_seconds": timeout_seconds},
        )
        raise
    except (ConnectionClosedError, ConnectionNotFoundError) as conn_err:
        mcp_duration_ms = (time.time() - mcp_start_time) * 1000
        structured_logger.log(
            level="ERROR",
            message=f"MCP {telemetry.noun} call failed: {telemetry.name}",
            component=telemetry.component,
            correlation_id=correlation_id,
            duration_ms=mcp_duration_ms,
            error_details={"error_type": type(conn_err).__name__, "error_message": str(conn_err)},
            metadata={"event": "mcp_call_failed", **base_metadata},
        )
        raise error_factory(f"Reverse-proxy connection for gateway '{telemetry.gateway_id}' failed: {conn_err}") from conn_err

    if isinstance(response.payload, JsonRpcErrorResponse):
        mcp_error = response.payload.error
        mcp_duration_ms = (time.time() - mcp_start_time) * 1000
        structured_logger.log(
            level="ERROR",
            message=f"MCP {telemetry.noun} call failed: {telemetry.name}",
            component=telemetry.component,
            correlation_id=correlation_id,
            duration_ms=mcp_duration_ms,
            error_details={"error_type": "JsonRpcErrorResponse", "error_message": f"MCP error {mcp_error.code}"},
            metadata={"event": "mcp_call_failed", **base_metadata},
        )
        raise error_factory(f"MCP error {mcp_error.code}")

    return response


def _resource_content_for_read(resource: DbResource) -> ResourceContent:
    """Return cached content or a dispatch placeholder for an internal PROXIED row."""
    gateway = resource.gateway
    if is_internal_proxied_gateway(gateway):
        return ResourceContent(type="resource", id=str(resource.id), uri=resource.uri, mimeType=resource.mime_type, text="", _meta=None)
    return resource.content


async def _read_reverse_proxied_resource(
    gateway_id_str: str,
    uri: str,
    effective_timeout: float,
    downstream_auth: Optional[DownstreamAuth] = None,
) -> ResourceContents:
    """Dispatch ``resources/read`` to a PROXIED gateway over its reverse-proxy session.

    The request resolves the process-local connection for the persisted stable
    gateway ID and sends the persisted upstream URI downstream (or the
    substituted request URI for template-derived reads) — never a namespaced
    public catalog name. When the gateway row carries stored auth material,
    ``downstream_auth`` rides the request envelope as ``authentication``/
    ``authType`` for the client to apply downstream; when ``None`` those members
    are omitted. The material is never logged.

    Args:
        gateway_id_str: Stable gateway identifier used to resolve the live connection.
        uri: Upstream resource URI sent as ``params.uri``.
        effective_timeout: Per-request timeout in seconds.
        downstream_auth: Optional stored gateway credentials to forward downstream.

    Returns:
        The typed first ``result.contents`` entry, preserving blob/text and MIME metadata.

    Raises:
        ResourceError: If no live connection exists for the gateway, the
            connection drops mid-read, the read exceeds ``effective_timeout``,
            the downstream server returns a JSON-RPC error, or the upstream
            result carries no contents.
        ValidationError: If the upstream ``resources/read`` result is malformed.
    """
    # First-Party
    from mcpgateway.services.resource_service import ResourceError  # pylint: disable=import-outside-toplevel  # lazy: resource_service imports this module

    request_payload = JsonRpcRequest(jsonrpc="2.0", id=uuid.uuid4().hex, method="resources/read", params={"uri": uri})

    correlation_id = get_correlation_id()
    mcp_start_time = time.time()
    telemetry = ProxiedCallTelemetry(component="resource_service", noun="resource", name=uri, gateway_id=gateway_id_str)
    try:
        # Timeout policy: resource reads use the health-check budget — the sole caller
        # passes float(settings.health_check_timeout), matching the SSE/streamable branches.
        response = await dispatch_proxied_rpc(
            StableGatewayId(gateway_id_str),
            request_payload,
            timeout_seconds=effective_timeout,
            error_factory=ResourceError,
            telemetry=telemetry,
            auth=downstream_auth,
        )
    except TimeoutError as timeout_err:
        raise ResourceError(f"Resource read timed out after {effective_timeout}s") from timeout_err

    try:
        validated_result = types.ReadResourceResult.model_validate(response.payload.result)
    except ValidationError as validation_err:
        mcp_duration_ms = (time.time() - mcp_start_time) * 1000
        structured_logger.log(
            level="ERROR",
            message=f"MCP resource read failed: {uri}",
            component="resource_service",
            correlation_id=correlation_id,
            duration_ms=mcp_duration_ms,
            error_details={"error_type": "ValidationError", "error_message": "malformed upstream resources/read result"},
            metadata={"event": "mcp_call_failed", "resource_uri": uri, "gateway_id": gateway_id_str, "transport": "proxied"},
        )
        raise validation_err

    if not validated_result.contents:
        mcp_duration_ms = (time.time() - mcp_start_time) * 1000
        structured_logger.log(
            level="ERROR",
            message=f"MCP resource read failed: {uri}",
            component="resource_service",
            correlation_id=correlation_id,
            duration_ms=mcp_duration_ms,
            error_details={"error_type": "EmptyContentsError", "error_message": "upstream resources/read result carried no contents"},
            metadata={"event": "mcp_call_failed", "resource_uri": uri, "gateway_id": gateway_id_str, "transport": "proxied"},
        )
        raise ResourceError(f"Upstream resources/read for gateway '{gateway_id_str}' returned no contents")

    first_content = validated_result.contents[0]
    content_uri = str(first_content.uri)
    content_mime_type = first_content.mimeType
    content_meta = first_content.meta
    if isinstance(first_content, types.TextResourceContents):
        content = TextResourceContents(uri=content_uri, mimeType=content_mime_type, text=first_content.text, _meta=content_meta)
    else:
        content = BlobResourceContents(uri=content_uri, mimeType=content_mime_type, blob=first_content.blob, _meta=content_meta)

    mcp_duration_ms = (time.time() - mcp_start_time) * 1000
    structured_logger.log(
        level="INFO",
        message=f"MCP resource read completed: {uri}",
        component="resource_service",
        correlation_id=correlation_id,
        duration_ms=mcp_duration_ms,
        metadata={"event": "mcp_call_completed", "resource_uri": uri, "gateway_id": gateway_id_str, "transport": "proxied", "success": True},
    )
    return content
