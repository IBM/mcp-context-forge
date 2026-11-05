# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FastAPI router for handling reverse proxy connections.

This module provides WebSocket and SSE endpoints for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway, plus the
HTTP session-operations endpoints (list, disconnect, send-request) that act
on admitted sessions. WebSocket admission (authentication and both
authorization layers) and transport wrapping live here; the connection
lifecycle itself lives in
``mcpgateway.services.reverse_proxy_lifecycle``.
"""

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, Final, Optional

# Third-Party
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_jwt_user_email_from_payload, get_request_identity, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import get_db, Permissions
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, PermissionChecker, token_scope_grants
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_lifecycle import _LockedConnectionIO, _persist_unreachable_best_effort, ReverseProxyAuthenticatedContext, run_proxied_connection
from mcpgateway.services.reverse_proxy_protocol import JsonRpcRequest, JsonValue
from mcpgateway.services.reverse_proxy_relay_models import RelaySessionEntry
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, get_reverse_proxy_session_manager, ReverseProxySession
from mcpgateway.utils.verify_credentials import require_auth, verify_jwt_token_cached

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


_REVERSE_PROXY_CONNECT_PERMISSIONS: Final = (Permissions.GATEWAYS_CREATE, Permissions.SERVERS_CREATE)
# Bounded best-effort socket close for HTTP-initiated disconnects: authoritative
# typed session cleanup must never wait on a stalled socket.
_HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS: Final = 5.0


def _get_websocket_bearer_token(websocket: WebSocket) -> Optional[str]:
    """Extract a bearer token only from the WebSocket Authorization header.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Bearer token value when present, otherwise None.
    """
    authorization = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not credentials.strip():
        return None
    return credentials.strip()


async def _require_http_permission(request: Request, credentials: str | dict[str, Any], permission: str) -> None:
    """Enforce one method-specific Layer-2 permission before session access."""
    requesting_user, is_admin = _get_user_from_credentials(credentials)
    request_scope = getattr(request, "scope", {})
    scope_state = request_scope.get("state", {}) if isinstance(request_scope, dict) else {}
    team_id = scope_state.get("team_id") if isinstance(scope_state, dict) else None
    token_teams = scope_state.get("token_teams") if isinstance(scope_state, dict) else None
    token_scopes = scope_state.get("token_scopes") if isinstance(scope_state, dict) else None
    checker = PermissionChecker(
        {
            "email": requesting_user,
            "is_admin": is_admin,
            "team_id": team_id,
            "token_teams": token_teams,
            "token_scopes": token_scopes,
        }
    )
    if not await checker.has_permission(permission, team_id=team_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)


def _encode_sse_event(event: str, data: dict[str, JsonValue]) -> str:
    """Serialize one standards-compliant SSE event frame."""
    return f"event: {event}\ndata: {orjson.dumps(data).decode()}\n\n"


async def _authenticate_reverse_proxy_websocket(websocket: WebSocket) -> ReverseProxyAuthenticatedContext:
    """Authenticate and authorize a reverse-proxy WebSocket connection.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Canonical authenticated owner and server-derived team context.

    Raises:
        HTTPException: If authentication fails or required permissions are missing.
    """
    auth_token = _get_websocket_bearer_token(websocket)
    if auth_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_token)
    auth_scope = dict(websocket.scope)
    auth_scope["type"] = "http"
    auth_request = Request(auth_scope)
    user = await get_current_user(credentials, request=auth_request)
    owner_email = get_user_email(user)
    team_id: str | None = getattr(auth_request.state, "team_id", None)
    token_teams: list[str] | None = getattr(auth_request.state, "token_teams", None)
    token_scopes: list[str] | None = getattr(auth_request.state, "token_scopes", None)

    cached_payload = getattr(auth_request.state, "_jwt_verified_payload", None)
    if isinstance(cached_payload, tuple) and len(cached_payload) == 2 and cached_payload[0] == auth_token and isinstance(cached_payload[1], dict):
        token_payload = await verify_jwt_token_cached(auth_token, auth_request)
    elif getattr(auth_request.state, "auth_method", None) == "jwt":
        token_payload = await verify_jwt_token_cached(auth_token, auth_request)
    else:
        token_payload = {"scopes": {}}

    # Layer-1 parity with HTTP admission: revalidate claimed team membership
    # for non-session (API/legacy) tokens before restrictions, scopes, and RBAC.
    if token_payload.get("token_use") != "session" and not token_scoping_middleware.check_team_membership(token_payload):  # nosec B105 - Not a password; token_use is a JWT claim type
        LOGGER.warning(
            "Reverse proxy WebSocket admission denied: token team membership is no longer valid",
            extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "layer": "team_membership"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")
    request_path = str(websocket.scope.get("path") or "/reverse-proxy/ws")
    client_ip = websocket.client.host if websocket.client else "unknown"
    token_scoping_middleware.enforce_non_permission_restrictions(token_payload, request_path, client_ip)

    for permission in _REVERSE_PROXY_CONNECT_PERMISSIONS:
        if not token_scope_grants(token_scopes, permission):
            LOGGER.warning(
                "Reverse proxy WebSocket permission denied",
                extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "permission": permission, "layer": "token_scope"},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

    user_context: dict[str, Any] = {
        "email": owner_email,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "ip_address": websocket.client.host if websocket.client else None,
        "user_agent": websocket.headers.get("user-agent"),
        "team_id": team_id,
        "token_teams": token_teams,
        "token_use": getattr(auth_request.state, "token_use", None),
    }
    checker = PermissionChecker(user_context)
    for permission in _REVERSE_PROXY_CONNECT_PERMISSIONS:
        if not await checker.has_permission(permission, team_id=team_id):
            LOGGER.warning(
                "Reverse proxy WebSocket permission denied",
                extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "permission": permission, "layer": "rbac"},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

    return ReverseProxyAuthenticatedContext(owner_email=owner_email, team_id=team_id)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for reverse proxy connections.

    Authentication always requires a Bearer token in the Authorization header.
    The maintained client contract drives the lifecycle: ``register`` is
    acknowledged as ``register_ack(processing)`` before catalog persistence
    and MCP discovery run, then ``register_complete(success|error)`` closes
    the registration exchange. Heartbeats are acknowledgements, not pongs.
    One continuously-running receive pump owns every inbound frame while
    registration and discovery run as a sibling task, so the client's own
    JSON-RPC discovery responses always resolve.

    Args:
        websocket: WebSocket connection.
        db: Database session.
    """
    try:
        authenticated_context = await _authenticate_reverse_proxy_websocket(websocket)
    except HTTPException as exc:
        LOGGER.warning(
            "Reverse proxy WebSocket admission rejected",
            extra={"event": "reverse_proxy.websocket.rejected", "status_code": exc.status_code, "reason": str(exc.detail)},
        )
        await websocket.send_denial_response(JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}))
        return

    # Accept only after authentication and both authorization layers succeed.
    await websocket.accept()

    # Wrap the transport in the connection's shared I/O lock, then hand the
    # accepted connection to the lifecycle service.
    connection_io = _LockedConnectionIO(websocket, anyio.Lock())
    await run_proxied_connection(connection_io, authenticated_context, db)


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
    await _require_http_permission(request, credentials, Permissions.GATEWAYS_READ)
    requesting_user, is_admin = get_request_identity(request, credentials)
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

        sessions = await (await get_reverse_proxy_relay()).list_session_entries()
    else:
        session_manager = await get_reverse_proxy_session_manager()
        sessions = session_manager.list_sessions()
    visible = sessions if is_admin else tuple(session for session in sessions if not session.owner_email or session.owner_email == requesting_user)
    payload = [_session_payload(session) if isinstance(session, ReverseProxySession) else _relay_session_payload(session) for session in visible]
    return {"sessions": payload, "total": len(payload)}


