# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Location: ./mcpgateway/routers/a2a_gateway.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

A2A Gateway Router

Implements native A2A protocol endpoints for ContextForge. Provides a JSON-RPC 2.0
endpoint per registered A2A agent and agent card discovery.

Endpoints:
    POST /{prefix}/{agent_id}                               - JSON-RPC dispatcher
    GET  /{prefix}/{agent_id}/.well-known/agent-card.json   - Agent Card

The route prefix is configurable via A2A_GATEWAY_ROUTE_PREFIX (default: "a2a/agent").
"""

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Permissions
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.a2a_client_service import A2AClientService
from mcpgateway.services.a2a_gateway_service import (
    A2AGatewayAgentDisabledError,
    A2AGatewayAgentIncompatibleError,
    A2AGatewayAgentNotFoundError,
    A2AGatewayError,
    A2AGatewayService,
    fetch_downstream_agent_card,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_PARSE_ERROR,
    make_jsonrpc_error,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics import a2a_gateway_errors_counter, a2a_gateway_requests_counter, a2a_gateway_streams_active

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

_route_prefix = settings.a2a_gateway_route_prefix.strip("/")
router = APIRouter(prefix=f"/{_route_prefix}", tags=["A2A Gateway"])

# Service singletons
_gateway_service = A2AGatewayService()
_client_service = A2AClientService()

# Semaphore to enforce max concurrent SSE streams
_stream_semaphore = asyncio.Semaphore(settings.a2a_gateway_max_concurrent_streams)


def get_db():
    """Database session dependency for A2A gateway router."""
    # First-Party
    from mcpgateway.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_rpc_filter_context(request: Request, user: Any) -> tuple:
    """Extract user_email, token_teams, and is_admin for filtering.

    Mirrors the logic in mcpgateway.main._get_rpc_filter_context, including
    the security-critical empty-teams-disables-admin check.

    Args:
        request: FastAPI request object.
        user: User object from auth dependency.

    Returns:
        Tuple of (user_email, token_teams, is_admin).
    """
    # Extract user email
    if hasattr(user, "email"):
        user_email = getattr(user, "email", None)
    elif isinstance(user, dict):
        user_email = user.get("sub") or user.get("email")
    else:
        user_email = str(user) if user else None

    # Get normalized teams from verified token
    # First check request.state.token_teams (already normalized by auth.py)
    _not_set = object()
    token_teams = getattr(request.state, "token_teams", _not_set)
    if token_teams is _not_set or (token_teams is not None and not isinstance(token_teams, list)):
        # Fallback: use cached verified payload and call normalize_token_teams
        # First-Party
        from mcpgateway.auth import normalize_token_teams

        cached = getattr(request.state, "_jwt_verified_payload", None)
        if cached and isinstance(cached, tuple) and len(cached) == 2:
            _, payload = cached
            if payload:
                token_teams = normalize_token_teams(payload)
            else:
                token_teams = []
        else:
            token_teams = []  # No token info = public-only

    # Check if user is admin - MUST come from token, not DB user
    is_admin = False
    cached = getattr(request.state, "_jwt_verified_payload", None)
    if cached and isinstance(cached, tuple) and len(cached) == 2:
        _, payload = cached
        if payload:
            is_admin = payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)

    # If token has empty teams array (public-only token), admin bypass is disabled
    # This allows admins to create properly scoped tokens for restricted access
    if token_teams is not None and len(token_teams) == 0:
        is_admin = False

    return user_email, token_teams, is_admin


def _get_base_url(request: Request) -> str:
    """Get the gateway's base URL from the request.

    Uses request.base_url which includes root_path (set via APP_ROOT_PATH).
    Respects X-Forwarded-Proto for reverse proxy deployments.

    This follows the same pattern as update_url_protocol() in main.py and
    get_base_url_with_protocol() in routers/well_known.py.

    Args:
        request: FastAPI request object.

    Returns:
        Base URL string (including root_path) without trailing slash.
    """
    # Standard
    from urllib.parse import urlparse, urlunparse

    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        proto = forwarded_proto.split(",")[0].strip()
    else:
        proto = request.url.scheme

    parsed = urlparse(str(request.base_url))
    new_parsed = parsed._replace(scheme=proto)
    return str(urlunparse(new_parsed)).rstrip("/")


# A2A protocol headers that should always be forwarded to the downstream agent
_A2A_PROTOCOL_HEADERS = frozenset(
    {
        "a2a-version",
        "x-a2a-extensions",
        "accept",
    }
)


def _extract_forwarded_headers(request: Request, agent_passthrough_headers: Optional[List[str]] = None) -> Dict[str, str]:
    """Extract headers from the inbound request that should be forwarded to the downstream agent.

    Forwards A2A protocol headers (A2A-Version, X-A2A-Extensions, Accept) and any
    headers configured in the agent's passthrough_headers list.

    Args:
        request: The inbound FastAPI request.
        agent_passthrough_headers: Optional list of additional header names to forward.

    Returns:
        Dict of header name → value to forward.
    """
    forwarded: Dict[str, str] = {}
    forward_set = set(_A2A_PROTOCOL_HEADERS)
    if agent_passthrough_headers:
        forward_set.update(h.lower() for h in agent_passthrough_headers)

    for header_name in forward_set:
        value = request.headers.get(header_name)
        if value:
            forwarded[header_name] = value

    return forwarded


def _record_gateway_db_metrics(
    agent_id: str,
    start_time: datetime,
    success: bool,
    interaction_type: str,
    error_message: Optional[str] = None,
) -> None:
    """Record DB metrics and update last_interaction for a gateway call.

    Mirrors a2a_service.invoke_agent Phase 3: writes to A2AAgentMetric via
    the metrics buffer service and updates the agent's last_interaction timestamp.

    Args:
        agent_id: The agent's database ID.
        start_time: UTC datetime when the call started.
        success: Whether the call succeeded.
        interaction_type: JSON-RPC method name (e.g., "message/send").
        error_message: Error message if the call failed.
    """
    end_time = datetime.now(timezone.utc)
    response_time = (end_time - start_time).total_seconds()

    # Record to A2AAgentMetric table via buffer service
    try:
        # First-Party
        from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

        metrics_buffer = get_metrics_buffer_service()
        metrics_buffer.record_a2a_agent_metric_with_duration(
            a2a_agent_id=agent_id,
            response_time=response_time,
            success=success,
            interaction_type=interaction_type,
            error_message=error_message,
        )
    except Exception as metrics_error:
        logger.warning(f"Failed to record A2A gateway DB metrics for '{agent_id}': {metrics_error}")

    # Update last_interaction timestamp
    try:
        # First-Party
        from mcpgateway.db import A2AAgent, fresh_db_session
        from mcpgateway.db import get_for_update as get_for_update_fn  # pylint: disable=import-outside-toplevel

        with fresh_db_session() as ts_db:
            db_agent = get_for_update_fn(ts_db, A2AAgent, agent_id)
            if db_agent and getattr(db_agent, "enabled", False):
                db_agent.last_interaction = end_time
                ts_db.commit()
    except Exception as ts_error:
        logger.warning(f"Failed to update last_interaction for gateway agent '{agent_id}': {ts_error}")


@router.get("/{agent_id}/.well-known/agent-card.json", response_model=Dict[str, Any])
@require_permission(Permissions.A2A_GATEWAY_READ)
async def get_agent_card(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Get the A2A Agent Card for a registered agent.

    Returns an A2A-spec compliant Agent Card that points to this gateway's
    JSON-RPC endpoint. Clients use this for agent discovery.

    Args:
        agent_id: The agent's database ID.
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSONResponse with the Agent Card.

    Raises:
        HTTPException: If agent not found (404) or disabled (400).
    """
    try:
        user_email, token_teams, is_admin = _get_rpc_filter_context(request, user)

        # Admin bypass: set user_email=None so check_agent_visibility_access grants unrestricted access
        if is_admin and token_teams is None:
            user_email = None
        elif token_teams is None:
            token_teams = []  # Non-admin without teams = public-only

        agent, auth_headers_card, _ = _gateway_service.resolve_agent(db, agent_id, user_email, token_teams)
        endpoint_url = getattr(agent, "_gateway_endpoint_url", agent.endpoint_url)

        # Fetch the original card from the downstream agent
        original_card = await fetch_downstream_agent_card(endpoint_url, auth_headers_card, agent_id)

        base_url = _get_base_url(request)
        card = _gateway_service.generate_agent_card(agent, base_url, original_card)

        return JSONResponse(content=card, media_type="application/json")

    except A2AGatewayAgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    except A2AGatewayAgentDisabledError:
        raise HTTPException(status_code=400, detail=f"Agent is disabled: {agent_id}")
    except A2AGatewayAgentIncompatibleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating agent card for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{agent_id}", response_model=Dict[str, Any])
