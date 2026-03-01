# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A2A Server Router — exposes virtual servers as A2A v1.0 protocol endpoints.

Mounts under ``/servers`` (applied by ``main.py``), providing:

- Agent Card discovery at ``/{server_id}/a2a/v1/card``
- JSON-RPC dispatch at ``/{server_id}/a2a`` (POST)
- REST-style endpoints at ``/{server_id}/a2a/message:send``, etc.
- Well-known alias at ``/{server_id}/.well-known/agent-card.json``

All routes require ``a2a.invoke`` permission and respect team/visibility
scoping via the standard RBAC middleware.
"""

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.routers.well_known import get_base_url_with_protocol
from mcpgateway.services.a2a_errors import A2AAgentError, A2AAgentNotFoundError, A2AAgentUpstreamError
from mcpgateway.services.a2a_server_service import A2AServerNotFoundError, A2AServerService

logger = logging.getLogger(__name__)

# Router without prefix — mounted at /servers in main.py
router = APIRouter(tags=["A2A Servers"])

# Module-level service instance.
_service: Optional[A2AServerService] = None


def _get_service() -> A2AServerService:
    """Lazy-init the A2A server service.

    Returns:
        A2AServerService singleton instance.
    """
    global _service  # noqa: PLW0603
    if _service is None:
        _service = A2AServerService()
    return _service


def _get_invoke_context(request: Request, user: Any) -> tuple:
    """Extract (user_id, user_email, token_teams) from request context.

    Mirrors the helper used by the standalone A2A router in main.py.

    Args:
        request: Incoming HTTP request.
        user: Authenticated user context.

    Returns:
        Tuple of (user_id, user_email, token_teams).
    """
    # First-Party
    from mcpgateway.main import _get_a2a_invoke_context  # pylint: disable=import-outside-toplevel

    return _get_a2a_invoke_context(request, user)


def _base_url(request: Request) -> str:
    """Derive the external base URL from the incoming request.

    Delegates to :func:`get_base_url_with_protocol` which safely derives the
    scheme from ``X-Forwarded-Proto`` (or ``request.url.scheme``) and the host
    from ``request.base_url`` — avoiding untrusted ``X-Forwarded-Host``.

    Args:
        request: Incoming HTTP request.

    Returns:
        External base URL string including scheme and host.
    """
    return get_base_url_with_protocol(request)


# -----------------------------------------------------------------------
# Agent Card Discovery
# -----------------------------------------------------------------------


@router.get("/{server_id}/a2a/v1/card", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def get_server_agent_card(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Return the auto-generated AgentCard for this server's A2A interface.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        db: Database session.
        user: Authenticated user context.

    Returns:
        AgentCard dictionary for the specified virtual server.

    Raises:
        HTTPException: If the server is not found (404) or the request is invalid (400).
    """
    try:
        service = _get_service()
        return service.get_agent_card(db, server_id, base_url=_base_url(request))
    except A2AServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{server_id}/.well-known/agent-card.json")
