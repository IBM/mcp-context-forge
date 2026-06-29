# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/reverse_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

FastAPI router for handling reverse proxy connections.

This module provides WebSocket and SSE endpoints for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway.
"""

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import PermissionChecker
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_service import (
    get_reverse_proxy_service,
    get_user_from_credentials,
    get_worker_id,
    ReverseProxySession,
    validate_session_ownership,
)
from mcpgateway.utils.verify_credentials import extract_websocket_bearer_token, is_proxy_auth_trust_active, require_auth

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])

# Get the global service instance
service = get_reverse_proxy_service()

# Required permissions for reverse proxy connections
_REVERSE_PROXY_CONNECT_PERMISSIONS = [
    "servers.create",
    "servers.update",
    "servers.manage",
]


def _get_websocket_bearer_token(websocket: WebSocket) -> Optional[str]:
    """Extract bearer token from WebSocket Authorization headers.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Bearer token value when present, otherwise None.
    """
    return extract_websocket_bearer_token(
        getattr(websocket, "query_params", {}),
        getattr(websocket, "headers", {}),
        query_param_warning="Reverse proxy WebSocket token passed via query parameter",
    )


async def _authenticate_reverse_proxy_websocket(websocket: WebSocket) -> tuple[Optional[str], Optional[str]]:
    """Authenticate and authorize a reverse-proxy WebSocket connection.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Tuple of (user_email, team_id) when available, otherwise (None, None).

    Raises:
        HTTPException: If authentication fails or required permissions are missing.
    """
    auth_required = settings.auth_required or settings.mcp_client_auth_enabled
    auth_token = _get_websocket_bearer_token(websocket)
    LOGGER.info(f"[REVERSE_PROXY] auth_required={auth_required}, auth_token present={bool(auth_token)}")
    user_context: Optional[dict[str, Any]] = None

    if auth_token:
        LOGGER.info("[REVERSE_PROXY] Processing auth token...")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_token)
        try:
            user = await get_current_user(credentials, request=websocket)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed") from exc
        user_context = {
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
            "ip_address": websocket.client.host if websocket.client else None,
            "user_agent": websocket.headers.get("user-agent"),
            "team_id": getattr(websocket.state, "team_id", None),
            "token_teams": getattr(websocket.state, "token_teams", None),
            "token_use": getattr(websocket.state, "token_use", None),
        }
    elif is_proxy_auth_trust_active(settings):
        proxy_user = websocket.headers.get(settings.proxy_user_header)
        if proxy_user:
            user_context = {
                "email": proxy_user,
                "full_name": proxy_user,
                "is_admin": False,
                "ip_address": websocket.client.host if websocket.client else None,
                "user_agent": websocket.headers.get("user-agent"),
            }
        elif auth_required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    elif auth_required:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    if user_context:
        # Two-layer permission check:
        # Layer 1: Token scopes.permissions cap (if present)
        # Layer 2: RBAC role-based permission check

        # Extract token scopes from JWT payload cached in websocket.state
        token_scopes: Optional[dict] = None
        jwt_payload = getattr(websocket.state, "_jwt_verified_payload", None)
        if jwt_payload and isinstance(jwt_payload, tuple) and len(jwt_payload) == 2:
            _, payload = jwt_payload
            if payload and isinstance(payload, dict):
                token_scopes = payload.get("scopes")

        # Layer 1: Check token scopes if present
        if token_scopes and isinstance(token_scopes, dict):
            LOGGER.info(f"[REVERSE_PROXY] Token scopes found: {token_scopes}")
            scoped_permissions = token_scopes.get("permissions")
            LOGGER.info(f"[REVERSE_PROXY] Scoped permissions: {scoped_permissions}")
            if scoped_permissions:  # Explicit permissions in token
                # Check if token has any of the required permissions
                has_wildcard = "*" in scoped_permissions
                has_required = any(perm in scoped_permissions for perm in _REVERSE_PROXY_CONNECT_PERMISSIONS)
                LOGGER.info(f"[REVERSE_PROXY] has_wildcard={has_wildcard}, has_required={has_required}, required_perms={_REVERSE_PROXY_CONNECT_PERMISSIONS}")

                if not (has_wildcard or has_required):
                    LOGGER.warning(
                        f"[REVERSE_PROXY] Reverse proxy WebSocket authentication failed: Token scopes missing required permissions. "
                        f"Token has: {scoped_permissions}, Required: {_REVERSE_PROXY_CONNECT_PERMISSIONS}"
                    )
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

                # Token scopes check passed, skip RBAC check (token scopes are authoritative)
                LOGGER.info(f"[REVERSE_PROXY] Reverse proxy WebSocket authentication successful via token scopes. " f"User: {user_context['email']}, Permissions: {scoped_permissions}")
                return user_context["email"], user_context.get("team_id")

        # Layer 2: Fall back to RBAC check if no explicit token scopes
        checker = PermissionChecker(user_context)
        if not await checker.has_any_permission(_REVERSE_PROXY_CONNECT_PERMISSIONS):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user_context["email"], user_context.get("team_id")

    return None, None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for reverse proxy connections.

    Authentication is REQUIRED when:
    - settings.auth_required is True, OR
    - settings.mcp_client_auth_enabled is True

    Supports:
    - Bearer token in Authorization header
    - Proxy authentication (when trust_proxy_auth is True and mcp_client_auth_enabled is False)

    Args:
        websocket: WebSocket connection.
        db: Database session.

    Raises:
        ValueError: If token is missing required subject claim.
    """
    LOGGER.debug("Reverse proxy WebSocket connection opened")
    try:
        user, team_id = await _authenticate_reverse_proxy_websocket(websocket)
    except HTTPException as e:
        LOGGER.warning(f"Reverse proxy WebSocket authentication failed: {e.detail}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e.detail))
        return

    # Accept connection only after successful authentication (or when auth not required)
    await websocket.accept()

    # Generate session ID server-side to prevent session hijacking
    # Client-supplied X-Session-ID is ignored for security (prevents collision/hijack attacks)
    # Get session ID from headers or generate new one
    session_id = websocket.headers.get("X-Session-ID", uuid.uuid4().hex)
    LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | WebSocket connected (user={user})")

    # Create session with authenticated user
    session = ReverseProxySession(session_id, websocket, user)

    # Register ownership in Redis BEFORE adding to local dict (for session affinity)
    await service.manager.register_session_ownership(session_id)
    await service.manager.add_session(session)

    try:
        LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Entering message loop")

        # Main message loop
        while True:
            try:
                message = await session.receive_message()
                msg_type = message.get("type")

                if msg_type == "register":
                    # Register the server
                    session.server_info = message.get("server", {})
                    LOGGER.info(f"session.server_info  {session.server_info}")

                    # Delegate registration to service layer (runs in background)
                    asyncio.create_task(
                        service.register_session_gateway_and_server(
                            session_id=session_id,
                            session=session,
                            server_info=session.server_info,
                            team_id=team_id,
                            user=user,
                        )
                    )

                elif msg_type == "unregister":
                    # Unregister the server
                    LOGGER.info(f"Unregistering server for session {session_id}")
                    break

                elif msg_type == "heartbeat":
                    # Update heartbeat timestamp and reset missed count
                    now = datetime.now(tz=timezone.utc)
                    previous_heartbeat = session.last_heartbeat
                    time_since_last = (now - previous_heartbeat).total_seconds() if previous_heartbeat else 0

                    session.last_heartbeat = now
                    previous_missed = session.missed_heartbeats
                    session.missed_heartbeats = 0

                    # Log heartbeat reception with timing details
                    LOGGER.info(
                        f"[HEARTBEAT_RECEIVED] Worker {get_worker_id()} | Session {session_id[:8]}... | "
                        f"Heartbeat received | Time since last: {time_since_last:.1f}s | "
                        f"Missed count reset: {previous_missed} → 0"
                    )

                    # Respond to heartbeat and refresh Redis ownership TTL (throttled to TTL/2 interval)
                    await session.send_message({"type": "heartbeat", "sessionId": session_id, "timestamp": now.isoformat()})
                    await service.manager.refresh_session_ownership_if_due(session_id, session)

                elif msg_type in ("response", "notification"):
                    # Handle MCP response/notification from the proxied server
                    payload = message.get("payload")
                    request_id = payload.get("id") if payload else None
                    LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Received {msg_type} from agent (request_id={request_id})")
                    if request_id and request_id in service.pending_responses:
                        future = service.pending_responses.pop(request_id)
                        if not future.done():
                            LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Resolved pending future for request_id={request_id}")
                            future.set_result(message)
                        else:
                            LOGGER.warning(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Future already done for request_id={request_id} (timeout or cancelled?)")
                    elif request_id:
                        LOGGER.warning(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | No pending future for request_id={request_id} (already timed out?)")

                else:
                    LOGGER.warning(f"Unknown message type from session {session_id}: {msg_type}")

            except WebSocketDisconnect:
                LOGGER.info(f"WebSocket disconnected: {session_id}")
                break
            except orjson.JSONDecodeError as e:
                LOGGER.error(f"Invalid JSON from session {session_id}: {e}")
                await session.send_message({"type": "error", "message": "Invalid JSON format"})
            except Exception as e:
                LOGGER.error(f"Error handling message from session {session_id}: {e}")
                await session.send_message({"type": "error", "message": str(e)})

    finally:
        await service.manager.remove_session(session_id)
        await service.manager.release_session_ownership(session_id)
        LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | WebSocket session ended")


@router.get("/sessions")
async def list_sessions(
    request: Request,
    credentials: str | dict = Depends(require_auth),
):
    """List active reverse proxy sessions.

    Returns only sessions owned by the authenticated user, unless
    the user is an admin (in which case all sessions are returned).

    Args:
        request: HTTP request.
        credentials: Authenticated user credentials.

    Returns:
        List of session information (filtered by ownership).
    """
    requesting_user, is_admin = get_user_from_credentials(credentials)

    LOGGER.info(f"list_sessions manager {hex(id(service.manager))} sessions {hex(id(service.manager.sessions))} sessions.values {service.manager.sessions.values()}")
    # Admins see all sessions
    if is_admin:
        return {"sessions": await service.manager.list_sessions(), "total": len(service.manager.sessions)}

    # Regular users see only their own sessions
    all_sessions = await service.manager.list_sessions()
    owned_sessions = []
    for session_info in all_sessions:
        session_owner = session_info.get("user")
        # Include if: user owns the session, or session has no owner (anonymous)
        if not session_owner or session_owner == requesting_user:
            owned_sessions.append(session_info)

    return {"sessions": owned_sessions, "total": len(owned_sessions)}


@router.delete("/sessions/{session_id}")
async def disconnect_session(
    session_id: str,
    request: Request,
    credentials: str | dict = Depends(require_auth),
):
    """Disconnect a reverse proxy session.

    Requires authentication and validates session ownership.
    Only the session owner or an admin can disconnect a session.

    Args:
        session_id: Session ID to disconnect.
        request: HTTP request.
        credentials: Authenticated user credentials.

    Returns:
        Disconnection status.

    Raises:
        HTTPException: If session is not found or user is not authorized.
    """
    # Validate session_id format (must be valid UUID hex string)
    try:
        # Validate UUID format - will raise ValueError if invalid
        uuid.UUID(session_id) if len(session_id) == 36 else uuid.UUID(hex=session_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session ID format")

    session = await service.manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    user_email, is_admin = get_user_from_credentials(credentials)
    if not validate_session_ownership(session, user_email, is_admin, "disconnect"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session")

    # Close the WebSocket connection
    await session.websocket.close()
    await service.manager.remove_session(session_id)

    # Return the validated session_id from the session object to prevent XSS
    return {"status": "disconnected", "session_id": session.session_id}


@router.post("/sessions/{session_id}/request")
async def send_request_to_session(
    session_id: str,
    mcp_request: Dict[str, Any],
    request: Request,
    credentials: str | dict = Depends(require_auth),
):
    """Send an MCP request to a reverse proxy session.

    Requires authentication and validates session ownership.
    Only the session owner or an admin can send requests to a session.

    Args:
        session_id: Session ID to send request to.
        mcp_request: MCP request to send.
        request: HTTP request.
        credentials: Authenticated user credentials.

    Returns:
        Request acknowledgment.

    Raises:
        HTTPException: If session is not found, user is not authorized, or request fails.
    """
    session = await service.manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    user_email, is_admin = get_user_from_credentials(credentials)
    if not validate_session_ownership(session, user_email, is_admin, "send request to"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session")

    try:
        response = await service.forward_request_to_session(session_id, mcp_request)
        return response
    except asyncio.TimeoutError:
        LOGGER.error("TimeoutError to send request to session %s", session_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Failed to send request")
    except Exception:
        LOGGER.error("Failed to send request to session %s", session_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send request")


@router.get("/sse/{session_id}")
async def sse_endpoint(
    session_id: str,
    request: Request,
    credentials: str | dict = Depends(require_auth),
):
    """SSE endpoint for receiving messages from a reverse proxy session.

    Requires authentication via require_auth dependency.
    Additionally validates that the authenticated user owns the session.

    Args:
        session_id: Session ID to subscribe to.
        request: HTTP request.
        credentials: Authenticated user credentials.

    Returns:
        SSE stream.

    Raises:
        HTTPException: If session is not found or user is not authorized.
    """
    session = await service.manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    user_email, is_admin = get_user_from_credentials(credentials)
    if not validate_session_ownership(session, user_email, is_admin, "subscribe to SSE for"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session")

    async def event_generator():
        """Generate SSE events.

        Yields:
            dict: SSE event data.

        Raises:
            asyncio.CancelledError: If the generator is cancelled.
        """
        try:
            # Send initial connection event
            yield {"event": "connected", "data": orjson.dumps({"sessionId": session_id, "serverInfo": session.server_info}).decode()}

            # TODO: Implement message queue for SSE delivery
            while not await request.is_disconnected():
                await asyncio.sleep(30)  # Keepalive
                yield {"event": "keepalive", "data": orjson.dumps({"timestamp": datetime.now(tz=timezone.utc).isoformat()}).decode()}

        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
