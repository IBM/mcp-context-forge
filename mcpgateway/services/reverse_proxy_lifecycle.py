# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_lifecycle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Reverse-proxy WebSocket connection lifecycle.

This module owns everything that happens after an authenticated
reverse-proxy WebSocket has been accepted: session registration with the
typed session manager, stable-ID catalog registration and MCP discovery
(quiesce-first, promote-on-commit), the continuously-running receive
pump, heartbeat acknowledgement, and the shielded teardown that
disconnects the session and persists reachability best-effort.

The module is transport-agnostic: it never imports FastAPI's WebSocket.
It drives the narrow :class:`ConnectionIO` protocol, which the lock
serializer :class:`_LockedConnectionIO` satisfies over any text
WebSocket transport.
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import assert_never, Final, Literal, Protocol
import uuid

# Third-Party
import anyio
import orjson
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette import status
from starlette.websockets import WebSocketDisconnect

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Server as DbServer
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
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, get_reverse_proxy_session_manager, LocalSessionId, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.services.reverse_proxy_lifecycle")

_MAX_WEBSOCKET_FRAME_BYTES: Final = 1024 * 1024


class ConnectionIO(Protocol):
    """Narrow text-frame transport driven by the connection lifecycle.

    Any object able to send and receive text frames and close with a
    WebSocket close code satisfies this protocol; FastAPI's WebSocket and
    the lock serializer below both conform structurally.
    """

    async def send_text(self, data: str) -> None:
        """Send one serialized text frame."""

    async def receive_text(self) -> str:
        """Receive one text frame, raising WebSocketDisconnect when the transport is lost."""

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the transport with a WebSocket close code and reason."""


@dataclass(frozen=True, slots=True)
class ReverseProxyAuthenticatedContext:
    """Canonical authority retained for an admitted reverse-proxy connection."""

    owner_email: str
    team_id: str | None


async def _persist_unreachable_best_effort(session_manager: ReverseProxySessionManager, evictions: tuple[ReverseProxyEviction, ...]) -> None:
    """Persist disconnect reachability without masking transport cleanup."""
    try:
        from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel,no-name-in-module
        from mcpgateway.services.server_service import server_service  # pylint: disable=import-outside-toplevel,no-name-in-module

        authority_guard = None
        if settings.mcpgateway_reverse_proxy_distributed_enabled:
            from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay  # pylint: disable=import-outside-toplevel

            authority_guard = (await get_reverse_proxy_relay()).unreachable_write_guard
        catalog = ReverseProxyCatalogService(gateway_service=gateway_service, server_service=server_service)
        await catalog.mark_reverse_proxy_gateways_unreachable(
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

    def __init__(self, websocket: ConnectionIO, io_lock: anyio.Lock) -> None:
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


async def run_proxied_connection(connection_io: ConnectionIO, context: ReverseProxyAuthenticatedContext, db: Session) -> None:
    """Run the full lifecycle of one admitted reverse-proxy connection.

    The maintained client contract drives the lifecycle: ``register`` is
    acknowledged as ``register_ack(processing)`` before catalog persistence
    and MCP discovery run, then ``register_complete(success|error)`` closes
    the registration exchange. Heartbeats are acknowledgements, not pongs.
    One continuously-running receive pump owns every inbound frame while
    registration and discovery run as a sibling task, so the client's own
    JSON-RPC discovery responses always resolve.

    Args:
        connection_io: Lock-serialized text-frame transport for this connection.
        context: Authenticated principal and team authority for registration.
        db: Database session.
    """
    # Resolve the shared service singletons on first endpoint use (they are PEP 562
    # lazy module attributes), never at module import time.
    from mcpgateway.services.gateway_service import gateway_service  # pylint: disable=import-outside-toplevel,no-name-in-module
    from mcpgateway.services.server_service import server_service  # pylint: disable=import-outside-toplevel,no-name-in-module

    session_manager = await get_reverse_proxy_session_manager()
    relay = None
    release_owners = None
    if settings.mcpgateway_reverse_proxy_distributed_enabled:
        from mcpgateway.services.reverse_proxy_relay_runtime import get_reverse_proxy_relay, release_reverse_proxy_owners_best_effort  # pylint: disable=import-outside-toplevel

        relay = await get_reverse_proxy_relay()
        release_owners = release_reverse_proxy_owners_best_effort
    connection = await session_manager.connect(connection_io, LocalSessionId(uuid.uuid4().hex), owner_email=context.owner_email)
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
            registration_claimed = False
            ownership_promoted = False
            stable_id: StableGatewayId | None = None
            quiesced: ConnectionId | None = None
            quiesced_started = False
            db_gateway: DbGateway | None = None
            committed = False
            reachable_committed = False

            async def compensate() -> None:
                """Leave persisted and routing state fail-closed after registration failure.

                Local restore, demotion, and retirement are guaranteed; every
                Redis cleanup is independently best-effort so a relay outage can
                never strand routing state or skip the registration-error
                response. A pre-commit failure that restored no predecessor
                re-evaluates reachability through the guarded persistence path
                once this registrant's lease is released, so an eviction denied
                by that lease is not permanently dropped. Restoration of the
                quiesced predecessor is verified against the live mapping; when
                it cannot be confirmed, the predecessor's stale owner generation
                is compare-released fenced before that re-evaluation.
                """
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
                persist_unreachable = False
                stale_predecessor: ConnectionId | None = None
                try:
                    if not committed and quiesced_started and quiesced is not None:
                        await session_manager.restore_stable_id(stable_id, quiesced, connection_id)
                        if session_manager.resolve_connection_id(stable_id) != quiesced:
                            # The quiesced predecessor is already gone, so restoration was a
                            # silent no-op: only a verified restore keeps the gateway reachable.
                            stale_predecessor = quiesced
                            persist_unreachable = True
                    elif not committed:
                        # No predecessor was restored (quiesce never ran or found no local
                        # mapping): re-evaluate reachability once the lease release below lands.
                        if quiesced_started:
                            await session_manager.restore_stable_id(stable_id, quiesced, connection_id)
                        persist_unreachable = True
                    else:
                        await session_manager.restore_stable_id(stable_id, None, connection_id)
                        if quiesced is not None and quiesced != connection_id:
                            await session_manager.retire_connection(quiesced)
                finally:
                    if relay is not None:
                        if stale_predecessor is not None:
                            if release_owners is None:
                                LOGGER.error(
                                    "Reverse proxy owner release is unavailable during registration compensation",
                                    extra={"connection_id": str(connection_id), "stable_id": str(stable_id)},
                                )
                            else:
                                # Fenced compare-delete: a newer owner generation never matches.
                                await release_owners(relay, (ReverseProxyEviction(stable_id, stale_predecessor),))
                        if ownership_promoted:
                            if release_owners is None:
                                LOGGER.error(
                                    "Reverse proxy owner release is unavailable during registration compensation",
                                    extra={"connection_id": str(connection_id), "stable_id": str(stable_id)},
                                )
                            else:
                                await release_owners(relay, (ReverseProxyEviction(stable_id, connection_id),))
                            try:
                                await relay.remove_session(connection_id)
                            except Exception:  # pylint: disable=broad-exception-caught  # best-effort directory cleanup
                                LOGGER.warning(
                                    "Reverse proxy session directory cleanup failed during registration compensation",
                                    extra={"connection_id": str(connection_id), "stable_id": str(stable_id)},
                                    exc_info=True,
                                )
                        if registration_claimed:
                            try:
                                await relay.release_registration(stable_id, connection_id)
                            except Exception:  # pylint: disable=broad-exception-caught  # the lease still expires by TTL
                                LOGGER.warning(
                                    "Reverse proxy registration lease release failed during compensation",
                                    extra={"connection_id": str(connection_id), "stable_id": str(stable_id)},
                                    exc_info=True,
                                )
                            else:
                                registration_claimed = False

                if persist_unreachable:
                    # Runs only after the finally's lease release: a registration
                    # lease still held by this registrant would deny the synthetic
                    # eviction's guard, re-dropping the denied old-worker write.
                    await _persist_unreachable_best_effort(session_manager, (ReverseProxyEviction(stable_id, connection_id),))

            try:
                registration_context = AuthenticatedRegistrationContext(owner_email=context.owner_email, team_id=context.team_id)
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
            try:
                if relay is not None:
                    if release_owners is None:
                        LOGGER.error("Reverse-proxy owner release is unavailable during session teardown", extra={"connection_id": str(connection_id)})
                    else:
                        await release_owners(relay, disconnected_stable_ids)
                    try:
                        await relay.remove_session(connection_id)
                    except Exception:  # pylint: disable=broad-exception-caught  # best-effort directory cleanup
                        LOGGER.warning("Reverse-proxy session directory cleanup failed during session teardown", extra={"connection_id": str(connection_id)}, exc_info=True)
            finally:
                await _persist_unreachable_best_effort(session_manager, disconnected_stable_ids)
        LOGGER.info(f"Reverse proxy session ended: {connection_id}")
