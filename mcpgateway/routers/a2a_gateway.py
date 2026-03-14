# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Location: ./mcpgateway/routers/a2a_gateway.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

A2A Gateway Router

Implements native A2A protocol endpoints for ContextForge. Provides a JSON-RPC 2.0
endpoint per registered A2A agent and agent card discovery.

Endpoints:
    POST /a2a/v1/{agent_slug}                               - JSON-RPC dispatcher
    GET  /a2a/v1/{agent_slug}/.well-known/agent-card.json   - Agent Card
"""

# Standard
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
from mcpgateway.services.a2a_gateway_service import (
    A2AGatewayAgentDisabledError,
    A2AGatewayAgentNotFoundError,
    A2AGatewayError,
    A2AGatewayService,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_PARSE_ERROR,
    make_jsonrpc_error,
)
from mcpgateway.services.a2a_client_service import A2AClientService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics import a2a_gateway_errors_counter, a2a_gateway_requests_counter, a2a_gateway_streams_active

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/a2a/v1", tags=["A2A Gateway"])

# Service singletons
_gateway_service = A2AGatewayService()
_client_service = A2AClientService()


def get_db():
    """Database session dependency for A2A gateway router."""
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

    Replicates the pattern from mcpgateway.main._get_rpc_filter_context.

    Args:
        request: FastAPI request object.
        user: User object from auth dependency.

    Returns:
        Tuple of (user_email, token_teams, is_admin).
    """
    if hasattr(user, "email"):
        user_email = getattr(user, "email", None)
    elif isinstance(user, dict):
        user_email = user.get("sub") or user.get("email")
    else:
        user_email = str(user) if user else None

    # Get normalized teams from verified token
    _not_set = object()
    token_teams = getattr(request.state, "token_teams", _not_set)
    if token_teams is _not_set or (token_teams is not None and not isinstance(token_teams, list)):
        # Fallback: try to get from JWT payload
        from mcpgateway.auth import normalize_token_teams

        cached = getattr(request.state, "_jwt_verified_payload", None)
        if cached:
            _, payload = cached
            token_teams = normalize_token_teams(payload.get("teams"))
        else:
            token_teams = []  # No token info = public-only

    # Check admin from token payload
    is_admin = False
    cached = getattr(request.state, "_jwt_verified_payload", None)
    if cached:
        _, payload = cached
        is_admin = bool(payload.get("is_admin", False))

    return user_email, token_teams, is_admin


def _get_base_url(request: Request) -> str:
    """Get the gateway's base URL from the request.

    Respects X-Forwarded-Proto for reverse proxy deployments.

    Args:
        request: FastAPI request object.

    Returns:
        Base URL string without trailing slash.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        proto = forwarded_proto.split(",")[0].strip()
    else:
        proto = request.url.scheme

    host = request.headers.get("host", request.url.netloc)
    return f"{proto}://{host}"


@router.get("/{agent_slug}/.well-known/agent-card.json", response_model=Dict[str, Any])
@require_permission(Permissions.A2A_GATEWAY_READ)
async def get_agent_card(
    agent_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """Get the A2A Agent Card for a registered agent.

    Returns an A2A-spec compliant Agent Card that points to this gateway's
    JSON-RPC endpoint. Clients use this for agent discovery.

    Args:
        agent_slug: The agent's URL slug.
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

        # Admin bypass for token_teams
        if is_admin and token_teams is None:
            pass  # Unrestricted
        elif token_teams is None:
            token_teams = []  # Non-admin without teams = public-only

        agent, _ = _gateway_service.resolve_agent(db, agent_slug, user_email, token_teams)
        base_url = _get_base_url(request)
        card = _gateway_service.generate_agent_card(agent, base_url)

        return JSONResponse(content=card, media_type="application/json")

    except A2AGatewayAgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_slug}")
    except A2AGatewayAgentDisabledError:
        raise HTTPException(status_code=400, detail=f"Agent is disabled: {agent_slug}")
    except Exception as e:
        logger.error(f"Error generating agent card for {agent_slug}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{agent_slug}", response_model=Dict[str, Any])