@require_permission("a2a.invoke")
async def well_known_agent_card(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Well-known alias for the AgentCard endpoint.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        db: Database session.
        user: Authenticated user context.

    Returns:
        AgentCard dictionary for the specified virtual server.

    Raises:
        HTTPException: If the server is not found (404) or the request is invalid (400).
    """
    try:
        service = _get_service()
        return service.get_agent_card(db, server_id, base_url=_base_url(request))
    except A2AServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------
# JSON-RPC Dispatcher
# -----------------------------------------------------------------------


@router.post("/{server_id}/a2a", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def jsonrpc_dispatch(
    server_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """JSON-RPC 2.0 dispatcher for A2A protocol methods.

    Accepts standard JSON-RPC requests with methods like ``SendMessage``,
    ``GetTask``, ``CancelTask``, etc. and routes them to the appropriate
    associated agent.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        body: JSON-RPC request body.
        db: Database session.
        user: Authenticated user context.

    Returns:
        JSON-RPC 2.0 response dictionary with result or error.
    """
    method = body.get("method", "")
    params = body.get("params", {})
    rpc_id = body.get("id")

    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request: params must be an object"},
            "id": rpc_id,
        }

    user_id, user_email, token_teams = _get_invoke_context(request, user)
    service = _get_service()

    try:
        if method == "SendMessage":
            result = await service.send_message(db, server_id, params, user_id, user_email, token_teams)
        elif method == "GetTask":
            task_id = params.get("taskId") or params.get("id", "")
            result = await service.get_task(db, server_id, task_id, user_id, user_email, token_teams)
        elif method == "CancelTask":
            task_id = params.get("taskId") or params.get("id", "")
            result = await service.cancel_task(db, server_id, task_id, user_id, user_email, token_teams)
        elif method == "ListTasks":
            result = await service.list_tasks(db, server_id, params, user_id, user_email, token_teams)
        elif method == "GetAgentCard":
            result = {"result": service.get_agent_card(db, server_id, base_url=_base_url(request))}
        else:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
                "id": rpc_id,
            }

        return {"jsonrpc": "2.0", "result": result.get("result", result), "id": rpc_id}

    except A2AServerNotFoundError as e:
        return {"jsonrpc": "2.0", "error": {"code": -32602, "message": str(e)}, "id": rpc_id}
    except A2AAgentNotFoundError as e:
        return {"jsonrpc": "2.0", "error": {"code": -32602, "message": str(e)}, "id": rpc_id}
    except A2AAgentUpstreamError as e:
        return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": rpc_id}
    except A2AAgentError as e:
        return {"jsonrpc": "2.0", "error": {"code": -32600, "message": str(e)}, "id": rpc_id}


# -----------------------------------------------------------------------
# REST-style Endpoints
# -----------------------------------------------------------------------


@router.post("/{server_id}/a2a/message:send", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def send_message(
    server_id: str,
    request: Request,
    message_params: Dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Send an A2A message through the virtual server.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        message_params: A2A message parameters.
        db: Database session.
        user: Authenticated user context.

    Returns:
        A2A message response dictionary.

    Raises:
        HTTPException: If the server is not found (404), upstream error (502),
            or the request is invalid (400).
    """
    user_id, user_email, token_teams = _get_invoke_context(request, user)
    try:
        service = _get_service()
        return await service.send_message(db, server_id, message_params, user_id, user_email, token_teams)
    except A2AServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{server_id}/a2a/message:stream")
@require_permission("a2a.invoke")
async def stream_message(
    server_id: str,
    request: Request,
    message_params: Dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> StreamingResponse:
    """Stream an A2A message through the virtual server.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        message_params: A2A message parameters.
        db: Database session.
        user: Authenticated user context.

    Returns:
        Streaming response with server-sent events for the A2A message.

    Raises:
        HTTPException: If the server is not found (404), upstream error (502),
            or the request is invalid (400).
    """
    user_id, user_email, token_teams = _get_invoke_context(request, user)
    try:
        service = _get_service()
        event_stream = await service.stream_message(db, server_id, message_params, user_id, user_email, token_teams)
        return StreamingResponse(event_stream, media_type="text/event-stream")
    except A2AServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{server_id}/a2a/tasks/{task_id}", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def get_task(
    server_id: str,
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Retrieve a task from the virtual server by server-level task ID.

    Args:
        server_id: Virtual server identifier.
        task_id: Task identifier.
        request: Incoming HTTP request.
        db: Database session.
        user: Authenticated user context.

    Returns:
        Task details dictionary.

    Raises:
        HTTPException: If the agent is not found (404), upstream error (502),
            or the request is invalid (400).
    """
    user_id, user_email, token_teams = _get_invoke_context(request, user)
    try:
        service = _get_service()
        return await service.get_task(db, server_id, task_id, user_id, user_email, token_teams)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{server_id}/a2a/tasks", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def list_tasks(
    server_id: str,
    request: Request,
    state: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """List tasks across agents associated with this virtual server.

    Args:
        server_id: Virtual server identifier.
        request: Incoming HTTP request.
        state: Optional task state filter.
        session_id: Optional session ID filter.
        limit: Optional result limit.
        db: Database session.
        user: Authenticated user context.

    Returns:
        Dictionary containing the list of tasks.

    Raises:
        HTTPException: If the server is not found (404), upstream error (502),
            or the request is invalid (400).
    """
    params: Dict[str, Any] = {}
    if state is not None:
        params["state"] = state
    if session_id is not None:
        params["sessionId"] = session_id
    if limit is not None:
        params["limit"] = limit

    user_id, user_email, token_teams = _get_invoke_context(request, user)
    try:
        service = _get_service()
        return await service.list_tasks(db, server_id, params, user_id, user_email, token_teams)
    except A2AServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{server_id}/a2a/tasks/{task_id}:cancel", response_model=Dict[str, Any])
@require_permission("a2a.invoke")
async def cancel_task(
    server_id: str,
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Cancel a task on the virtual server by server-level task ID.

    Args:
        server_id: Virtual server identifier.
        task_id: Task identifier.
        request: Incoming HTTP request.
        db: Database session.
        user: Authenticated user context.

    Returns:
        Cancellation result dictionary.

    Raises:
        HTTPException: If the agent is not found (404), upstream error (502),
            or the request is invalid (400).
    """
    user_id, user_email, token_teams = _get_invoke_context(request, user)
    try:
        service = _get_service()
        return await service.cancel_task(db, server_id, task_id, user_id, user_email, token_teams)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------
# Discovery
# -----------------------------------------------------------------------


@router.get("/a2a/discover", response_model=List[Dict[str, Any]])
@require_permission("a2a.invoke")
async def list_a2a_servers(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> List[Dict[str, Any]]:
    """List all virtual servers that expose A2A interfaces.

    Args:
        request: Incoming HTTP request.
        db: Database session.
        user: Authenticated user context.

    Returns:
        List of dictionaries describing A2A-enabled virtual servers.
    """
    _, user_email, token_teams = _get_invoke_context(request, user)
    service = _get_service()
    return service.list_a2a_servers(db, token_teams=token_teams, user_email=user_email)
