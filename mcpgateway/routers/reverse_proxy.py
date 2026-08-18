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
from typing import Any, assert_never, Final, Literal, Optional
import uuid

# Third-Party
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from pydantic import ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_jwt_user_email_from_payload, get_request_identity, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_db, Permissions
from mcpgateway.db import Server as DbServer
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, PermissionChecker, token_scope_grants
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, ReverseProxyCatalogConflictError, ReverseProxyCatalogService, stable_proxy_id
from mcpgateway.services.reverse_proxy_discovery import ReverseProxyDiscoveryService
from mcpgateway.services.reverse_proxy_relay_models import RelaySessionEntry
from mcpgateway.services.reverse_proxy_protocol import (
    encode_server_message,
    error,
    heartbeat,
    HeartbeatMessage,
    JsonRpcRequest,
    JsonValue,
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
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, get_reverse_proxy_session_manager, LocalSessionId, ReverseProxyEviction, ReverseProxySession, StableGatewayId
from mcpgateway.utils.verify_credentials import require_auth, verify_jwt_token_cached

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


async def _persist_unreachable_best_effort(session_manager, evictions) -> None:
    """Persist disconnect reachability without masking transport cleanup."""
    try:
        from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel,no-name-in-module

        authority_check = None
        if settings.mcpgateway_reverse_proxy_distributed_enabled:
            from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

            authority_check = (await get_reverse_proxy_relay()).is_unowned
        await gateway_service.mark_reverse_proxy_gateways_unreachable(
            session_manager,
            evictions,
            seen_at=datetime.now(tz=timezone.utc),
            authority_check=authority_check,
        )
    except Exception as persistence_error:
        LOGGER.warning("Reverse-proxy reachability persistence failed", exc_info=persistence_error)


class _LockedConnectionIO:
    """Serialize every send and close on one reverse-proxy connection.

    One per-connection lock funnels the endpoint's own frames (register acks,
    heartbeat acknowledgements, error frames), the typed session manager's
    request/notification frames and all server-initiated closes, so the
    WebSocket is never touched concurrently.
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


_REVERSE_PROXY_CONNECT_PERMISSIONS: Final = (Permissions.GATEWAYS_CREATE, Permissions.SERVERS_CREATE)
# Bounded best-effort socket close for HTTP-initiated disconnects: authoritative
# typed session cleanup must never wait on a stalled socket.
_HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS: Final = 5.0
_MAX_WEBSOCKET_FRAME_BYTES: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReverseProxyAuthenticatedContext:
    """Canonical authority retained for an admitted reverse-proxy connection."""

    owner_email: str
    team_id: str | None


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

    # Resolve the shared service singletons on first endpoint use (they are PEP 562
    # lazy module attributes), never at router import time.
    from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel,no-name-in-module
    from mcpgateway.services.server_service import server_service  # pylint: disable=import-outside-toplevel,no-name-in-module

    session_manager = await get_reverse_proxy_session_manager()
    relay = None
    release_owners = None
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay, release_reverse_proxy_owners_best_effort  # pylint: disable=import-outside-toplevel

        relay = await get_reverse_proxy_relay()
        release_owners = release_reverse_proxy_owners_best_effort
    connection_io = _LockedConnectionIO(websocket, anyio.Lock())
    connection = await session_manager.connect(connection_io, LocalSessionId(uuid.uuid4().hex), owner_email=authenticated_context.owner_email)
    connection_id = connection.connection_id

    async def send_frame(frame: str) -> None:
        """Send one endpoint frame serialized through the connection's I/O lock."""
        await connection_io.send_text(frame)
        session_manager.record_sent(connection_id, character_count=len(frame))

    try:
        LOGGER.info(f"Reverse proxy connected: {connection_id}")

        registration_state: Literal["unregistered", "processing", "registered"] = "unregistered"

        async def run_registration(server: RegistrationServer) -> None:
            """Run catalog registration and MCP discovery as a sibling of the receive pump.

            Authority comes only from the authenticated context; the register
            payload carries non-authoritative server metadata. The stable
            mapping is quiesced for the whole discovery window and promotion is
            last, so catalog visibility and routing never split; a displaced
            predecessor is retired only after the replacement registration is
            acknowledged.
            """
            nonlocal registration_state
            stable_id: StableGatewayId | None = None
            quiesced: ConnectionId | None = None
            quiesced_started = False
            db_gateway: DbGateway | None = None
            committed = False
            reachable_committed = False
            registration_claimed = False
            ownership_promoted = False

            async def compensate() -> None:
                """Leave persisted and routing state fail-closed after registration failure."""
                nonlocal registration_claimed
                if stable_id is None:
                    return
                try:
                    db.rollback()
                    if reachable_committed and db_gateway is not None:
                        db_gateway.reachable = False
                        db_gateway.last_seen = datetime.now(tz=timezone.utc)
                        db.commit()
                except Exception:  # pylint: disable=broad-exception-caught
                    LOGGER.warning(
                        "Reverse proxy registration compensation persistence failed",
                        extra={"connection_id": str(connection_id), "stable_id": str(stable_id)},
                        exc_info=True,
                    )
                if ownership_promoted and relay is not None:
                    if release_owners is None:
                        raise RuntimeError("reverse-proxy owner release is unavailable")
                    await release_owners(relay, (ReverseProxyEviction(stable_id, connection_id),))
                    await relay.remove_session(connection_id)
                if registration_claimed and relay is not None:
                    await relay.release_registration(stable_id, connection_id)
                    registration_claimed = False
                if not committed and quiesced_started:
                    await session_manager.restore_stable_id(stable_id, quiesced, connection_id)
                    return
                if not committed:
                    return
                await session_manager.restore_stable_id(stable_id, None, connection_id)
                if quiesced is not None and quiesced != connection_id:
                    await session_manager.retire_connection(quiesced)

            try:
                registration_context = AuthenticatedRegistrationContext(owner_email=authenticated_context.owner_email, team_id=authenticated_context.team_id)
                stable_id = StableGatewayId(stable_proxy_id(registration_context, server))
                if relay is not None:
                    registration_claimed = await relay.claim_registration(stable_id, connection_id)
                    if not registration_claimed:
                        raise RuntimeError("reverse-proxy stable gateway registration is already in progress")
                await session_manager.record_server_info(connection_id, server.model_dump(exclude_none=True))
                catalog = ReverseProxyCatalogService(gateway_service=gateway_service, server_service=server_service)
                discovery = ReverseProxyDiscoveryService(gateway_service=gateway_service, server_service=server_service)
                async with anyio.create_task_group() as lease_tasks:
                    if relay is not None:
                        lease_tasks.start_soon(relay.maintain_registration, stable_id, connection_id)
                    entry = await catalog.register(db, registration_context, server, commit=False)
                    if entry.stable_id != stable_id:
                        raise ReverseProxyCatalogConflictError(stable_id=entry.stable_id, reason="catalog returned an unexpected stable ID")
                    db_gateway = db.get(DbGateway, entry.stable_id)
                    db_server = db.get(DbServer, entry.stable_id)
                    if db_gateway is None or db_server is None:
                        raise ReverseProxyCatalogConflictError(stable_id=entry.stable_id, reason="catalog pair was not persisted")
                    async with session_manager.registration_lock(stable_id):
                        quiesced = await session_manager.quiesce_stable_id(stable_id)
                        quiesced_started = True
                        await discovery.discover_and_reconcile(
                            db,
                            session_manager,
                            connection_id,
                            db_gateway,
                            db_server,
                            timeout_seconds=float(settings.tool_timeout),
                            commit=False,
                            mark_reachable=False,
                        )
                        if relay is not None and not await relay.heartbeat_registration(stable_id, connection_id):
                            raise RuntimeError("reverse-proxy registration authority was lost")
                        db.commit()
                        committed = True
                        if relay is not None:
                            ownership_promoted = await relay.promote_registration(stable_id, connection_id)
                            if not ownership_promoted:
                                raise RuntimeError("reverse-proxy registration authority was lost")
                        await session_manager.promote_stable_id(stable_id, connection_id)
                        db_gateway.reachable = True
                        db_gateway.last_seen = datetime.now(tz=timezone.utc)
                        if relay is not None and not await relay.heartbeat_registration(stable_id, connection_id):
                            raise RuntimeError("reverse-proxy registration authority was lost")
                        db.commit()
                        reachable_committed = True
                        if relay is not None:
                            await relay.publish_session(stable_id, connection_id)
                        await catalog.publish_post_commit_effects(db, registration_context, server, entry)
                        await discovery.publish_post_commit_effects(db_gateway, db_server)
                    registration_state = "registered"
                    LOGGER.info(f"Registered server for connection {connection_id}: {server.name}")
                    await send_frame(encode_server_message(register_complete(str(connection_id), RegistrationStatus.SUCCESS)))
                    if relay is not None:
                        await relay.release_registration(stable_id, connection_id)
                        registration_claimed = False
                    lease_tasks.cancel_scope.cancel()
                # Retire the quiesced predecessor only after the replacement is
                # acknowledged, so its client reconnects cleanly.
                if quiesced is not None and quiesced != connection_id:
                    await session_manager.retire_connection(quiesced)
                    if relay is not None:
                        await relay.remove_session(quiesced)
            except anyio.get_cancelled_exc_class():
                # Task-group cancellation (disconnect, unregister, duplicate
                # register) still compensates under a shield, then re-raises.
                with anyio.CancelScope(shield=True):
                    await compensate()
                raise
            except Exception:
                LOGGER.error("Reverse proxy registration failed for connection %s", connection_id, exc_info=True)
                with anyio.CancelScope(shield=True):
                    await compensate()
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
                            frame = await connection_io.receive_text()
                            if len(frame.encode("utf-8")) > _MAX_WEBSOCKET_FRAME_BYTES:
                                await connection_io.close(code=status.WS_1009_MESSAGE_TOO_BIG, reason="message too large")
                                break
                            session_manager.record_received(connection_id, character_count=len(frame))
                            message = parse_client_message(frame)
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
                                heartbeat_at = await session_manager.record_heartbeat(connection_id)
                                await send_frame(encode_server_message(heartbeat(str(connection_id), heartbeat_at)))
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
        # Shield typed disconnect so cancellation cannot skip authoritative cleanup.
        with anyio.CancelScope(shield=True):
            disconnected_stable_ids = await session_manager.disconnect(connection_id)
            if relay is not None:
                if release_owners is None:
                    raise RuntimeError("reverse-proxy owner release is unavailable")
                await release_owners(relay, disconnected_stable_ids)
                await relay.remove_session(connection_id)
            await _persist_unreachable_best_effort(session_manager, disconnected_stable_ids)
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
