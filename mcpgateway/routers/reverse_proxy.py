# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FastAPI router for handling reverse proxy connections.

This module provides WebSocket and SSE endpoints for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway.
"""

# Standard
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, assert_never, Dict, Final, Literal, Optional
import uuid

# Third-Party
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from pydantic import ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_jwt_user_email_from_payload, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_db, Permissions
from mcpgateway.db import Server as DbServer
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, PermissionChecker, token_scope_grants
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, ReverseProxyCatalogConflictError, ReverseProxyCatalogService
from mcpgateway.services.reverse_proxy_discovery import ReverseProxyDiscoveryService
from mcpgateway.services.reverse_proxy_protocol import (
    encode_server_message,
    error,
    heartbeat,
    HeartbeatMessage,
    NotificationMessage,
    parse_client_message,
    register_ack,
    register_complete,
    RegisterMessage,
    RegistrationServer,
    RegistrationStatus,
    ResponseMessage,
    UnregisterMessage,
)
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, get_reverse_proxy_session_manager, LocalSessionId, StableGatewayId
from mcpgateway.utils.verify_credentials import require_auth, verify_jwt_token_cached

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


class _LockedConnectionIO:
    """Serialize every send and close on one reverse-proxy connection.

    One per-connection lock funnels the endpoint's own frames (register acks,
    heartbeat acknowledgements, error frames), the typed session manager's
    request/notification frames, legacy-mirror HTTP control sends, and all
    server-initiated closes, so the WebSocket is never touched concurrently.
    """

    def __init__(self, websocket: WebSocket, io_lock: anyio.Lock) -> None:
        """Wrap the raw WebSocket with the connection's shared I/O lock."""
        self._websocket = websocket
        self._io_lock = io_lock

    async def send_text(self, data: str) -> None:
        """Send one text frame under the shared I/O lock."""
        async with self._io_lock:
            await self._websocket.send_text(data)

    async def receive_text(self) -> str:
        """Receive one text frame; reads stay unlocked because the receive pump is the sole reader."""
        return await self._websocket.receive_text()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the connection under the shared I/O lock."""
        async with self._io_lock:
            await self._websocket.close(code=code, reason=reason)


class ReverseProxySession:
    """Manages a reverse proxy session."""

    def __init__(self, session_id: str, websocket: _LockedConnectionIO, user: Optional[str | dict] = None):
        """Initialize reverse proxy session.

        Args:
            session_id: Unique session identifier.
            websocket: Locked connection I/O wrapper for the session's WebSocket.
            user: Authenticated user info (if any).
        """
        self.session_id = session_id
        self.websocket = websocket
        self.user = user
        self.server_info: Dict[str, Any] = {}
        self.connected_at = datetime.now(tz=timezone.utc)
        self.last_activity = datetime.now(tz=timezone.utc)
        self.message_count = 0
        self.bytes_transferred = 0

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message to the client.

        Args:
            message: Message dictionary to send.
        """
        data = orjson.dumps(message).decode()
        await self.websocket.send_text(data)
        self.bytes_transferred += len(data)
        self.last_activity = datetime.now(tz=timezone.utc)

    async def receive_message(self) -> Dict[str, Any]:
        """Receive message from the client.

        Returns:
            Parsed message dictionary.
        """
        data = await self.websocket.receive_text()
        self.bytes_transferred += len(data)
        self.message_count += 1
        self.last_activity = datetime.now(tz=timezone.utc)
        return orjson.loads(data)


class ReverseProxyManager:
    """Manages all reverse proxy sessions."""

    def __init__(self):
        """Initialize the manager."""
        self.sessions: Dict[str, ReverseProxySession] = {}
        self._lock = asyncio.Lock()

    async def add_session(self, session: ReverseProxySession) -> None:
        """Add a new session.

        Args:
            session: Session to add.
        """
        async with self._lock:
            self.sessions[session.session_id] = session
            LOGGER.info(f"Added reverse proxy session: {session.session_id}")

    async def remove_session(self, session_id: str) -> None:
        """Remove a session.

        Args:
            session_id: Session ID to remove.
        """
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                LOGGER.info(f"Removed reverse proxy session: {session_id}")

    def get_session(self, session_id: str) -> Optional[ReverseProxySession]:
        """Get a session by ID.

        Args:
            session_id: Session ID to get.

        Returns:
            Session if found, None otherwise.
        """
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[Dict[str, Any]]:
        """List all active sessions.

        Returns:
            List of session information dictionaries.

        Examples:
            >>> from fastapi import WebSocket
            >>> manager = ReverseProxyManager()
            >>> sessions = manager.list_sessions()
            >>> sessions
            []
            >>> isinstance(sessions, list)
            True
        """
        return [
            {
                "session_id": session.session_id,
                "server_info": session.server_info,
                "connected_at": session.connected_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "message_count": session.message_count,
                "bytes_transferred": session.bytes_transferred,
                "user": _get_session_owner(session.user),
            }
            for session in self.sessions.values()
        ]


