# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared A2A transport dispatch utilities.

Centralizes the auth resolution and transport dispatch logic used by both
a2a_service.invoke_agent() and tool_service (A2A tool invocation paths).
Callers handle response parsing, error handling, plugin hooks, logging,
and metrics recording — this module only covers the common dispatch core.
"""

# Standard
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class A2AAuthContext:
    """Result of resolving A2A agent authentication.

    Attributes:
        headers: Auth headers to include in the request.
        endpoint_url: Endpoint URL, possibly modified with query param auth.
        query_params_decrypted: Decrypted query params (for URL sanitization in logs).
    """

    headers: Dict[str, str] = field(default_factory=dict)
    endpoint_url: str = ""
    query_params_decrypted: Optional[Dict[str, str]] = None


@dataclass
class A2ADispatchResult:
    """Result of an A2A transport dispatch.

    Exactly one of http_response or grpc_data will be set, depending on
    the transport used.

    Attributes:
        http_response: HTTP response for HTTP-based transports.
        grpc_data: Response data for gRPC transport.
        transport: The transport type used for the dispatch.
    """

    http_response: Any = None  # httpx.Response when set
    grpc_data: Any = None
    transport: str = ""


async def resolve_a2a_auth(
    endpoint_url: str,
    auth_type: Optional[str],
    auth_value: Any,
    auth_query_params: Optional[Dict[str, Any]],
    oauth_config: Optional[Dict[str, Any]],
    agent_name: str = "",
    error_cls: type = Exception,
    fallback_raw_auth: bool = False,
) -> A2AAuthContext:
    """Resolve A2A agent authentication into headers and URL modifications.

    Handles all auth types: query_param, basic, bearer, authheaders,
    api_key, token, and oauth.

    Args:
        endpoint_url: Base endpoint URL of the agent.
        auth_type: Authentication type (basic, bearer, oauth, etc.).
        auth_value: Encrypted auth value (string or dict).
        auth_query_params: Encrypted query parameter auth config.
        oauth_config: OAuth configuration dict.
        agent_name: Agent name for error messages.
        error_cls: Exception class to raise on auth failures.
        fallback_raw_auth: If True, fall back to using the raw auth_value
            when decryption fails (for tool_service backward compat).
            If False, raise error_cls on decryption failure.

    Returns:
        A2AAuthContext with resolved headers and potentially modified URL.
    """
    # First-Party
    from mcpgateway.utils.services_auth import decode_auth  # pylint: disable=import-outside-toplevel

    ctx = A2AAuthContext(endpoint_url=endpoint_url)

    # Handle query_param auth - decrypt and apply to URL.
    if auth_type == "query_param" and auth_query_params:
        # First-Party
        from mcpgateway.utils.url_auth import apply_query_param_auth  # pylint: disable=import-outside-toplevel

        ctx.query_params_decrypted = {}
        for param_key, encrypted_value in auth_query_params.items():
            if not encrypted_value:
                continue
            try:
                decrypted = decode_auth(encrypted_value)
                ctx.query_params_decrypted[param_key] = decrypted.get(param_key, "")
            except Exception:
                logger.warning("Failed to decrypt query param '%s' for A2A agent '%s'", param_key, agent_name)

        if ctx.query_params_decrypted:
            ctx.endpoint_url = apply_query_param_auth(ctx.endpoint_url, ctx.query_params_decrypted)

    # Decode auth_value for header-based auth types.
    if auth_type in ("basic", "bearer", "authheaders") and auth_value:
        if isinstance(auth_value, str):
            try:
                decoded_headers = decode_auth(auth_value)
                ctx.headers = {str(k): str(v) for k, v in decoded_headers.items() if k and v is not None}
            except Exception as e:
                if fallback_raw_auth:
                    # Backward compatibility: use raw auth_value as-is.
                    raw_auth = auth_value.strip()
                    if auth_type == "bearer" and raw_auth:
                        ctx.headers = {"Authorization": raw_auth if raw_auth.lower().startswith("bearer ") else f"Bearer {raw_auth}"}
                    elif auth_type == "basic" and raw_auth:
                        ctx.headers = {"Authorization": raw_auth if raw_auth.lower().startswith("basic ") else f"Basic {raw_auth}"}
                    else:
                        raise error_cls(f"Failed to decrypt authentication for agent '{agent_name}': {e}") from e
                else:
                    raise error_cls(f"Failed to decrypt authentication for agent '{agent_name}': {e}") from e
        elif isinstance(auth_value, dict):
            ctx.headers = {str(k): str(v) for k, v in auth_value.items() if k and v is not None}
    elif auth_type in ("api_key", "token") and isinstance(auth_value, str) and auth_value:
        ctx.headers = {"Authorization": f"Bearer {auth_value}"}

    # OAuth token acquisition.
    if auth_type == "oauth" and oauth_config:
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager  # pylint: disable=import-outside-toplevel

        try:
            access_token = await OAuthManager().get_access_token(oauth_config)
        except Exception as e:
            raise error_cls(f"OAuth authentication failed for agent '{agent_name}': {e}") from e
        ctx.headers["Authorization"] = f"Bearer {access_token}"

    return ctx


def prepare_rpc_params(
    parameters: Any,
    normalized_agent_type: str,
    normalize_parts_fn: Optional[Callable] = None,
) -> Tuple[str, Any]:
    """Extract RPC method and params from raw parameters.

    Also wraps flat ``{"query": "..."}`` payloads into a proper A2A message
    for spec-compliant transports.

    Args:
        parameters: Raw parameters dict or other value.
        normalized_agent_type: Normalized agent type string.
        normalize_parts_fn: Optional function to normalize message parts.

    Returns:
        Tuple of (rpc_method, rpc_params).
    """
    rpc_method = parameters.get("method", "SendMessage") if isinstance(parameters, dict) else "SendMessage"
    rpc_params: Any = parameters.get("params", parameters) if isinstance(parameters, dict) else parameters

    # Convenience: wrap a flat {"query": "..."} into an A2A message.
    if (
        normalized_agent_type in ("a2a-jsonrpc", "a2a-rest", "a2a-grpc")
        and isinstance(parameters, dict)
        and isinstance(parameters.get("query"), str)
        and "params" not in parameters
        and "message" not in parameters
    ):
        message_id = f"tool-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        rpc_params = {
            "message": {
                "messageId": message_id,
                "role": "user",
                "parts": [{"text": parameters["query"]}],
            }
        }

    if normalize_parts_fn and isinstance(rpc_params, dict):
        rpc_params = normalize_parts_fn(rpc_params)

    return rpc_method, rpc_params


async def dispatch_a2a_transport(
    endpoint_url: str,
    normalized_agent_type: str,
    rpc_method: str,
    rpc_params: Any,
    headers: Dict[str, str],
    auth_headers: Dict[str, str],
    http_client: Any,
    *,
    parameters: Optional[Any] = None,
    interaction_type: str = "query",
    protocol_version: Optional[str] = None,
    correlation_id: Optional[str] = None,
    build_rest_request_fn: Optional[Callable] = None,
    invoke_grpc_fn: Optional[Callable] = None,
    timeout: Optional[float] = None,
) -> A2ADispatchResult:
    """Dispatch an A2A request to the appropriate transport.

    Core transport selection shared by a2a_service and tool_service.
    Callers handle response parsing, error wrapping, logging, and metrics.

    Args:
        endpoint_url: Target endpoint URL (already auth-modified if needed).
        normalized_agent_type: One of a2a-jsonrpc, a2a-rest, a2a-grpc,
            rest-passthrough, custom.
        rpc_method: JSON-RPC method name (e.g. SendMessage).
        rpc_params: Request parameters/payload.
        headers: Full merged headers (Content-Type + auth + correlation).
        auth_headers: Auth-only headers (for gRPC metadata).
        http_client: httpx.AsyncClient instance.
        parameters: Original raw parameters (for passthrough/custom).
        interaction_type: Interaction type for custom transport.
        protocol_version: Protocol version for custom transport.
        correlation_id: Request correlation ID (for gRPC metadata).
        build_rest_request_fn: Function to build REST request from RPC method.
        invoke_grpc_fn: Async function to invoke gRPC transport.
        timeout: Optional timeout in seconds for the HTTP call.

    Returns:
        A2ADispatchResult with either http_response or grpc_data set.

    Raises:
        Exception: If the transport type is unsupported.
    """
    import asyncio  # pylint: disable=import-outside-toplevel

    result = A2ADispatchResult(transport=normalized_agent_type)

    if normalized_agent_type == "a2a-jsonrpc":
        request_data = {
            "jsonrpc": "2.0",
            "method": rpc_method,
            "params": rpc_params,
            "id": str(uuid.uuid4()),
        }
        coro = http_client.post(endpoint_url, json=request_data, headers=headers)
        result.http_response = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)

    elif normalized_agent_type == "a2a-rest":
        if not build_rest_request_fn:
            raise ValueError("build_rest_request_fn required for a2a-rest transport")
        rest_method, rest_url, rest_json, rest_query = build_rest_request_fn(endpoint_url, rpc_method, rpc_params)
        coro = http_client.request(rest_method, rest_url, json=rest_json, params=rest_query, headers=headers)
        result.http_response = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)

    elif normalized_agent_type == "rest-passthrough":
        payload = parameters if parameters is not None else rpc_params
        coro = http_client.post(endpoint_url, json=payload, headers=headers)
        result.http_response = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)

    elif normalized_agent_type == "custom":
        params = parameters if isinstance(parameters, dict) else {}
        request_data = {
            "interaction_type": params.get("interaction_type", interaction_type),
            "parameters": params,
            "protocol_version": protocol_version,
        }
        coro = http_client.post(endpoint_url, json=request_data, headers=headers)
        result.http_response = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)

    elif normalized_agent_type == "a2a-grpc":
        if not invoke_grpc_fn:
            raise ValueError("invoke_grpc_fn required for a2a-grpc transport")
        coro = invoke_grpc_fn(
            endpoint_url=endpoint_url,
            parameters={"method": rpc_method, "params": rpc_params},
            interaction_type=interaction_type,
            auth_headers=auth_headers,
            correlation_id=correlation_id,
        )
        result.grpc_data = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)

    else:
        raise ValueError(f"Unsupported A2A transport: {normalized_agent_type}")

    return result


def build_dispatch_headers(
    auth_headers: Dict[str, str],
    normalized_agent_type: str,
    a2a_version_header: str,
    correlation_id: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build the full headers dict for an A2A dispatch.

    Merges Content-Type, auth headers, A2A-Version (for REST), correlation ID,
    and any extra headers.

    Args:
        auth_headers: Resolved auth headers.
        normalized_agent_type: Transport type (for conditional A2A-Version).
        a2a_version_header: A2A protocol version string.
        correlation_id: Optional correlation ID.
        extra_headers: Optional additional headers to merge.

    Returns:
        Complete headers dict ready for dispatch.
    """
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    headers.update(auth_headers)

    if normalized_agent_type == "a2a-rest":
        headers["A2A-Version"] = a2a_version_header

    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    if extra_headers:
        headers.update(extra_headers)

    return headers