def _session_payload(session: ReverseProxySession) -> dict[str, JsonValue]:
    """Serialize typed session metadata using the established list response shape."""
    return {
        "session_id": str(session.connection_id),
        "server_info": dict(session.server_info),
        "connected_at": session.connected_at.isoformat(),
        "last_activity": session.last_activity.isoformat(),
        "message_count": session.message_count,
        "bytes_transferred": session.bytes_transferred,
        "user": session.owner_email,
    }


def _relay_session_payload(session: RelaySessionEntry) -> dict[str, JsonValue]:
    """Serialize distributed directory metadata using the established response shape."""
    return {
        "session_id": session.connection_id,
        "server_info": dict(session.server_info),
        "connected_at": session.connected_at,
        "last_activity": session.last_activity,
        "message_count": session.message_count,
        "bytes_transferred": session.bytes_transferred,
        "user": session.owner_email,
    }


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
    await _require_http_permission(request, credentials, Permissions.GATEWAYS_DELETE)
    session_manager = await get_reverse_proxy_session_manager()
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

        relay = await get_reverse_proxy_relay()
        session = session_manager.get_session(ConnectionId(session_id)) or await relay.get_session_entry(ConnectionId(session_id))
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")
        _validate_session_ownership(session, credentials, "disconnect", request=request)
        if not await relay.disconnect_session(ConnectionId(session_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")
        return {"status": "disconnected", "session_id": session_id}
    session = session_manager.get_session(ConnectionId(session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "disconnect", request=request)

    # Clear typed session state first so stable mappings and pending calls fail
    # closed immediately, then close the socket bounded
    # and best-effort: a stalled or already-lost connection cannot block cleanup.
    disconnected_stable_ids = await session_manager.disconnect(ConnectionId(session_id))
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay, release_reverse_proxy_owners_best_effort  # pylint: disable=import-outside-toplevel

        relay = await get_reverse_proxy_relay()
        await release_reverse_proxy_owners_best_effort(relay, disconnected_stable_ids)
    await _persist_unreachable_best_effort(session_manager, disconnected_stable_ids)
    try:
        with anyio.fail_after(_HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS):
            await session.websocket.close()
    except Exception as close_error:
        LOGGER.debug("Reverse proxy HTTP disconnect close for session %s failed: %s", session_id, close_error)

    return {"status": "disconnected", "session_id": session_id}


@router.post("/sessions/{session_id}/request")
async def send_request_to_session(
    session_id: str,
    mcp_request: JsonRpcRequest,
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
    await _require_http_permission(request, credentials, Permissions.TOOLS_EXECUTE)
    session_manager = await get_reverse_proxy_session_manager()
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

        relay = await get_reverse_proxy_relay()
        session = session_manager.get_session(ConnectionId(session_id)) or await relay.get_session_entry(ConnectionId(session_id))
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")
        _validate_session_ownership(session, credentials, "send request to", request=request)
        try:
            await relay.send_request_by_connection_id_nowait(ConnectionId(session_id), mcp_request, timeout_seconds=float(settings.tool_timeout))
            return {"status": "sent", "session_id": session_id}
        except Exception:
            LOGGER.error("Failed to send request to session %s", session_id, exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send request")
    session = session_manager.get_session(ConnectionId(session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "send request to", request=request)

    try:
        await session_manager.send_request_nowait(ConnectionId(session_id), mcp_request, timeout_seconds=float(settings.tool_timeout))
        return {"status": "sent", "session_id": session_id}
    except Exception:
        LOGGER.error("Failed to send request to session %s", session_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send request")


def _get_user_from_credentials(credentials: str | dict[str, Any] | None) -> tuple[str | None, bool]:
    """Extract user and admin status from credentials.

    Args:
        credentials: Auth credentials (dict from JWT or string)

    Returns:
        Tuple of (username, is_admin)
    """
    if isinstance(credentials, dict):
        user = get_jwt_user_email_from_payload(credentials)
        # Check both top-level is_admin and nested user.is_admin (JWT tokens may nest it)
        user_claim = credentials.get("user")
        nested_is_admin = user_claim.get("is_admin", False) if isinstance(user_claim, dict) else False
        is_admin = bool(credentials.get("is_admin", False) or nested_is_admin)
        return user, is_admin
    elif credentials and credentials != "anonymous":
        return credentials, False
    return None, False


def _validate_session_ownership(session: ReverseProxySession | RelaySessionEntry, credentials: str | dict[str, Any] | None, action: str, *, request: Request | None = None) -> None:
    """Validate that the requesting user owns the session or is admin.

    Args:
        session: The session to validate ownership for
        credentials: Auth credentials from require_auth
        action: Description of the action for logging
        request: Request context used for authoritative session-token admin state.

    Raises:
        HTTPException: 403 if user is not authorized for the session
    """
    if not session.owner_email:
        # Session was created without auth - allow access
        return

    requesting_user, is_admin = get_request_identity(request, credentials) if request is not None else _get_user_from_credentials(credentials)

    # Admins can access any session
    if is_admin:
        return

    # Session owner can access their own session
    session_owner = session.owner_email
    if requesting_user and session_owner and requesting_user == session_owner:
        return

    # Not authorized
    LOGGER.warning(f"Session access denied: user {requesting_user} attempted to {action} session owned by {session_owner}")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session")


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
    await _require_http_permission(request, credentials, Permissions.GATEWAYS_READ)
    session_manager = await get_reverse_proxy_session_manager()
    session: ReverseProxySession | RelaySessionEntry | None = session_manager.get_session(ConnectionId(session_id))
    if session is None and settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

        session = await (await get_reverse_proxy_relay()).get_session_entry(ConnectionId(session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "subscribe to SSE for", request=request)

    async def event_generator():
        """Generate SSE events.

        Yields:
            dict: SSE event data.

        Raises:
            asyncio.CancelledError: If the generator is cancelled.
        """
        try:
            # Send initial connection event
            yield _encode_sse_event("connected", {"sessionId": session_id, "serverInfo": dict(session.server_info)})

            # TODO: Implement message queue for SSE delivery
            while not await request.is_disconnected():
                await asyncio.sleep(30)  # Keepalive
                yield _encode_sse_event("keepalive", {"timestamp": datetime.now(tz=timezone.utc).isoformat()})

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