# Global manager instance
manager = ReverseProxyManager()

_REVERSE_PROXY_CONNECT_PERMISSIONS: Final = (Permissions.GATEWAYS_CREATE, Permissions.SERVERS_CREATE)
# Bounded best-effort socket close for HTTP-initiated disconnects: cleanup of
# typed session state and the legacy mirror must never wait on a stalled socket.
_HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS: Final = 5.0


@dataclass(frozen=True, slots=True)
class ReverseProxyAuthenticatedContext:
    """Canonical authority retained for an admitted reverse-proxy connection."""

    owner_email: str
    team_id: str | None


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
    team_id: str | None = getattr(websocket.state, "team_id", None)
    token_teams: list[str] | None = getattr(websocket.state, "token_teams", None)
    token_scopes: list[str] | None = getattr(websocket.state, "token_scopes", None)

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
        "token_use": getattr(websocket.state, "token_use", None),
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
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc.detail))
        return

    # Accept only after authentication and both authorization layers succeed.
    await websocket.accept()

    # Resolve the shared service singletons on first endpoint use (they are PEP 562
    # lazy module attributes), never at router import time.
    from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel
    from mcpgateway.services.server_service import server_service  # pylint: disable=import-outside-toplevel

    session_manager = await get_reverse_proxy_session_manager()
    connection_io = _LockedConnectionIO(websocket, anyio.Lock())
    connection = await session_manager.connect(connection_io, LocalSessionId(uuid.uuid4().hex))
    connection_id = connection.connection_id

    async def send_frame(frame: str) -> None:
        """Send one endpoint frame serialized through the connection's I/O lock."""
        await connection_io.send_text(frame)

    try:
        # D12: mirror connection metadata in the legacy manager so the HTTP admin
        # endpoints keep working; the typed manager remains the dispatch authority.
        await manager.add_session(ReverseProxySession(str(connection_id), connection_io, authenticated_context.owner_email))
        LOGGER.info(f"Reverse proxy connected: {connection_id}")

        registration_state: Literal["unregistered", "processing", "registered"] = "unregistered"

        async def run_registration(server: RegistrationServer) -> None:
            """Run catalog registration and MCP discovery as a sibling of the receive pump.

            Authority comes only from the authenticated context; the register
            payload carries non-authoritative server metadata. Discovery,
            promotion, and publish are serialized per stable ID through the
            session manager's registration lock, and a displaced predecessor is
            retired only after the replacement registration is acknowledged.
            """
            nonlocal registration_state
            stable_id: StableGatewayId | None = None
            displaced: ConnectionId | None = None
            try:
                registration_context = AuthenticatedRegistrationContext(owner_email=authenticated_context.owner_email, team_id=authenticated_context.team_id)
                entry = await ReverseProxyCatalogService(gateway_service=gateway_service, server_service=server_service).register(db, registration_context, server)
                stable_id = StableGatewayId(entry.stable_id)
                db_gateway = db.get(DbGateway, entry.stable_id)
                db_server = db.get(DbServer, entry.stable_id)
                if db_gateway is None or db_server is None:
                    raise ReverseProxyCatalogConflictError(stable_id=entry.stable_id, reason="catalog pair was not persisted")
                discovery = ReverseProxyDiscoveryService(gateway_service=gateway_service, server_service=server_service)
                async with session_manager.registration_lock(stable_id):
                    # Commit, promote, and publish under the per-stable-ID lock:
                    # two same-ID registrations can never interleave these steps.
                    await discovery.discover_and_reconcile(db, session_manager, connection_id, db_gateway, db_server, timeout_seconds=float(settings.tool_timeout))
                    # Promote only after discovery commits, and publish cache
                    # effects only after promotion: a failed replacement must
                    # never strand the healthy prior mapping or advertise an
                    # unrouted catalog.
                    displaced = await session_manager.promote_stable_id(stable_id, connection_id)
                    await discovery.publish_post_commit_effects(db_gateway, db_server)
                registration_state = "registered"
                LOGGER.info(f"Registered server for connection {connection_id}: {server.name}")
                await send_frame(encode_server_message(register_complete(str(connection_id), RegistrationStatus.SUCCESS)))
                # Retire the displaced predecessor only after the replacement is
                # acknowledged: an acknowledgement failure must still be able to
                # restore the live predecessor mapping.
                if displaced is not None and displaced != connection_id:
                    await session_manager.retire_connection(displaced)
            except Exception:
                LOGGER.error("Reverse proxy registration failed for connection %s", connection_id, exc_info=True)
                if stable_id is not None:
                    # Compare-and-swap no-op unless this connection's promotion is still current.
                    await session_manager.restore_stable_id(stable_id, displaced, connection_id)
                try:
                    await send_frame(encode_server_message(register_complete(str(connection_id), RegistrationStatus.ERROR, "registration failed")))
                    await connection_io.close(code=status.WS_1008_POLICY_VIOLATION, reason="registration failed")
                except Exception as io_error:
                    # The socket can already be lost (for example mid-discovery);
                    # never mask the primary failure with a secondary send error.
                    LOGGER.debug("Reverse proxy registration-failure notification failed for connection %s: %s", connection_id, io_error)
                return

        try:
            async with anyio.create_task_group() as task_group:
                try:
                    # One continuously-running receive pump; registration and
                    # discovery run in a sibling task so their JSON-RPC
                    # responses keep resolving here.
                    while True:
                        try:
                            message = parse_client_message(await connection_io.receive_text())
                        except WebSocketDisconnect:
                            LOGGER.info(f"WebSocket disconnected: {connection_id}")
                            break
                        except (ValidationError, orjson.JSONDecodeError) as exc:
                            LOGGER.warning(f"Invalid message from connection {connection_id}: {exc}")
                            await send_frame(encode_server_message(error(str(connection_id), "Invalid message format")))
                            continue

                        match message:
                            case RegisterMessage():
                                if registration_state != "unregistered":
                                    LOGGER.warning(f"Duplicate register on connection {connection_id}")
                                    await send_frame(encode_server_message(error(str(connection_id), "connection already registered")))
                                    await connection_io.close(code=status.WS_1008_POLICY_VIOLATION, reason="connection already registered")
                                    break
                                registration_state = "processing"
                                await send_frame(encode_server_message(register_ack(str(connection_id))))
                                task_group.start_soon(run_registration, message.server)
                            case UnregisterMessage():
                                LOGGER.info(f"Unregistering server for connection {connection_id}")
                                break
                            case HeartbeatMessage():
                                await send_frame(encode_server_message(heartbeat(str(connection_id), datetime.now(tz=timezone.utc))))
                            case ResponseMessage():
                                if not session_manager.resolve_response(connection_id, message):
                                    LOGGER.debug(f"Unmatched response from connection {connection_id}: {message.payload.id}")
                            case NotificationMessage():
                                LOGGER.debug(f"Received notification from connection {connection_id}: {message.payload.method}")
                            case unreachable:
                                assert_never(unreachable)
                finally:
                    # Disconnect, unregister, and duplicate-register paths cancel
                    # any in-flight registration; the task group awaits its
                    # cancellation on exit.
                    task_group.cancel_scope.cancel()
        except ExceptionGroup as group:
            # anyio wraps a sole pump-loop failure in an ExceptionGroup;
            # re-raise the original exception unchanged.
            if len(group.exceptions) == 1:
                raise group.exceptions[0]
            raise
    finally:
        # Shield the typed disconnect so cancellation cannot skip cleanup, and
        # guarantee the legacy mirror removal runs even when it fails.
        with anyio.CancelScope(shield=True):
            try:
                await session_manager.disconnect(connection_id)
            finally:
                await manager.remove_session(str(connection_id))
        LOGGER.info(f"Reverse proxy session ended: {connection_id}")


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
    requesting_user, is_admin = _get_user_from_credentials(credentials)

    # Admins see all sessions
    if is_admin:
        return {"sessions": manager.list_sessions(), "total": len(manager.sessions)}

    # Regular users see only their own sessions
    all_sessions = manager.list_sessions()
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
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "disconnect")

    # Clear typed session state and the legacy mirror FIRST so stable mappings
    # and pending calls fail closed immediately, then close the socket bounded
    # and best-effort: a stalled or already-lost connection cannot block cleanup.
    session_manager = await get_reverse_proxy_session_manager()
    await session_manager.disconnect(ConnectionId(session_id))
    await manager.remove_session(session_id)
    try:
        with anyio.fail_after(_HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS):
            await session.websocket.close()
    except Exception as close_error:
        LOGGER.debug("Reverse proxy HTTP disconnect close for session %s failed: %s", session_id, close_error)

    return {"status": "disconnected", "session_id": session_id}


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
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "send request to")

    # Wrap the request in reverse proxy envelope
    message = {"type": "request", "sessionId": session_id, "payload": mcp_request}

    try:
        await session.send_message(message)
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


def _get_session_owner(session_user: str | dict[str, Any] | None) -> str | None:
    """Extract a comparable owner email from stored reverse-proxy session user data."""
    if isinstance(session_user, str):
        return session_user
    if isinstance(session_user, dict):
        return get_jwt_user_email_from_payload(session_user)
    return None


def _validate_session_ownership(session: ReverseProxySession, credentials: str | dict[str, Any] | None, action: str) -> None:
    """Validate that the requesting user owns the session or is admin.

    Args:
        session: The session to validate ownership for
        credentials: Auth credentials from require_auth
        action: Description of the action for logging

    Raises:
        HTTPException: 403 if user is not authorized for the session
    """
    if not session.user:
        # Session was created without auth - allow access
        return

    requesting_user, is_admin = _get_user_from_credentials(credentials)

    # Admins can access any session
    if is_admin:
        return

    # Session owner can access their own session
    session_owner = _get_session_owner(session.user)
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
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found")

    # Validate session ownership
    _validate_session_ownership(session, credentials, "subscribe to SSE for")

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