@require_permission(Permissions.A2A_GATEWAY_EXECUTE)
async def jsonrpc_endpoint(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """A2A JSON-RPC 2.0 endpoint for a registered agent.

    Receives JSON-RPC requests, validates them, resolves the target agent,
    and forwards the request to the downstream A2A agent. Applies the full
    gateway pipeline: auth, RBAC, token scoping, correlation IDs.

    Supported methods:
        - message/send: Send a message (non-streaming)
        - message/stream: Send a message (streaming SSE)
        - tasks/get: Get task by ID
        - tasks/list: List tasks with filtering and pagination
        - tasks/cancel: Cancel a task
        - tasks/resubscribe: Resubscribe to task events
        - tasks/pushNotificationConfig/*: Push notification config management
        - agent/getAuthenticatedExtendedCard: Get extended agent card

    Args:
        agent_id: The agent's database ID.
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSONResponse with the JSON-RPC response from the downstream agent.
    """
    # Parse request body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_PARSE_ERROR, "Invalid JSON"),
            status_code=200,  # JSON-RPC errors are returned with HTTP 200
        )

    request_id = body.get("id") if isinstance(body, dict) else None

    # Validate JSON-RPC structure
    validation_error = _gateway_service.validate_jsonrpc_request(body)
    if validation_error:
        return JSONResponse(content=validation_error, status_code=200)

    method = body["method"]

    # Handle agent/getAuthenticatedExtendedCard: forward to downstream, fall back to local card
    if method == "agent/getAuthenticatedExtendedCard":
        return await _handle_get_authenticated_card(agent_id, request, db, user, request_id, body)

    # Resolve agent with visibility/team scoping
    try:
        user_email, token_teams, is_admin = _get_rpc_filter_context(request, user)

        # Admin bypass: set user_email=None so check_agent_visibility_access grants unrestricted access
        if is_admin and token_teams is None:
            user_email = None
        elif token_teams is None:
            token_teams = []

        agent, auth_headers, auth_query_params_decrypted = _gateway_service.resolve_agent(db, agent_id, user_email, token_teams)

    except A2AGatewayAgentNotFoundError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent not found: {agent_id}", request_id),
            status_code=200,
        )
    except A2AGatewayAgentDisabledError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent is disabled: {agent_id}", request_id),
            status_code=200,
        )
    except A2AGatewayAgentIncompatibleError as e:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, str(e), request_id),
            status_code=200,
        )
    except A2AGatewayError as e:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, str(e), request_id),
            status_code=200,
        )

    # Get user context for logging
    user_id = None
    if isinstance(user, dict):
        user_id = str(user.get("id") or user.get("sub") or user_email)
    else:
        user_id = str(user) if user else None

    # Forward request to downstream agent
    endpoint_url = getattr(agent, "_gateway_endpoint_url", agent.endpoint_url)

    # Extract A2A protocol headers and passthrough headers from inbound request
    passthrough_list = getattr(agent, "passthrough_headers", None)
    forwarded_headers = _extract_forwarded_headers(request, passthrough_list)

    # Run pre-invoke plugin hook
    await _run_pre_invoke_hook(agent_id, method, body.get("params", {}), user_email, user_id)

    # Streaming methods return SSE event streams
    if _gateway_service.is_streaming_method(method):
        # Enforce max concurrent streams limit
        if _stream_semaphore.locked():
            # First-Party
            from mcpgateway.services.a2a_gateway_service import A2A_UNSUPPORTED_OPERATION  # pylint: disable=import-outside-toplevel

            return JSONResponse(
                content=make_jsonrpc_error(A2A_UNSUPPORTED_OPERATION, "Too many concurrent streams, try again later", request_id),
                status_code=200,
            )

        a2a_gateway_streams_active.labels(agent_id=agent_id).inc()

        async def _stream_with_metrics():
            stream_start = datetime.now(timezone.utc)
            stream_success = False
            await _stream_semaphore.acquire()
            try:
                async for event in _client_service.stream_jsonrpc(
                    endpoint_url=endpoint_url,
                    auth_headers=auth_headers,
                    body=body,
                    user_id=user_id,
                    user_email=user_email,
                    agent_id=agent_id,
                    auth_query_params_decrypted=auth_query_params_decrypted,
                    forwarded_headers=forwarded_headers,
                ):
                    yield event
                stream_success = True
                a2a_gateway_requests_counter.labels(agent_id=agent_id, method=method, status="success").inc()
            except Exception:
                a2a_gateway_requests_counter.labels(agent_id=agent_id, method=method, status="error").inc()
                a2a_gateway_errors_counter.labels(agent_id=agent_id, error_type="stream_error").inc()
                raise
            finally:
                _stream_semaphore.release()
                a2a_gateway_streams_active.labels(agent_id=agent_id).dec()
                _record_gateway_db_metrics(agent_id, stream_start, stream_success, method, None if stream_success else "stream_error")

        return StreamingResponse(
            _stream_with_metrics(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming methods return JSON-RPC responses
    call_start = datetime.now(timezone.utc)
    result = await _client_service.send_jsonrpc(
        endpoint_url=endpoint_url,
        auth_headers=auth_headers,
        body=body,
        user_id=user_id,
        user_email=user_email,
        agent_id=agent_id,
        auth_query_params_decrypted=auth_query_params_decrypted,
        forwarded_headers=forwarded_headers,
    )
    duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000

    # Track metrics
    is_error = "error" in result
    status = "error" if is_error else "success"
    a2a_gateway_requests_counter.labels(agent_id=agent_id, method=method, status=status).inc()
    if is_error:
        a2a_gateway_errors_counter.labels(agent_id=agent_id, error_type="downstream_error").inc()

    # Record DB metrics (matches invoke_agent's Phase 3)
    _record_gateway_db_metrics(agent_id, call_start, not is_error, method, result.get("error", {}).get("message") if is_error else None)

    # Run post-invoke plugin hook
    await _run_post_invoke_hook(agent_id, method, result, duration_ms, is_error)

    return JSONResponse(content=result, status_code=200)


async def _handle_get_authenticated_card(
    agent_id: str,
    request: Request,
    db: Session,
    user: Any,
    request_id: Any,
    body: Dict[str, Any],
) -> JSONResponse:
    """Handle agent/getAuthenticatedExtendedCard by forwarding to the downstream agent.

    Forwards the JSON-RPC request to the downstream A2A agent to get its
    authenticated extended card. Patches the ``url`` field in the response
    to point to the gateway endpoint. Falls back to a gateway-generated card
    if the downstream doesn't support this method.

    Args:
        agent_id: The agent's database ID.
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.
        request_id: JSON-RPC request ID.
        body: The original JSON-RPC request body.

    Returns:
        JSONResponse with agent card as JSON-RPC result.
    """
    try:
        user_email, token_teams, is_admin = _get_rpc_filter_context(request, user)

        # Admin bypass: set user_email=None so check_agent_visibility_access grants unrestricted access
        if is_admin and token_teams is None:
            user_email = None
        elif token_teams is None:
            token_teams = []

        agent, auth_headers_card, auth_qp = _gateway_service.resolve_agent(db, agent_id, user_email, token_teams)
        endpoint_url = getattr(agent, "_gateway_endpoint_url", agent.endpoint_url)
        base_url = _get_base_url(request)

        # Forward protocol headers to the downstream agent
        passthrough_list = getattr(agent, "passthrough_headers", None)
        fwd_headers = _extract_forwarded_headers(request, passthrough_list)

        # First-Party
        from mcpgateway.services.a2a_gateway_service import make_jsonrpc_response

        # Forward the request to the downstream agent
        result = await _client_service.send_jsonrpc(
            endpoint_url=endpoint_url,
            auth_headers=auth_headers_card,
            body=body,
            user_id=str(user) if user else None,
            user_email=user_email,
            agent_id=agent_id,
            auth_query_params_decrypted=auth_qp,
            forwarded_headers=fwd_headers,
        )

        # If the downstream returned a successful card, patch the url to point to the gateway
        if "result" in result and isinstance(result["result"], dict):
            # First-Party
            from mcpgateway.config import settings

            route_prefix = settings.a2a_gateway_route_prefix.strip("/")
            result["result"]["url"] = f"{base_url}/{route_prefix}/{agent_id}"
            return JSONResponse(content=result, status_code=200)

        # If the downstream returned an error (e.g., method not supported, not configured),
        # fall back to a gateway-generated card so clients still get useful metadata
        if "error" in result:
            logger.debug(f"Downstream does not support getAuthenticatedExtendedCard for {agent_id}, falling back to gateway card")
            original_card = await fetch_downstream_agent_card(endpoint_url, auth_headers_card, agent_id)
            card = _gateway_service.generate_agent_card(agent, base_url, original_card)
            return JSONResponse(content=make_jsonrpc_response(card, request_id), status_code=200)

        return JSONResponse(content=result, status_code=200)

    except A2AGatewayAgentNotFoundError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent not found: {agent_id}", request_id),
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Error handling getAuthenticatedExtendedCard for {agent_id}: {e}")
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, "Internal error", request_id),
            status_code=200,
        )


