# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FastAPI router for handling reverse proxy connections.

This module provides the WebSocket endpoint for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway.
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, assert_never, Final, Literal, Optional
import uuid

# Third-Party
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from pydantic import ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_user_email
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_db, Permissions
from mcpgateway.db import Server as DbServer
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, PermissionChecker, token_scope_grants
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, ReverseProxyCatalogConflictError, ReverseProxyCatalogService, stable_proxy_id
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
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, get_reverse_proxy_session_manager, LocalSessionId, ReverseProxyEviction, StableGatewayId
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


async def _persist_unreachable_best_effort(session_manager, evictions) -> None:
    """Persist disconnect reachability without masking transport cleanup."""
    try:
        from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel,no-name-in-module

        authority_guard = None
        await gateway_service.mark_reverse_proxy_gateways_unreachable(
            session_manager,
            evictions,
            seen_at=datetime.now(tz=timezone.utc),
            authority_guard=authority_guard,
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
_MAX_WEBSOCKET_FRAME_BYTES: Final = 1024 * 1024


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

            async def compensate() -> None:
                """Leave persisted and routing state fail-closed after registration failure.

                Local restore, demotion, and retirement are guaranteed, and the
                registration-error response is never skipped. A pre-commit
                failure that restored no predecessor re-evaluates reachability
                through the guarded persistence path. Restoration of the
                quiesced predecessor is verified against the live mapping.
                """
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
                persist_unreachable = False
                if not committed and quiesced_started and quiesced is not None:
                    await session_manager.restore_stable_id(stable_id, quiesced, connection_id)
                    if session_manager.resolve_connection_id(stable_id) != quiesced:
                        # The quiesced predecessor is already gone, so restoration was a
                        # silent no-op: only a verified restore keeps the gateway reachable.
                        persist_unreachable = True
                elif not committed:
                    # No predecessor was restored (quiesce never ran or found no local
                    # mapping): re-evaluate reachability.
                    if quiesced_started:
                        await session_manager.restore_stable_id(stable_id, quiesced, connection_id)
                    persist_unreachable = True
                else:
                    await session_manager.restore_stable_id(stable_id, None, connection_id)
                    if quiesced is not None and quiesced != connection_id:
                        await session_manager.retire_connection(quiesced)

                if persist_unreachable:
                    await _persist_unreachable_best_effort(session_manager, (ReverseProxyEviction(stable_id, connection_id),))

            try:
                registration_context = AuthenticatedRegistrationContext(owner_email=authenticated_context.owner_email, team_id=authenticated_context.team_id)
                stable_id = StableGatewayId(stable_proxy_id(registration_context, server))
                catalog = ReverseProxyCatalogService(gateway_service=gateway_service, server_service=server_service)
                discovery = ReverseProxyDiscoveryService(gateway_service=gateway_service, server_service=server_service)
                async with anyio.create_task_group() as lease_tasks:
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
                        db.commit()
                        committed = True
                        await session_manager.promote_stable_id(stable_id, connection_id)
                        db_gateway.reachable = True
                        db_gateway.last_seen = datetime.now(tz=timezone.utc)
                        db.commit()
                        reachable_committed = True
                        await catalog.publish_post_commit_effects(db, registration_context, server, entry)
                        await discovery.publish_post_commit_effects(db_gateway, db_server)
                    registration_state = "registered"
                    LOGGER.info(f"Registered server for connection {connection_id}: {server.name}")
                    await send_frame(encode_server_message(register_complete(str(connection_id), RegistrationStatus.SUCCESS)))
                    lease_tasks.cancel_scope.cancel()
                # Retire the quiesced predecessor only after the replacement is
                # acknowledged, so its client reconnects cleanly.
                if quiesced is not None and quiesced != connection_id:
                    await session_manager.retire_connection(quiesced)
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
            await _persist_unreachable_best_effort(session_manager, disconnected_stable_ids)
        LOGGER.info(f"Reverse proxy session ended: {connection_id}")