@require_permission(Permissions.A2A_GATEWAY_EXECUTE)
async def jsonrpc_endpoint(
    agent_slug: str,
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
        - message/stream: Send a message (streaming SSE) [Phase 2]
        - tasks/get: Get task by ID
        - tasks/cancel: Cancel a task
        - tasks/resubscribe: Resubscribe to task events [Phase 2]
        - tasks/pushNotificationConfig/*: Push notification config management
        - agent/getAuthenticatedExtendedCard: Get extended agent card

    Args:
        agent_slug: The agent's URL slug.
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

    # Handle agent/getAuthenticatedExtendedCard locally (no downstream call)
    if method == "agent/getAuthenticatedExtendedCard":
        return await _handle_get_authenticated_card(agent_slug, request, db, user, request_id)

    # Resolve agent with visibility/team scoping
    try:
        user_email, token_teams, is_admin = _get_rpc_filter_context(request, user)

        if is_admin and token_teams is None:
            pass
        elif token_teams is None:
            token_teams = []

        agent, auth_headers = _gateway_service.resolve_agent(db, agent_slug, user_email, token_teams)

    except A2AGatewayAgentNotFoundError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent not found: {agent_slug}", request_id),
            status_code=200,
        )
    except A2AGatewayAgentDisabledError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent is disabled: {agent_slug}", request_id),
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

    # Run pre-invoke plugin hook
    await _run_pre_invoke_hook(agent_slug, method, body.get("params", {}), user_email, user_id)

    # Streaming methods return SSE event streams
    if _gateway_service.is_streaming_method(method):
        a2a_gateway_streams_active.labels(agent_slug=agent_slug).inc()

        async def _stream_with_metrics():
            try:
                async for event in _client_service.stream_jsonrpc(
                    endpoint_url=endpoint_url,
                    auth_headers=auth_headers,
                    body=body,
                    user_id=user_id,
                    user_email=user_email,
                    agent_slug=agent_slug,
                ):
                    yield event
                a2a_gateway_requests_counter.labels(agent_slug=agent_slug, method=method, status="success").inc()
            except Exception:
                a2a_gateway_requests_counter.labels(agent_slug=agent_slug, method=method, status="error").inc()
                a2a_gateway_errors_counter.labels(agent_slug=agent_slug, error_type="stream_error").inc()
                raise
            finally:
                a2a_gateway_streams_active.labels(agent_slug=agent_slug).dec()

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
        agent_slug=agent_slug,
    )
    duration_ms = (datetime.now(timezone.utc) - call_start).total_seconds() * 1000

    # Track metrics
    is_error = "error" in result
    status = "error" if is_error else "success"
    a2a_gateway_requests_counter.labels(agent_slug=agent_slug, method=method, status=status).inc()
    if is_error:
        a2a_gateway_errors_counter.labels(agent_slug=agent_slug, error_type="downstream_error").inc()

    # Run post-invoke plugin hook
    await _run_post_invoke_hook(agent_slug, method, result, duration_ms, is_error)

    return JSONResponse(content=result, status_code=200)


async def _handle_get_authenticated_card(
    agent_slug: str,
    request: Request,
    db: Session,
    user: Any,
    request_id: Any,
) -> JSONResponse:
    """Handle agent/getAuthenticatedExtendedCard locally.

    Returns the gateway-generated agent card with extended info.

    Args:
        agent_slug: The agent's URL slug.
        request: FastAPI request object.
        db: Database session.
        user: Authenticated user.
        request_id: JSON-RPC request ID.

    Returns:
        JSONResponse with agent card as JSON-RPC result.
    """
    try:
        user_email, token_teams, is_admin = _get_rpc_filter_context(request, user)

        if is_admin and token_teams is None:
            pass
        elif token_teams is None:
            token_teams = []

        agent, _ = _gateway_service.resolve_agent(db, agent_slug, user_email, token_teams)
        base_url = _get_base_url(request)
        card = _gateway_service.generate_agent_card(agent, base_url)

        from mcpgateway.services.a2a_gateway_service import make_jsonrpc_response

        return JSONResponse(content=make_jsonrpc_response(card, request_id), status_code=200)

    except A2AGatewayAgentNotFoundError:
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, f"Agent not found: {agent_slug}", request_id),
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Error handling getAuthenticatedExtendedCard for {agent_slug}: {e}")
        return JSONResponse(
            content=make_jsonrpc_error(JSONRPC_INTERNAL_ERROR, "Internal error", request_id),
            status_code=200,
        )


async def _run_pre_invoke_hook(
    agent_slug: str,
    method: str,
    params: Dict[str, Any],
    user_email: Optional[str],
    user_id: Optional[str],
) -> None:
    """Run A2A gateway pre-invoke plugin hook if plugins are enabled."""
    try:
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.a2a_gateway import A2AGatewayHookType, A2AGatewayPreInvokePayload

        pm = get_plugin_manager()
        if pm and pm.has_hooks_for(A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE):
            from mcpgateway.plugins.framework import GlobalContext

            global_context = GlobalContext()
            await pm.invoke_hook(
                A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE,
                payload=A2AGatewayPreInvokePayload(
                    agent_slug=agent_slug,
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
    agent_slug: str,
    method: str,
    result: Dict[str, Any],
    duration_ms: float,
    is_error: bool,
) -> None:
    """Run A2A gateway post-invoke plugin hook if plugins are enabled."""
    try:
        from mcpgateway.plugins.framework import get_plugin_manager
        from mcpgateway.plugins.framework.hooks.a2a_gateway import A2AGatewayHookType, A2AGatewayPostInvokePayload

        pm = get_plugin_manager()
        if pm and pm.has_hooks_for(A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE):
            from mcpgateway.plugins.framework import GlobalContext

            global_context = GlobalContext()
            await pm.invoke_hook(
                A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE,
                payload=A2AGatewayPostInvokePayload(
                    agent_slug=agent_slug,
                    method=method,
                    result=result,
                    duration_ms=duration_ms,
                    is_error=is_error,
                ),
                global_context=global_context,
            )
    except Exception as e:
        logger.debug(f"A2A gateway post-invoke hook error (non-fatal): {e}")