async def _run_pre_invoke_hook(
    agent_id: str,
    method: str,
    params: Dict[str, Any],
    user_email: Optional[str],
    user_id: Optional[str],
) -> None:
    """Run A2A gateway pre-invoke plugin hook if plugins are enabled."""
    try:
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.a2a_gateway import A2AGatewayHookType, A2AGatewayPreInvokePayload

        pm = get_plugin_manager()
        if pm and pm.has_hooks_for(A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE):
            # First-Party
            from mcpgateway.plugins.framework import GlobalContext

            global_context = GlobalContext()
            await pm.invoke_hook(
                A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE,
                payload=A2AGatewayPreInvokePayload(
                    agent_id=agent_id,
                    method=method,
                    params=params,
                    user_email=user_email,
                    user_id=user_id,
                ),
                global_context=global_context,
            )
    except Exception as e:
        logger.debug(f"A2A gateway pre-invoke hook error (non-fatal): {e}")


async def _run_post_invoke_hook(
    agent_id: str,
    method: str,
    result: Dict[str, Any],
    duration_ms: float,
    is_error: bool,
) -> None:
    """Run A2A gateway post-invoke plugin hook if plugins are enabled."""
    try:
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.a2a_gateway import A2AGatewayHookType, A2AGatewayPostInvokePayload

        pm = get_plugin_manager()
        if pm and pm.has_hooks_for(A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE):
            # First-Party
            from mcpgateway.plugins.framework import GlobalContext

            global_context = GlobalContext()
            await pm.invoke_hook(
                A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE,
                payload=A2AGatewayPostInvokePayload(
                    agent_id=agent_id,
                    method=method,
                    result=result,
                    duration_ms=duration_ms,
                    is_error=is_error,
                ),
                global_context=global_context,
            )
    except Exception as e:
        logger.debug(f"A2A gateway post-invoke hook error (non-fatal): {e}")
