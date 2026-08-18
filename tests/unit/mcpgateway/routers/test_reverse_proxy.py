# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for reverse proxy router.
This module tests the reverse proxy functionality including WebSocket connections,
session management, and HTTP endpoints.
"""

# Standard
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import math
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, call, MagicMock, Mock, patch

# Third-Party
import anyio
from anyio.lowlevel import checkpoint
import anyio.to_thread
import orjson

# Third-Party
from fastapi import APIRouter, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest
# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Permissions
from mcpgateway.services.gateway_service import GatewayCatalogReconcileResult
from mcpgateway.routers.reverse_proxy import router
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, ReverseProxyCatalogService
from mcpgateway.services.reverse_proxy_discovery import ReverseProxyDiscoveryService
from mcpgateway.services.reverse_proxy_protocol import JsonRpcRequest
from mcpgateway.services.reverse_proxy_relay_models import RelayOwner, RelaySessionEntry
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, LocalSessionId, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId
from mcpgateway.services.reverse_proxy_sessions import ReverseProxySession as ManagedSession
from mcpgateway.utils.verify_credentials import require_auth
from tests.helpers.router_helpers import collect_routes

# --------------------------------------------------------------------------- #
# Test Fixtures                                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = Mock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.close = AsyncMock()
    ws.headers = {"X-Session-ID": "test-session-123"}
    ws.query_params = {}
    ws.client = Mock(host="127.0.0.1")
    ws.scope = {"type": "websocket", "state": {}}
    return ws


# --------------------------------------------------------------------------- #
# Scripted WebSocket fakes (real anyio scheduling)                           #
# --------------------------------------------------------------------------- #


class ScriptedReverseProxyWebSocket:
    """Fake reverse-proxy client WebSocket driving real anyio scheduling.

    Unlike the AsyncMock-based ``mock_websocket`` (whose scripted side effects
    never yield to the event loop), this fake suspends the endpoint's receive
    pump on a real anyio stream so a sibling registration task runs
    concurrently, exactly as it would against a live client.
    """

    def __init__(self) -> None:
        """Initialize with an empty incoming-frame stream."""
        self._send_stream, self._receive_stream = anyio.create_memory_object_stream[str](math.inf)
        self.sent_frames: list[dict] = []
        self.accepted = False
        self.closed_code: int | None = None
        self.closed = anyio.Event()
        self.headers: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.scope: dict = {"type": "websocket", "state": {}}

    def queue_client_frame(self, frame: dict) -> None:
        """Queue one client frame for the endpoint's receive pump."""
        self._send_stream.send_nowait(orjson.dumps(frame).decode())

    def queue_disconnect(self) -> None:
        """Close the client stream so the pump observes a disconnect."""
        self._send_stream.close()

    async def accept(self) -> None:
        """Record the acceptance."""
        self.accepted = True

    async def send_text(self, data: str) -> None:
        """Capture one server frame; auto-disconnect once registration completes."""
        frame = orjson.loads(data)
        self.sent_frames.append(frame)
        if frame.get("type") == "register_complete":
            self.queue_disconnect()

    async def receive_text(self) -> str:
        """Return the next scripted client frame, raising disconnect at stream end."""
        try:
            return await self._receive_stream.receive()
        except anyio.EndOfStream:
            raise WebSocketDisconnect()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Record a server-initiated close and end the client stream."""
        self.closed_code = code
        self.closed.set()
        self._send_stream.close()


class DiscoveryAnsweringWebSocket(ScriptedReverseProxyWebSocket):
    """Scripted client that answers the discovery initialize handshake.

    Advertises empty capabilities so the handshake needs no list pagination.
    """

    async def send_text(self, data: str) -> None:
        """Capture the server frame and reply to the initialize request."""
        frame = orjson.loads(data)
        self.sent_frames.append(frame)
        frame_type = frame.get("type")
        if frame_type == "request":
            payload = frame["payload"]
            if payload.get("method") == "initialize":
                self.queue_client_frame(
                    {
                        "type": "response",
                        "payload": {
                            "jsonrpc": "2.0",
                            "id": payload["id"],
                            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "scripted-client", "version": "0.0.0"}},
                        },
                    }
                )
        elif frame_type == "register_complete":
            self.queue_disconnect()


class TrackedRegistrationWebSocket(ScriptedReverseProxyWebSocket):
    """Scripted client that stays connected after a successful registration."""

    def __init__(self) -> None:
        """Initialize with a registration-completion signal and an open stream."""
        super().__init__()
        self.registration_completed = anyio.Event()

    async def send_text(self, data: str) -> None:
        """Capture the server frame and signal registration completion."""
        frame = orjson.loads(data)
        self.sent_frames.append(frame)
        if frame.get("type") == "register_complete":
            self.registration_completed.set()


class LostSocketWebSocket(ScriptedReverseProxyWebSocket):
    """Scripted client whose socket dies while registration is in flight."""

    async def send_text(self, data: str) -> None:
        """Raise a transport error instead of delivering a register_complete frame."""
        frame = orjson.loads(data)
        if frame.get("type") == "register_complete":
            self._send_stream.close()
            raise ConnectionError("socket lost during registration")
        self.sent_frames.append(frame)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Record the close attempt, then raise because the socket is already gone."""
        self.closed_code = code
        raise ConnectionError("close on a lost socket")


class PendingTrackedWebSocket(TrackedRegistrationWebSocket):
    """Scripted client that also signals when a server JSON-RPC request frame is sent."""

    def __init__(self) -> None:
        """Initialize with an additional request-sent signal."""
        super().__init__()
        self.request_sent = anyio.Event()

    async def send_text(self, data: str) -> None:
        """Capture the server frame, signal registration completion, and signal request frames."""
        frame = orjson.loads(data)
        self.sent_frames.append(frame)
        frame_type = frame.get("type")
        if frame_type == "register_complete":
            self.registration_completed.set()
        elif frame_type == "request":
            self.request_sent.set()


# --------------------------------------------------------------------------- #
# WebSocket Endpoint Tests                                                   #
# --------------------------------------------------------------------------- #


class TestWebSocketEndpoint:
    """Test the typed WebSocket lifecycle against the session manager, catalog, and discovery seams.

    Admission is mocked at the ``_authenticate_reverse_proxy_websocket`` seam;
    deny-path coverage lives in TestWebSocketAuthentication and friends.
    """

    _CONNECTION_ID = ConnectionId("test-connection-id")
    _STABLE_ID = "stable-test-id"

    @pytest.fixture(autouse=True)
    def mock_auth_settings(self):
        """Authenticate lifecycle tests through the admission seam."""
        context = SimpleNamespace(owner_email="test-user@example.com", team_id=None)
        with patch("mcpgateway.routers.reverse_proxy._authenticate_reverse_proxy_websocket", new=AsyncMock(return_value=context)) as authenticate:
            yield authenticate

    @pytest.fixture
    def session_manager(self, mock_websocket):
        """Scripted session manager with a fixed server-generated connection id."""
        fake = Mock(spec=ReverseProxySessionManager)
        fake.connect.return_value = ManagedSession(connection_id=self._CONNECTION_ID, local_id=LocalSessionId("local-test-id"), websocket=mock_websocket, last_heartbeat=datetime.now(tz=timezone.utc))
        fake.registration_lock.side_effect = lambda stable_id: anyio.Lock()
        fake.quiesce_stable_id.return_value = None
        fake.promote_stable_id.return_value = None
        fake.disconnect.return_value = ()
        return fake

    @pytest.fixture(autouse=True)
    def patch_session_manager(self, session_manager):
        """Route the endpoint's session-manager singleton to the scripted fake."""
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=session_manager)):
            yield

    @pytest.fixture(autouse=True)
    def distributed_relay(self, monkeypatch):
        relay = MagicMock(
            claim_registration=AsyncMock(return_value=True),
            heartbeat_registration=AsyncMock(return_value=True),
            maintain_registration=AsyncMock(return_value=None),
            promote_registration=AsyncMock(return_value=True),
            publish_session=AsyncMock(),
            remove_session=AsyncMock(),
            release_registration=AsyncMock(return_value=True),
            release_owner=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)
        with patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", new=AsyncMock(return_value=relay)):
            yield relay

    @pytest.fixture(autouse=True)
    def catalog_service(self):
        """Mock catalog registration at the router import site."""
        service = Mock(spec=ReverseProxyCatalogService)
        service.register.return_value = SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())
        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service),
            patch("mcpgateway.routers.reverse_proxy.stable_proxy_id", return_value=self._STABLE_ID),
        ):
            yield service

    @pytest.fixture(autouse=True)
    def discovery_service(self):
        """Mock MCP discovery at the router import site."""
        service = Mock(spec=ReverseProxyDiscoveryService)
        service.discover_and_reconcile.return_value = Mock()
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=service):
            yield service

    @staticmethod
    def _sent_frames(mock_websocket) -> list[dict]:
        """Decode every frame the endpoint sent, in send order."""
        return [orjson.loads(call_args.args[0]) for call_args in mock_websocket.send_text.call_args_list]

    @pytest.mark.asyncio
    async def test_websocket_accept(self, mock_websocket, session_manager):
        """Accept follows admission, and disconnect cleans up typed state."""
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_called_once()
        session_manager.connect.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_generates_connection_id_server_side(self, mock_websocket, session_manager, catalog_service, discovery_service):
        """The client-supplied X-Session-ID never becomes connection identity."""
        mock_websocket.headers = {"X-Session-ID": "client-controlled"}
        register_msg = {"type": "register", "server": {"name": "test-server"}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(register_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        ack = self._sent_frames(mock_websocket)[0]
        assert ack["sessionId"] == str(self._CONNECTION_ID)
        assert ack["sessionId"] != "client-controlled"

    @pytest.mark.asyncio
    async def test_websocket_register_message(self, session_manager, catalog_service, discovery_service, distributed_relay):
        """Register drives ack(processing) -> catalog -> quiesce -> discovery -> publish -> promote -> complete(success)."""
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server", "description": "Test server", "protocol": "mcp"}})
        db = Mock()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), db)

        frames = websocket.sent_frames
        assert [frame["type"] for frame in frames] == ["register_ack", "register_complete"]
        assert frames[0]["status"] == "processing"
        assert frames[0]["sessionId"] == str(self._CONNECTION_ID)
        assert frames[1]["status"] == "success"
        assert frames[1]["sessionId"] == str(self._CONNECTION_ID)

        catalog_service.register.assert_awaited_once()
        register_call = catalog_service.register.await_args
        context = register_call.args[1]
        assert isinstance(context, AuthenticatedRegistrationContext)
        assert context.owner_email == "test-user@example.com"
        assert context.team_id is None
        assert register_call.args[2].name == "test-server"
        assert register_call.kwargs["commit"] is False

        session_manager.promote_stable_id.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        distributed_relay.claim_registration.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        distributed_relay.promote_registration.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        discovery_service.publish_post_commit_effects.assert_awaited_once()

        discovery_service.discover_and_reconcile.assert_awaited_once()
        discovery_call = discovery_service.discover_and_reconcile.await_args
        assert discovery_call.args[1] is session_manager
        assert discovery_call.args[2] == self._CONNECTION_ID
        assert discovery_call.args[3] is not None  # db_gateway row
        assert discovery_call.args[4] is not None  # db_server row
        assert discovery_call.kwargs["timeout_seconds"] == float(settings.tool_timeout)
        assert discovery_call.kwargs["commit"] is False
        assert discovery_call.kwargs["mark_reachable"] is False
        assert db.commit.call_count == 2

        assert websocket.closed_code is None

    @pytest.mark.asyncio
    async def test_distributed_registration_lease_loss_prevents_catalog_write_and_closes_candidate(self, session_manager, distributed_relay, catalog_service, discovery_service):
        distributed_relay.claim_registration.return_value = False
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), Mock())

        assert [frame["type"] for frame in websocket.sent_frames] == ["register_ack", "register_complete"]
        assert websocket.sent_frames[-1]["status"] == "error"
        catalog_service.register.assert_not_awaited()
        discovery_service.discover_and_reconcile.assert_not_awaited()
        session_manager.promote_stable_id.assert_not_awaited()
        distributed_relay.promote_registration.assert_not_awaited()
        session_manager.disconnect.assert_awaited_with(self._CONNECTION_ID)
        assert websocket.closed_code == status.WS_1008_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_websocket_register_catalog_failure_closes_connection(self, session_manager, catalog_service, discovery_service):
        """Catalog failure -> register_complete(error) then close 1008; discovery never runs."""
        catalog_service.register.side_effect = RuntimeError("catalog exploded")
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), Mock())

        frames = websocket.sent_frames
        assert [frame["type"] for frame in frames] == ["register_ack", "register_complete"]
        assert frames[1]["status"] == "error"
        assert frames[1]["message"] == "registration failed"
        assert "catalog exploded" not in frames[1]["message"]
        assert websocket.closed_code == 1008
        session_manager.promote_stable_id.assert_not_awaited()
        session_manager.restore_stable_id.assert_not_awaited()
        discovery_service.discover_and_reconcile.assert_not_awaited()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_register_discovery_failure_closes_connection(self, session_manager, catalog_service, discovery_service):
        """Discovery failure -> register_complete(error) then close 1008; the stable mapping is never promoted."""
        discovery_service.discover_and_reconcile.side_effect = RuntimeError("discovery exploded")
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), Mock())

        frames = websocket.sent_frames
        assert [frame["type"] for frame in frames] == ["register_ack", "register_complete"]
        assert frames[1]["status"] == "error"
        assert frames[1]["message"] == "registration failed"
        assert "discovery exploded" not in frames[1]["message"]
        assert websocket.closed_code == 1008
        catalog_service.register.assert_awaited_once()
        session_manager.promote_stable_id.assert_not_awaited()
        session_manager.restore_stable_id.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), None, self._CONNECTION_ID)
        discovery_service.publish_post_commit_effects.assert_not_awaited()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_registration_compensation_commit_failure_still_releases_generation(self, session_manager, distributed_relay, catalog_service, discovery_service):
        """A failed unreachable commit cannot strand Redis or local registration authority."""
        catalog_service.publish_post_commit_effects.side_effect = RuntimeError("publish exploded")
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})
        db = Mock()
        db.get.side_effect = [MagicMock(name="db_gateway"), MagicMock(name="db_server")]
        db.commit.side_effect = [None, None, RuntimeError("compensation commit failed")]

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), db)

        assert [frame["type"] for frame in websocket.sent_frames] == ["register_ack", "register_complete"]
        assert websocket.sent_frames[-1]["status"] == "error"
        distributed_relay.release_owner.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        distributed_relay.release_registration.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        session_manager.restore_stable_id.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), None, self._CONNECTION_ID)
        assert websocket.closed_code == status.WS_1008_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_websocket_heartbeat_message(self, mock_websocket, session_manager, catalog_service):
        """Heartbeat is acknowledged with the connection-scoped id and a timestamp."""
        heartbeat_msg = {"type": "heartbeat"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(heartbeat_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        frames = self._sent_frames(mock_websocket)
        assert len(frames) == 1
        assert frames[0]["type"] == "heartbeat"
        assert frames[0]["sessionId"] == str(self._CONNECTION_ID)
        assert "timestamp" in frames[0]
        session_manager.record_heartbeat.assert_awaited_once()
        assert session_manager.record_heartbeat.await_args.args[0] == self._CONNECTION_ID
        catalog_service.register.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_response_resolves_pending_request(self, mock_websocket, session_manager):
        """A response frame resolves the pending request through the connection-scoped id."""
        response_msg = {"type": "response", "payload": {"jsonrpc": "2.0", "id": "req-1", "result": {"ok": True}}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(response_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        session_manager.resolve_response.assert_called_once()
        resolve_call = session_manager.resolve_response.call_args
        assert resolve_call.args[0] == self._CONNECTION_ID
        assert resolve_call.args[1].payload.id == "req-1"
        mock_websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_duplicate_register_closes_connection(self, session_manager, catalog_service, discovery_service):
        """D13: a second register on one connection is an error and closes 1008."""
        register_msg = {"type": "register", "server": {"name": "test-server"}}
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame(register_msg)
        websocket.queue_client_frame(register_msg)

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), Mock())

        # The lock-serialized registration yields before completing, so the pump
        # rejects the buffered duplicate first; the in-flight registration may
        # still complete on the dying connection. The contract: ack first, the
        # duplicate is rejected with exactly one error, the connection closes 1008.
        frames = websocket.sent_frames
        frame_types = [frame["type"] for frame in frames]
        assert frame_types[0] == "register_ack"
        assert frame_types.count("error") == 1
        assert "already registered" in frames[frame_types.index("error")]["message"]
        assert websocket.closed_code == 1008
        catalog_service.register.assert_awaited_once()
        discovery_service.discover_and_reconcile.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_unregister_message(self, mock_websocket, session_manager):
        """Unregister ends the connection cleanly without server frames or close."""
        unregister_msg = {"type": "unregister"}
        mock_websocket.receive_text.return_value = orjson.dumps(unregister_msg).decode()
        session_manager.disconnect.return_value = (ReverseProxyEviction(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID),)

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        db = Mock()
        from mcpgateway.services.gateway_service import gateway_service

        gateway_service.mark_reverse_proxy_gateways_unreachable = AsyncMock()
        await websocket_endpoint(mock_websocket, db)

        mock_websocket.accept.assert_called_once()
        mock_websocket.send_text.assert_not_called()
        mock_websocket.close.assert_not_called()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)
        gateway_service.mark_reverse_proxy_gateways_unreachable.assert_awaited_once()
        persistence_call = gateway_service.mark_reverse_proxy_gateways_unreachable.await_args
        assert persistence_call is not None
        assert persistence_call.args[0] is session_manager

    @pytest.mark.asyncio
    async def test_websocket_invalid_json(self, mock_websocket, session_manager):
        """Malformed frames get a typed error frame; the connection stays up."""
        mock_websocket.receive_text.side_effect = ["invalid json", WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        session_manager.connect.assert_awaited_once()
        frames = self._sent_frames(mock_websocket)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["sessionId"] == str(self._CONNECTION_ID)
        mock_websocket.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_oversized_frame_closes_before_parsing(self, mock_websocket, session_manager):
        """Authenticated frames over the application limit close with message-too-big."""
        from mcpgateway.routers import reverse_proxy as rp

        oversized_frame = "x" * (rp._MAX_WEBSOCKET_FRAME_BYTES + 1)
        mock_websocket.receive_text.return_value = oversized_frame

        await rp.websocket_endpoint(mock_websocket, Mock())

        session_manager.record_received.assert_not_called()
        mock_websocket.send_text.assert_not_called()
        mock_websocket.close.assert_awaited_once_with(code=1009, reason="message too large")

    @pytest.mark.asyncio
    async def test_websocket_inbound_accounting_uses_unicode_character_count(self, mock_websocket, session_manager):
        """Router receive accounting passes text length rather than encoded byte length."""
        frame = '{"type":"notification","payload":{"jsonrpc":"2.0","method":"通知/更新"}}'
        mock_websocket.receive_text.side_effect = [frame, WebSocketDisconnect()]

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        session_manager.record_received.assert_called_once_with(self._CONNECTION_ID, character_count=len(frame))
        assert len(frame) < len(frame.encode())

    @pytest.mark.asyncio
    async def test_websocket_unknown_message_type(self, mock_websocket, session_manager):
        """Frames outside the client contract are rejected with a typed error frame."""
        unknown_msg = {"type": "unknown", "data": "test"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(unknown_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        frames = self._sent_frames(mock_websocket)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_websocket_notification_message(self, mock_websocket, session_manager):
        """Client notifications are accepted without a server reply."""
        notification_msg = {"type": "notification", "payload": {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "req-1"}}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(notification_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        session_manager.connect.assert_awaited_once()
        mock_websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_unexpected_error_disconnects_typed_manager(self, mock_websocket, session_manager):
        """An unexpected loop error propagates but still disconnects typed state."""
        mock_websocket.receive_text.side_effect = [RuntimeError("boom"), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with pytest.raises(RuntimeError, match="boom"):
            await websocket_endpoint(mock_websocket, Mock())

        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_persistence_failure_preserves_primary_exception_and_cleanup(self, mock_websocket, session_manager):
        """Reachability persistence cannot replace the receive failure or strand typed cleanup."""
        mock_websocket.receive_text.side_effect = [RuntimeError("primary boom"), asyncio.CancelledError()]
        session_manager.disconnect.return_value = (ReverseProxyEviction(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID),)
        from mcpgateway.services.gateway_service import gateway_service
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch.object(gateway_service, "mark_reverse_proxy_gateways_unreachable", new=AsyncMock(side_effect=RuntimeError("db unavailable"))):
            with pytest.raises(RuntimeError, match="primary boom"):
                await websocket_endpoint(mock_websocket, Mock())

    @pytest.mark.asyncio
    async def test_websocket_registration_failure_notification_is_best_effort(self, session_manager, catalog_service, discovery_service):
        """F4: a socket lost mid-registration must not mask the registration failure path."""
        discovery_service.discover_and_reconcile.side_effect = RuntimeError("discovery exploded")
        websocket = LostSocketWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.LOGGER.debug") as debug_log:
            await websocket_endpoint(cast(WebSocket, websocket), Mock())

        assert [frame["type"] for frame in websocket.sent_frames] == ["register_ack"]
        debug_log.assert_called()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_constructs_wrappers_with_both_service_singletons(self, session_manager):
        """F2: catalog and discovery wrappers both receive the shared gateway and server services."""
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        catalog = Mock(spec=ReverseProxyCatalogService)
        catalog.register.return_value = SimpleNamespace(stable_id="stable-singletons", gateway=Mock(), server=Mock())
        discovery = Mock(spec=ReverseProxyDiscoveryService)
        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=catalog) as catalog_class,
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery) as discovery_class,
        ):
            await websocket_endpoint(cast(WebSocket, websocket), Mock())

        assert catalog_class.call_args.kwargs.keys() == {"gateway_service", "server_service"}
        assert discovery_class.call_args.kwargs.keys() == {"gateway_service", "server_service"}
        assert catalog_class.call_args.kwargs["gateway_service"] is discovery_class.call_args.kwargs["gateway_service"]
        assert catalog_class.call_args.kwargs["server_service"] is discovery_class.call_args.kwargs["server_service"]


class TestWebSocketRegistrationIntegration:
    """Integration regression for the B1 registration deadlock.

    The wire path is fully real: a REAL ``ReverseProxySessionManager`` and the
    REAL ``ReverseProxyDiscoveryService`` run against a scripted client that
    answers the discovery ``initialize`` handshake. Only the catalog register
    call and the DB-facing gateway-service seam are mocked. Against the former
    single-receive-loop endpoint this test deadlocked (discovery's own
    responses could never be received) and fails here by ``anyio.fail_after``
    timeout; after the pump/sibling-task restructure it passes.
    """

    _STABLE_ID = "stable-integration-id"

    @pytest.fixture(autouse=True)
    def mock_admission(self):
        """Authenticate through the admission seam."""
        context = SimpleNamespace(owner_email="integration-user@example.com", team_id=None)
        with patch("mcpgateway.routers.reverse_proxy._authenticate_reverse_proxy_websocket", new=AsyncMock(return_value=context)):
            yield

    @pytest.fixture
    def real_session_manager(self):
        """A fresh REAL session manager (never mocked) for the wire path."""
        return ReverseProxySessionManager()

    @pytest.fixture(autouse=True)
    def patch_session_manager_singleton(self, real_session_manager):
        """Route the endpoint's session-manager singleton to the real instance."""
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=real_session_manager)):
            yield

    @pytest.fixture(autouse=True)
    def catalog_service(self):
        """Mock ONLY ``ReverseProxyCatalogService.register`` at the router import site."""
        service = Mock(spec=ReverseProxyCatalogService)
        service.register.return_value = SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())
        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service),
            patch("mcpgateway.routers.reverse_proxy.stable_proxy_id", return_value=self._STABLE_ID),
        ):
            yield service

    @pytest.fixture
    def gateway_service_mock(self):
        """Mock the DB-facing gateway-service seam used by REAL discovery."""
        service = MagicMock()
        service._validate_tools.return_value = ([], [])
        service._sync_gateway_catalog.return_value = MagicMock(name="catalog_sync")
        service._reconcile_gateway_catalog.return_value = GatewayCatalogReconcileResult(tools_added=0, resources_added=0, prompts_added=0, tools_removed=0, resources_removed=0, prompts_removed=0)
        return service

    @pytest.fixture(autouse=True)
    def patch_gateway_service_seams(self, gateway_service_mock):
        """Inject the mocked seam into discovery on both pre- and post-restructure code.

        ``create=True`` lets the router-module symbol patch apply even before the
        router gains its shared-singleton import, so this identical test runs red
        against the pre-restructure endpoint.
        """
        registry_cache = MagicMock()
        registry_cache.invalidate_tools = AsyncMock()
        registry_cache.invalidate_resources = AsyncMock()
        registry_cache.invalidate_prompts = AsyncMock()
        registry_cache.invalidate_servers = AsyncMock()
        tool_lookup_cache = MagicMock()
        tool_lookup_cache.invalidate_gateway = AsyncMock()
        with (
            patch("mcpgateway.routers.reverse_proxy.gateway_service", gateway_service_mock, create=True),
            patch("mcpgateway.services.reverse_proxy_discovery.GatewayService", return_value=gateway_service_mock),
            patch("mcpgateway.services.reverse_proxy_discovery._get_registry_cache", return_value=registry_cache),
            patch("mcpgateway.services.reverse_proxy_discovery._get_tool_lookup_cache", return_value=tool_lookup_cache),
        ):
            yield

    @pytest.fixture
    def mock_db(self):
        """Mock db whose ``get`` returns non-None catalog rows."""
        db = MagicMock()
        db.get.side_effect = [MagicMock(name="db_gateway"), MagicMock(name="db_server")]
        return db

    @pytest.mark.asyncio
    async def test_registration_completes_while_receive_pump_resolves_discovery_responses(self, real_session_manager, catalog_service, mock_db):
        """Register -> real discovery handshake -> register_complete(success).

        Red against the single-loop endpoint: discovery awaits responses that
        only the (blocked) receive loop could resolve, so ``anyio.fail_after``
        fires long before ``settings.tool_timeout`` would.
        """
        websocket = DiscoveryAnsweringWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "integration-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with anyio.fail_after(10):
            await websocket_endpoint(cast(WebSocket, websocket), mock_db)

        frame_types = [frame["type"] for frame in websocket.sent_frames]
        assert frame_types == ["register_ack", "request", "request", "register_complete"]
        assert websocket.sent_frames[0]["status"] == "processing"
        assert websocket.sent_frames[1]["payload"]["method"] == "initialize"
        assert websocket.sent_frames[2]["payload"]["method"] == "notifications/initialized"
        assert websocket.sent_frames[3]["status"] == "success"
        assert websocket.closed_code is None

        catalog_service.register.assert_awaited_once()
        register_call = catalog_service.register.await_args
        assert isinstance(register_call.args[1], AuthenticatedRegistrationContext)
        assert register_call.args[1].owner_email == "integration-user@example.com"

        connection_id = ConnectionId(websocket.sent_frames[0]["sessionId"])
        assert real_session_manager.pending_count(connection_id) == 0
        assert real_session_manager.resolve_connection_id(StableGatewayId(self._STABLE_ID)) is None


class TestConcurrentRegistrationPromotion:
    """Same-stable-ID registrations serialize through the per-stable-ID registration lock."""

    _STABLE_ID = "stable-race-id"

    @pytest.fixture(autouse=True)
    def mock_admission(self):
        """Authenticate every connection through the admission seam."""
        context = SimpleNamespace(owner_email="owner@example.com", team_id=None)
        with patch("mcpgateway.routers.reverse_proxy._authenticate_reverse_proxy_websocket", new=AsyncMock(return_value=context)):
            yield

    @pytest.fixture
    def real_session_manager(self):
        """A fresh REAL session manager so locking and promotion behave exactly as in production."""
        return ReverseProxySessionManager()

    @pytest.fixture(autouse=True)
    def patch_session_manager_singleton(self, real_session_manager):
        """Route the endpoint's session-manager singleton to the real instance."""
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=real_session_manager)):
            yield

    @pytest.fixture(autouse=True)
    def catalog_service(self):
        """Both connections register the same stable catalog identity."""
        service = Mock(spec=ReverseProxyCatalogService)
        service.register.return_value = SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())
        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service),
            patch("mcpgateway.routers.reverse_proxy.stable_proxy_id", return_value=self._STABLE_ID),
        ):
            yield service

    @staticmethod
    def _mock_db(gateway_name: str, server_name: str) -> tuple[MagicMock, MagicMock]:
        """Build a mock db whose ``get`` returns one gateway row and one server row."""
        db = MagicMock()
        gateway = MagicMock(name=gateway_name)
        db.get.side_effect = [gateway, MagicMock(name=server_name)]
        return db, gateway

    @pytest.mark.asyncio
    async def test_concurrent_same_stable_id_registrations_are_serialized(self, real_session_manager, catalog_service):
        """B's discovery cannot start while A holds the registration lock; the last completed registration owns the mapping and publishes last."""
        events: list[str] = []
        a_in_discovery = anyio.Event()
        release_a = anyio.Event()
        b_catalog_registered = anyio.Event()
        b_discovery_started = anyio.Event()

        async def discover_a(*args, **kwargs):
            events.append("discover:A")
            a_in_discovery.set()
            await release_a.wait()
            return Mock(name="discovery-a")

        async def discover_b(*args, **kwargs):
            b_discovery_started.set()
            events.append("discover:B")
            return Mock(name="discovery-b")

        discovery_handlers = [discover_a, discover_b]

        async def dispatch_discovery(*args, **kwargs):
            return await discovery_handlers.pop(0)(*args, **kwargs)

        db_a, gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        async def publish(db_gateway, db_server):
            events.append("publish:A" if db_gateway is gateway_a else "publish:B")

        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.side_effect = dispatch_discovery
        discovery.publish_post_commit_effects.side_effect = publish

        register_calls = 0

        async def counted_register(*args, **kwargs):
            nonlocal register_calls
            register_calls += 1
            if register_calls == 2:
                b_catalog_registered.set()
            return SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())

        catalog_service.register.side_effect = counted_register

        websocket_a = TrackedRegistrationWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        websocket_b = TrackedRegistrationWebSocket()
        websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await a_in_discovery.wait()
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_b), db_b)
                with anyio.fail_after(5):
                    await b_catalog_registered.wait()
                await checkpoint()
                assert not b_discovery_started.is_set()
                release_a.set()
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                    await websocket_b.registration_completed.wait()

                connection_b = ConnectionId(websocket_b.sent_frames[0]["sessionId"])
                assert real_session_manager.resolve_connection_id(stable_id) == connection_b
                assert events == ["discover:A", "publish:A", "discover:B", "publish:B"]
                # The earlier connection is retired once the later finisher is acknowledged.
                with anyio.fail_after(5):
                    await websocket_a.closed.wait()
                task_group.cancel_scope.cancel()

    @pytest.mark.asyncio
    async def test_success_send_failure_after_commit_demotes_candidate_and_stays_fail_closed(self, real_session_manager):
        """B's register_complete(success) send fails AFTER commit+publish: the candidate is demoted, the quiesced predecessor is retired, and the stable ID resolves to None - never restored to a catalog-incompatible predecessor."""
        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.return_value = Mock(name="discovery-ok")

        websocket_a = TrackedRegistrationWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        db_a, _gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                connection_a = real_session_manager.resolve_connection_id(stable_id)
                assert connection_a is not None

                websocket_b = LostSocketWebSocket()
                websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
                await websocket_endpoint(cast(WebSocket, websocket_b), db_b)

                # The catalog was committed for B, so routing must never fall back
                # to the catalog-incompatible A: the mapping stays absent
                # (fail-closed) and the quiesced predecessor is retired.
                assert real_session_manager.resolve_connection_id(stable_id) is None
                with anyio.fail_after(5):
                    await websocket_a.closed.wait()
                task_group.cancel_scope.cancel()

    @pytest.mark.asyncio
    async def test_dispatch_fails_closed_during_reregistration_discovery_window(self, real_session_manager):
        """While B's re-registration discovery runs, the stable ID resolves to None (fail-closed), never to the quiesced predecessor."""
        discovery_entered = anyio.Event()
        release_discovery = anyio.Event()
        discovery_calls = 0

        async def discover(*args, **kwargs):
            nonlocal discovery_calls
            discovery_calls += 1
            if discovery_calls == 2:
                discovery_entered.set()
                await release_discovery.wait()
            return Mock(name="discovery-result")

        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.side_effect = discover

        websocket_a = TrackedRegistrationWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        websocket_b = TrackedRegistrationWebSocket()
        websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        db_a, _gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                connection_a = real_session_manager.resolve_connection_id(stable_id)
                assert connection_a is not None

                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_b), db_b)
                with anyio.fail_after(5):
                    await discovery_entered.wait()
                # B quiesced the stable mapping for its discovery window:
                # dispatch fails closed instead of routing to the predecessor.
                assert real_session_manager.resolve_connection_id(stable_id) is None

                release_discovery.set()
                with anyio.fail_after(5):
                    await websocket_b.registration_completed.wait()
                connection_b = ConnectionId(websocket_b.sent_frames[0]["sessionId"])
                assert real_session_manager.resolve_connection_id(stable_id) == connection_b
                with anyio.fail_after(5):
                    await websocket_a.closed.wait()
                task_group.cancel_scope.cancel()

    @pytest.mark.asyncio
    async def test_cancellation_during_publish_runs_shielded_post_commit_compensation(self, real_session_manager):
        """Cancelling B's registration mid-publish (post-commit) runs shielded compensation: demote-only restore keeps the mapping fail-closed, the quiesced predecessor is retired (pending calls fail, socket close attempted), and the cancellation still propagates."""
        publish_entered = anyio.Event()
        block_publish = False

        async def publish(db_gateway, db_server):
            if block_publish:
                publish_entered.set()
                await anyio.sleep_forever()

        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.return_value = Mock(name="discovery-ok")
        discovery.publish_post_commit_effects.side_effect = publish

        restore_calls: list[tuple] = []
        original_restore = real_session_manager.restore_stable_id

        async def restore_spy(*args, **kwargs):
            restore_calls.append(args)
            return await original_restore(*args, **kwargs)

        websocket_a = PendingTrackedWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        db_a, _gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        b_done = anyio.Event()

        async def run_b(websocket_b: ScriptedReverseProxyWebSocket) -> None:
            await websocket_endpoint(cast(WebSocket, websocket_b), db_b)
            b_done.set()

        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery),
            patch.object(real_session_manager, "restore_stable_id", new=restore_spy),
        ):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                connection_a = real_session_manager.resolve_connection_id(stable_id)
                assert connection_a is not None

                pending_failed = anyio.Event()

                async def pending_call() -> None:
                    with pytest.raises(ConnectionClosedError):
                        await real_session_manager.send_request(
                            connection_a,
                            JsonRpcRequest.model_validate({"jsonrpc": "2.0", "id": "tool-1", "method": "tools/call"}),
                            timeout_seconds=30,
                        )
                    pending_failed.set()

                task_group.start_soon(pending_call)
                with anyio.fail_after(5):
                    await websocket_a.request_sent.wait()

                block_publish = True
                websocket_b = ScriptedReverseProxyWebSocket()
                websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
                task_group.start_soon(run_b, websocket_b)
                with anyio.fail_after(5):
                    await publish_entered.wait()

                # The client disconnect cancels the in-flight registration mid-publish.
                websocket_b.queue_disconnect()
                with anyio.fail_after(5):
                    await b_done.wait()

                connection_b = ConnectionId(websocket_b.sent_frames[0]["sessionId"])
                # Shielded post-commit compensation demotes the candidate only:
                # the catalog was committed, so the predecessor is never restored.
                assert (stable_id, None, connection_b) in restore_calls
                assert real_session_manager.resolve_connection_id(stable_id) is None
                # ...but the quiesced predecessor IS retired, mirroring the ordinary
                # post-commit failure branch: its pending calls fail and its socket closes.
                with anyio.fail_after(5):
                    await pending_failed.wait()
                    await websocket_a.closed.wait()
                assert websocket_a.closed_code is not None
                # The cancellation still propagates: B is never told the registration
                # completed - only the register ack went out.
                assert [frame["type"] for frame in websocket_b.sent_frames] == ["register_ack"]
                task_group.cancel_scope.cancel()

    @pytest.mark.asyncio
    async def test_cancellation_during_discovery_restores_quiesced_predecessor(self, real_session_manager):
        """Cancelling B's registration mid-discovery (pre-commit) runs shielded compensation that restores the still-healthy predecessor, then re-raises."""
        discovery_entered = anyio.Event()
        discovery_calls = 0

        async def discover(*args, **kwargs):
            nonlocal discovery_calls
            discovery_calls += 1
            if discovery_calls == 2:
                discovery_entered.set()
                await anyio.sleep_forever()
            return Mock(name="discovery-result")

        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.side_effect = discover

        restore_calls: list[tuple] = []
        original_restore = real_session_manager.restore_stable_id

        async def restore_spy(*args, **kwargs):
            restore_calls.append(args)
            return await original_restore(*args, **kwargs)

        websocket_a = TrackedRegistrationWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        db_a, _gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        b_done = anyio.Event()

        async def run_b(websocket_b: ScriptedReverseProxyWebSocket) -> None:
            await websocket_endpoint(cast(WebSocket, websocket_b), db_b)
            b_done.set()

        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery),
            patch.object(real_session_manager, "restore_stable_id", new=restore_spy),
        ):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                connection_a = real_session_manager.resolve_connection_id(stable_id)
                assert connection_a is not None

                websocket_b = ScriptedReverseProxyWebSocket()
                websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
                task_group.start_soon(run_b, websocket_b)
                with anyio.fail_after(5):
                    await discovery_entered.wait()

                # The client disconnect cancels the in-flight registration before commit.
                websocket_b.queue_disconnect()
                with anyio.fail_after(5):
                    await b_done.wait()

                connection_b = ConnectionId(websocket_b.sent_frames[0]["sessionId"])
                # Shielded pre-commit compensation restores the quiesced predecessor:
                # the catalog was never replaced, so routing back to A stays consistent.
                assert (stable_id, connection_a, connection_b) in restore_calls
                assert real_session_manager.resolve_connection_id(stable_id) == connection_a
                task_group.cancel_scope.cancel()

    @pytest.mark.asyncio
    async def test_displaced_connection_is_retired_after_replacement_acknowledged(self, real_session_manager):
        """After B displaces A and is acknowledged, A's pending calls fail with ConnectionClosedError and A's socket close is attempted."""
        discovery = Mock(spec=ReverseProxyDiscoveryService)
        discovery.discover_and_reconcile.return_value = Mock(name="discovery-ok")

        websocket_a = PendingTrackedWebSocket()
        websocket_a.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
        db_a, _gateway_a = self._mock_db("gateway-a", "server-a")
        db_b, _gateway_b = self._mock_db("gateway-b", "server-b")

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        pending_failed = anyio.Event()

        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=discovery):
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_a), db_a)
                with anyio.fail_after(5):
                    await websocket_a.registration_completed.wait()
                connection_a = real_session_manager.resolve_connection_id(stable_id)
                assert connection_a is not None

                async def pending_call() -> None:
                    with pytest.raises(ConnectionClosedError):
                        await real_session_manager.send_request(
                            connection_a,
                            JsonRpcRequest.model_validate({"jsonrpc": "2.0", "id": "tool-1", "method": "tools/call"}),
                            timeout_seconds=30,
                        )
                    pending_failed.set()

                task_group.start_soon(pending_call)
                with anyio.fail_after(5):
                    await websocket_a.request_sent.wait()

                websocket_b = TrackedRegistrationWebSocket()
                websocket_b.queue_client_frame({"type": "register", "server": {"name": "race-server"}})
                task_group.start_soon(websocket_endpoint, cast(WebSocket, websocket_b), db_b)
                with anyio.fail_after(5):
                    await websocket_b.registration_completed.wait()
                with anyio.fail_after(5):
                    await pending_failed.wait()

                assert websocket_a.closed_code is not None
                assert real_session_manager.resolve_connection_id(stable_id) == ConnectionId(websocket_b.sent_frames[0]["sessionId"])
                task_group.cancel_scope.cancel()


class TestStableIdPromotionOrdering:
    """A failed replacement registration must not strand the healthy stable mapping."""

    _STABLE_ID = "stable-shared-id"

    @pytest.fixture(autouse=True)
    def mock_admission(self):
        """Authenticate every connection through the admission seam."""
        context = SimpleNamespace(owner_email="owner@example.com", team_id=None)
        with patch("mcpgateway.routers.reverse_proxy._authenticate_reverse_proxy_websocket", new=AsyncMock(return_value=context)):
            yield

    @pytest.fixture
    def real_session_manager(self):
        """A fresh REAL session manager so stable-ID mappings behave exactly as in production."""
        return ReverseProxySessionManager()

    @pytest.fixture(autouse=True)
    def patch_session_manager_singleton(self, real_session_manager):
        """Route the endpoint's session-manager singleton to the real instance."""
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=real_session_manager)):
            yield

    @pytest.fixture(autouse=True)
    def catalog_service(self):
        """Both connections register the same stable catalog identity."""
        service = Mock(spec=ReverseProxyCatalogService)
        service.register.return_value = SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())
        with (
            patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service),
            patch("mcpgateway.routers.reverse_proxy.stable_proxy_id", return_value=self._STABLE_ID),
        ):
            yield service

    @pytest.fixture(autouse=True)
    def discovery_service(self):
        """The first (healthy) registration discovers cleanly; the replacement fails mid-flight."""
        service = Mock(spec=ReverseProxyDiscoveryService)
        service.discover_and_reconcile.side_effect = [Mock(name="discovery-ok"), RuntimeError("discovery exploded")]
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=service):
            yield service

    @pytest.mark.asyncio
    async def test_failed_replacement_preserves_healthy_stable_mapping(self, real_session_manager):
        """B's re-registration quiesces A's mapping, then fails discovery pre-commit: the catalog is untouched, so the restore puts the still-healthy A back."""
        healthy = TrackedRegistrationWebSocket()
        healthy.queue_client_frame({"type": "register", "server": {"name": "shared-server"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        stable_id = StableGatewayId(self._STABLE_ID)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(websocket_endpoint, cast(WebSocket, healthy), MagicMock())
            with anyio.fail_after(5):
                await healthy.registration_completed.wait()

            healthy_connection_id = real_session_manager.resolve_connection_id(stable_id)
            assert healthy_connection_id is not None

            failing = ScriptedReverseProxyWebSocket()
            failing.queue_client_frame({"type": "register", "server": {"name": "shared-server"}})
            await websocket_endpoint(cast(WebSocket, failing), MagicMock())

            assert failing.closed_code == 1008
            assert real_session_manager.resolve_connection_id(stable_id) == healthy_connection_id

            task_group.cancel_scope.cancel()


class TestLockedConnectionIO:
    """F4: one per-connection lock serializes every send and close on the socket."""

    @pytest.mark.asyncio
    async def test_send_text_is_serialized_through_the_connection_lock(self):
        """A concurrent send cannot interleave while the connection lock is held."""
        # First-Party
        from mcpgateway.routers.reverse_proxy import _LockedConnectionIO

        websocket = ScriptedReverseProxyWebSocket()
        io_lock = anyio.Lock()
        connection_io = _LockedConnectionIO(cast(WebSocket, websocket), io_lock)

        await io_lock.acquire()
        send_entered = asyncio.Event()

        async def send_concurrently() -> None:
            send_entered.set()
            await connection_io.send_text('{"type": "heartbeat"}')

        concurrent_send = asyncio.create_task(send_concurrently())
        await send_entered.wait()
        await asyncio.sleep(0)
        assert websocket.sent_frames == []

        io_lock.release()
        await asyncio.wait_for(concurrent_send, timeout=1)
        assert [frame["type"] for frame in websocket.sent_frames] == ["heartbeat"]

    @pytest.mark.asyncio
    async def test_close_is_serialized_through_the_connection_lock(self):
        """A concurrent close cannot fire while the connection lock is held."""
        # First-Party
        from mcpgateway.routers.reverse_proxy import _LockedConnectionIO

        websocket = ScriptedReverseProxyWebSocket()
        io_lock = anyio.Lock()
        connection_io = _LockedConnectionIO(cast(WebSocket, websocket), io_lock)

        await io_lock.acquire()
        close_entered = asyncio.Event()

        async def close_concurrently() -> None:
            close_entered.set()
            await connection_io.close(code=1008, reason="policy")

        concurrent_close = asyncio.create_task(close_concurrently())
        await close_entered.wait()
        await asyncio.sleep(0)
        assert websocket.closed_code is None

        io_lock.release()
        await asyncio.wait_for(concurrent_close, timeout=1)
        assert websocket.closed_code == 1008


class TestLazyServiceResolution:
    """F2: the shared service singletons resolve on first endpoint use, not at router import."""

    def test_router_module_does_not_bind_service_singletons_at_import_time(self):
        """The router module must not carry gateway_service/server_service module attributes."""
        # First-Party
        from mcpgateway.routers import reverse_proxy as rp

        assert not hasattr(rp, "gateway_service")
        assert not hasattr(rp, "server_service")


class TestReverseProxyFeatureGate:
    """The v1 router only mounts the reverse-proxy router when the feature flag is on."""

    @staticmethod
    def _sentinel_router(path: str) -> APIRouter:
        """Build a router exposing one unique sentinel route."""
        sentinel = APIRouter()
        sentinel.add_api_route(path, lambda: path)
        return sentinel

    def _build_v1_router(self, *, reverse_proxy_enabled: bool) -> APIRouter:
        """Assemble the real v1 router with the reverse-proxy flag flipped."""
        # First-Party
        from mcpgateway.api.v1 import build_v1_router

        feature_flags = SimpleNamespace(
            mcpgateway_a2a_enabled=False,
            observability_enabled=False,
            mcpgateway_reverse_proxy_enabled=reverse_proxy_enabled,
            toolops_enabled=False,
            mcpgateway_tool_cancellation_enabled=False,
            metrics_cleanup_enabled=False,
            metrics_rollup_enabled=False,
            email_auth_enabled=False,
            sso_enabled=False,
            llmchat_enabled=False,
            mcpgateway_admin_api_enabled=False,
        )
        inline_routers = {
            "protocol_router": self._sentinel_router("/sentinel-protocol"),
            "tool_router": self._sentinel_router("/sentinel-tool"),
            "resource_router": self._sentinel_router("/sentinel-resource"),
            "prompt_router": self._sentinel_router("/sentinel-prompt"),
            "gateway_router": self._sentinel_router("/sentinel-gateway"),
            "root_router": self._sentinel_router("/sentinel-root"),
            "server_router": self._sentinel_router("/sentinel-server"),
            "metrics_router": self._sentinel_router("/sentinel-metrics"),
            "tag_router": self._sentinel_router("/sentinel-tag"),
            "export_import_router": self._sentinel_router("/sentinel-export"),
            "a2a_router": self._sentinel_router("/sentinel-a2a"),
        }
        return build_v1_router(feature_flags, **inline_routers)

    def test_reverse_proxy_router_absent_when_feature_disabled(self):
        """Feature disabled -> no /reverse-proxy routes in the v1 app."""
        v1_router = self._build_v1_router(reverse_proxy_enabled=False)
        paths = [path for path, *_ in collect_routes(v1_router)]
        assert not any(path.startswith("/v1/reverse-proxy") for path in paths)

    def test_reverse_proxy_router_present_when_feature_enabled(self):
        """Feature enabled -> the WebSocket endpoint is mounted under /v1."""
        v1_router = self._build_v1_router(reverse_proxy_enabled=True)
        paths = [path for path, *_ in collect_routes(v1_router)]
        assert "/v1/reverse-proxy/ws" in paths


class TestWebSocketAuthentication:
    """Test WebSocket authentication functionality."""

    @staticmethod
    def _configure_authenticated_websocket(mock_websocket, payload):
        mock_websocket.headers = {"Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}
        state = {
            "_jwt_verified_payload": ("valid-token", payload),
            "team_id": "team-canonical",
            "token_teams": ["team-canonical"],
            "token_scopes": [],
        }
        mock_websocket.state = SimpleNamespace(**state)
        mock_websocket.scope = {"type": "websocket", "path": "/reverse-proxy/ws", "state": state}
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

    @pytest.mark.asyncio
    async def test_websocket_rejects_server_restricted_token_before_accept(self, mock_websocket):
        """A server-restricted token cannot open the unscoped reverse-proxy tunnel."""
        payload = {"jti": "server-restricted", "scopes": {"server_id": "server-1", "permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_403_FORBIDDEN
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 403

    @pytest.mark.asyncio
    async def test_websocket_rejects_ip_restricted_token_before_accept(self, mock_websocket):
        """A token restricted to another network is denied before WebSocket accept."""
        payload = {"jti": "ip-restricted", "scopes": {"ip_restrictions": ["10.0.0.0/24"], "permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_403_FORBIDDEN
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 403

    @pytest.mark.asyncio
    async def test_websocket_rejects_time_restricted_token_before_accept(self, mock_websocket):
        """A token outside its allowed time window is denied before WebSocket accept."""
        payload = {"jti": "time-restricted", "scopes": {"time_restrictions": {"weekdays_only": True}, "permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        from mcpgateway.middleware.token_scoping import token_scoping_middleware
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch.object(token_scoping_middleware, "_check_time_restrictions", return_value=False),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_403_FORBIDDEN
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 403

    @pytest.mark.asyncio
    async def test_websocket_rejects_usage_limited_token_before_accept(self, mock_websocket):
        """An exhausted token usage limit is denied with 429 semantics before accept."""
        payload = {"jti": "usage-restricted", "scopes": {"usage_limits": {"requests_per_hour": 1}, "permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        from mcpgateway.middleware.token_scoping import token_scoping_middleware
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch.object(token_scoping_middleware, "_check_usage_limits", return_value=(False, "Hourly request limit exceeded")),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_429_TOO_MANY_REQUESTS
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 429

    @pytest.mark.asyncio
    async def test_websocket_rejects_missing_authorization_header_before_accept(self, mock_websocket):
        """A WebSocket without an Authorization header is always rejected."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}  # No Authorization header
        mock_websocket.query_params = {}

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        # Should NOT accept the connection
        mock_websocket.accept.assert_not_called()
        denial = mock_websocket.send_denial_response
        denial.assert_awaited_once()
        assert denial.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        mock_websocket.close.assert_not_called()
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_authenticates_and_authorizes_both_layers_before_accept(self, mock_websocket):
        """Admission completes authentication and both permission layers before accept."""
        mock_websocket.headers = {"X-Session-ID": "test-session", "Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}
        mock_websocket.state = SimpleNamespace(team_id="team-canonical", token_teams=["team-canonical"], token_scopes=[])
        mock_websocket.scope = {"type": "websocket", "state": vars(mock_websocket.state)}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()
        events = []

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        async def authenticate(_credentials, request):
            events.append("authenticate")
            request.state._jwt_verified_payload = ("valid-token", {"scopes": {"permissions": []}})
            return SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)

        async def authorize(permission, **kwargs):
            events.append(permission)
            assert kwargs["team_id"] == "team-canonical"
            return True

        async def accept():
            events.append("accept")

        mock_websocket.accept.side_effect = accept
        checker = Mock()
        checker.has_permission = AsyncMock(side_effect=authorize)
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=authenticate)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            with pytest.raises(asyncio.CancelledError):
                await websocket_endpoint(mock_websocket, Mock())

        # Should accept the connection
        mock_websocket.accept.assert_called_once()
        assert events == ["authenticate", "gateways.create", "servers.create", "accept"]

    @pytest.mark.asyncio
    async def test_websocket_rejects_query_token_auth(self, mock_websocket):
        """Query-string bearer tokens must be rejected for reverse-proxy WebSocket auth."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}  # No Authorization header
        mock_websocket.query_params = {"token": "valid-token"}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_rejects_proxy_identity_header(self, mock_websocket):
        """A trusted-proxy identity header is not a WebSocket credential."""
        mock_websocket.headers = {"X-Session-ID": "test-session", "X-Authenticated-User": "proxy-user"}
        mock_websocket.query_params = {}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_rejects_api_token_with_revoked_team_membership_before_accept(self, mock_websocket):
        """B1: an RBAC-passing API token is denied when its team membership was revoked."""
        payload = {"jti": "membership-revoked", "sub": "canonical@example.com", "teams": ["team-revoked"], "token_use": "api", "scopes": {"permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        # First-Party
        from mcpgateway.middleware.token_scoping import token_scoping_middleware
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch.object(token_scoping_middleware, "check_team_membership", return_value=False) as membership,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_403_FORBIDDEN
        membership.assert_called_once_with(payload)
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 403

    @pytest.mark.asyncio
    async def test_websocket_rejects_api_token_with_wrong_team_before_accept(self, mock_websocket):
        """B1: an API token claiming a team the user is not a member of is denied before accept."""
        payload = {"jti": "wrong-team", "sub": "canonical@example.com", "teams": ["team-other"], "token_use": "api", "scopes": {"permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        # First-Party
        from mcpgateway.middleware.token_scoping import token_scoping_middleware
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as permission_checker,
            patch.object(token_scoping_middleware, "check_team_membership", return_value=False) as membership,
            patch("mcpgateway.routers.reverse_proxy.LOGGER.warning") as warning,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_403_FORBIDDEN
        membership.assert_called_once_with(payload)
        permission_checker.assert_not_called()
        assert warning.call_args.kwargs["extra"]["status_code"] == 403

    @pytest.mark.asyncio
    async def test_websocket_session_token_skips_membership_revalidation(self, mock_websocket):
        """B1: session tokens resolve membership from the DB upstream and skip JWT-team revalidation."""
        payload = {"jti": "session-token", "sub": "canonical@example.com", "teams": ["team-stale"], "token_use": "session", "scopes": {"permissions": ["*"]}}
        self._configure_authenticated_websocket(mock_websocket, payload)

        # First-Party
        from mcpgateway.middleware.token_scoping import token_scoping_middleware
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        user = SimpleNamespace(email="canonical@example.com", full_name="Test User", is_admin=False)
        checker = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
            patch.object(token_scoping_middleware, "check_team_membership", return_value=False) as membership,
        ):
            await websocket_endpoint(mock_websocket, Mock())

        membership.assert_not_called()
        mock_websocket.accept.assert_called_once()


# --------------------------------------------------------------------------- #
# HTTP Endpoint Tests                                                        #
# --------------------------------------------------------------------------- #


class TestHTTPEndpoints:
    """Test HTTP endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        # Third-Party
        from fastapi import FastAPI

        app = FastAPI()

        # Override the auth dependency
        def mock_require_auth():
            return "test-user"

        app.dependency_overrides[require_auth] = mock_require_auth
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture
    def mock_auth(self):
        """Mock authentication dependency (for reference)."""
        return "test-user"

    @staticmethod
    def typed_session(owner_email: str | None, websocket=None) -> ManagedSession:
        """Build one typed endpoint fixture with a fixed connection ID."""
        connected_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        return ManagedSession(
            connection_id=ConnectionId("test-session"),
            local_id=LocalSessionId("local"),
            websocket=websocket or Mock(),
            last_heartbeat=connected_at,
            owner_email=owner_email,
            connected_at=connected_at,
            last_activity=connected_at,
        )

    def test_list_sessions_empty(self, client, mock_auth):
        """Test listing sessions when empty."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.list_sessions.return_value = ()
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    @pytest.mark.parametrize(
        ("method", "path", "json_body", "permission"),
        [
            ("get", "/reverse-proxy/sessions", None, Permissions.GATEWAYS_READ),
            ("get", "/reverse-proxy/sse/test-session", None, Permissions.GATEWAYS_READ),
            ("delete", "/reverse-proxy/sessions/test-session", None, Permissions.GATEWAYS_DELETE),
            ("post", "/reverse-proxy/sessions/test-session/request", {"jsonrpc": "2.0", "method": "tools/list", "id": 1}, Permissions.TOOLS_EXECUTE),
        ],
    )
    def test_http_routes_require_method_specific_rbac(self, client, method, path, json_body, permission):
        """Ownership never substitutes for the method-specific Layer-2 permission."""
        checker = Mock(has_permission=AsyncMock(return_value=False))
        manager_factory = AsyncMock()
        with (
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", manager_factory),
        ):
            response = getattr(client, method)(path, json=json_body) if json_body is not None else getattr(client, method)(path)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        checker.has_permission.assert_awaited_once_with(permission, team_id=None)
        manager_factory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_http_permission_forwards_token_scopes_to_layer_two_checker(self):
        """Restricted API-token scopes remain independent from DB RBAC grants."""
        from mcpgateway.routers import reverse_proxy as rp

        request = Mock(spec=Request)
        request.scope = {"state": {"team_id": None, "token_teams": [], "token_scopes": [Permissions.GATEWAYS_READ]}}
        checker = Mock(has_permission=AsyncMock(return_value=False))

        with patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as checker_factory:
            with pytest.raises(HTTPException) as exc_info:
                await rp._require_http_permission(request, {"email": "owner@example.com"}, Permissions.TOOLS_EXECUTE)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert checker_factory.call_args.args[0]["token_scopes"] == [Permissions.GATEWAYS_READ]

    def test_list_sessions_uses_typed_metadata_and_owner_filter(self, client):
        """The typed manager is the only listing authority and preserves response fields."""
        typed_manager = ReverseProxySessionManager()
        first = asyncio.run(typed_manager.connect(Mock(), LocalSessionId("owned"), owner_email="test-user", now=datetime(2026, 8, 13, tzinfo=timezone.utc)))
        asyncio.run(typed_manager.connect(Mock(), LocalSessionId("other"), owner_email="other-user"))

        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        assert response.json() == {
            "sessions": [
                {
                    "session_id": str(first.connection_id),
                    "server_info": {},
                    "connected_at": "2026-08-13T00:00:00+00:00",
                    "last_activity": "2026-08-13T00:00:00+00:00",
                    "message_count": 0,
                    "bytes_transferred": 0,
                    "user": "test-user",
                }
            ],
            "total": 1,
        }

    def test_distributed_list_uses_redis_directory_on_wrong_worker(self, client, monkeypatch):
        """A worker with no local sockets lists owner-filtered Redis directory entries."""
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)
        entry = RelaySessionEntry(
            connection_id="remote-session",
            stable_id="stable-remote",
            owner=RelayOwner(worker_id="worker-a", connection_id="remote-session"),
            owner_email="test-user",
            connected_at="2026-08-13T00:00:00+00:00",
            last_activity="2026-08-13T00:00:00+00:00",
            message_count=2,
            bytes_transferred=10,
            server_info={"name": "remote"},
        )
        relay = MagicMock(list_session_entries=AsyncMock(return_value=(entry,)))
        with patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", new=AsyncMock(return_value=relay)):
            response = client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        assert response.json()["sessions"][0]["session_id"] == "remote-session"

    def test_distributed_post_and_delete_route_remote_connection(self, client, monkeypatch):
        """POST and DELETE resolve a remote connection instead of returning worker-local 404."""
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)
        entry = RelaySessionEntry(
            connection_id="remote-session",
            stable_id="stable-remote",
            owner=RelayOwner(worker_id="worker-a", connection_id="remote-session"),
            owner_email="test-user",
            connected_at="2026-08-13T00:00:00+00:00",
            last_activity="2026-08-13T00:00:00+00:00",
            message_count=0,
            bytes_transferred=0,
            server_info={},
        )
        manager = Mock(spec=ReverseProxySessionManager)
        manager.get_session.return_value = None
        relay = MagicMock(
            get_session_entry=AsyncMock(return_value=entry),
            send_request_by_connection_id_nowait=AsyncMock(),
            disconnect_session=AsyncMock(return_value=True),
        )
        with (
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=manager)),
            patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", new=AsyncMock(return_value=relay)),
        ):
            post_response = client.post("/reverse-proxy/sessions/remote-session/request", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
            delete_response = client.delete("/reverse-proxy/sessions/remote-session")

        assert post_response.status_code == 200
        assert delete_response.status_code == 200
        relay.send_request_by_connection_id_nowait.assert_awaited_once()
        relay.disconnect_session.assert_awaited_once_with(ConnectionId("remote-session"))

    def test_distributed_sse_uses_remote_session_directory(self, monkeypatch):
        """SSE ownership and connected metadata resolve on a worker without the socket."""
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)
        entry = RelaySessionEntry(
            connection_id="remote-session",
            stable_id="stable-remote",
            owner=RelayOwner(worker_id="worker-a", connection_id="remote-session"),
            owner_email="test-user",
            connected_at="2026-08-13T00:00:00+00:00",
            last_activity="2026-08-13T00:00:00+00:00",
            message_count=0,
            bytes_transferred=0,
            server_info={"name": "remote"},
        )
        manager = Mock(spec=ReverseProxySessionManager)
        manager.get_session.return_value = None
        relay = MagicMock(get_session_entry=AsyncMock(return_value=entry))

        async def read_connected_event() -> str:
            from mcpgateway.routers.reverse_proxy import sse_endpoint

            request = Mock(spec=Request)
            request.is_disconnected = AsyncMock(return_value=True)
            response = await sse_endpoint("remote-session", request, credentials="test-user")  # pragma: allowlist secret
            return await anext(response.body_iterator)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=manager)),
            patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", new=AsyncMock(return_value=relay)),
        ):
            connected = asyncio.run(read_connected_event())

        assert connected.startswith("event: connected\ndata: ")
        assert '"sessionId":"remote-session"' in connected
        assert '"name":"remote"' in connected

    def test_request_uses_typed_json_rpc_immediate_ack_and_timeout(self, client):
        """The HTTP request endpoint parses JSON-RPC and emits without response correlation."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        connected_at = datetime.now(tz=timezone.utc)
        typed_manager.get_session.return_value = ManagedSession(
            connection_id=ConnectionId("test-session"),
            local_id=LocalSessionId("local"),
            websocket=Mock(),
            owner_email="test-user",
            connected_at=connected_at,
            last_activity=connected_at,
            last_heartbeat=connected_at,
            message_count=0,
            bytes_transferred=0,
            server_info={},
        )
        typed_manager.send_request_nowait.return_value = None

        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.post("/reverse-proxy/sessions/test-session/request", json={"jsonrpc": "2.0", "method": "tools/list", "id": "http-1"})

        assert response.status_code == 200
        assert response.json() == {"status": "sent", "session_id": "test-session"}
        call_args = typed_manager.send_request_nowait.await_args
        assert call_args.args[0] == ConnectionId("test-session")
        assert call_args.args[1] == JsonRpcRequest(jsonrpc="2.0", method="tools/list", id="http-1")
        assert call_args.kwargs["timeout_seconds"] == float(settings.tool_timeout)

    def test_request_rejects_malformed_json_rpc_without_dispatch(self, client):
        """Malformed JSON-RPC is rejected at the HTTP boundary."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = Mock(owner_email="test-user")

        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.post("/reverse-proxy/sessions/test-session/request", json={"method": "tools/list"})

        assert response.status_code == 422
        typed_manager.send_request.assert_not_awaited()

    def test_list_sessions_uuid_sub_with_nested_email_sees_email_owned_session(self):
        """UUID-sub API-token payloads should match sessions owned by signed email."""
        # Third-Party
        from fastapi import FastAPI

        uuid_credentials = {"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "owner@test.com"}}
        app = FastAPI()
        app.dependency_overrides[require_auth] = lambda: uuid_credentials
        app.include_router(router)
        client = TestClient(app)

        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.list_sessions.return_value = (self.typed_session("owner@test.com"),)
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_disconnect_session_success(self, client, mock_auth, mock_websocket):
        """Test disconnecting an existing session."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.disconnect.return_value = ()
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.delete("/reverse-proxy/sessions/test-session")

        assert response.status_code == 200
        assert response.json() == {"status": "disconnected", "session_id": "test-session"}
        typed_manager.disconnect.assert_awaited_once_with(ConnectionId("test-session"))
        mock_websocket.close.assert_awaited_once()

    def test_disconnect_session_not_found(self, client, mock_auth):
        """Test disconnecting a non-existent session."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = None
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.delete("/reverse-proxy/sessions/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_disconnect_session_close_failure_still_clears_state(self, client, mock_auth, mock_websocket):
        """A raising close cannot prevent typed disconnect."""
        mock_websocket.close.side_effect = ConnectionError("socket already lost")
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.disconnect.return_value = ()
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.delete("/reverse-proxy/sessions/test-session")

        assert response.status_code == 200
        typed_manager.disconnect.assert_awaited_once_with(ConnectionId("test-session"))

    def test_disconnect_session_persistence_failure_still_removes_and_closes(self, client, mock_auth, mock_websocket):
        """Reachability persistence failure cannot strand socket close."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.disconnect.return_value = (ReverseProxyEviction(StableGatewayId("stable"), ConnectionId("test-session")),)

        from mcpgateway.services.gateway_service import gateway_service

        with (
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)),
            patch.object(gateway_service, "mark_reverse_proxy_gateways_unreachable", new=AsyncMock(side_effect=RuntimeError("db unavailable"))),
        ):
            response = client.delete("/reverse-proxy/sessions/test-session")

        assert response.status_code == 200
        mock_websocket.close.assert_called_once()

    def test_disconnect_session_release_failure_still_persists_and_closes(self, client, mock_auth, mock_websocket, monkeypatch):
        eviction = ReverseProxyEviction(StableGatewayId("stable"), ConnectionId("test-session"))
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.disconnect.return_value = (eviction,)
        relay = MagicMock(disconnect_session=AsyncMock(return_value=True))
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)),
            patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", new=AsyncMock(return_value=relay)),
        ):
            response = client.delete("/reverse-proxy/sessions/test-session")

        assert response.status_code == 200
        relay.disconnect_session.assert_awaited_once_with(ConnectionId("test-session"))

    @pytest.mark.asyncio
    async def test_disconnect_session_blocked_close_is_bounded(self, client, mock_auth, mock_websocket):
        """F1: a close stalled behind a blocked send cannot block cleanup; the endpoint returns within the bounded close timeout."""

        async def blocked_close(*args, **kwargs):
            await anyio.sleep(30)

        mock_websocket.close.side_effect = blocked_close
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.disconnect.return_value = ()
        with (
            patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)),
            patch("mcpgateway.routers.reverse_proxy._HTTP_DISCONNECT_CLOSE_TIMEOUT_SECONDS", 0.05),
        ):
            with anyio.fail_after(10):
                response = await anyio.to_thread.run_sync(client.delete, "/reverse-proxy/sessions/test-session")

        assert response.status_code == 200
        typed_manager.disconnect.assert_awaited_once_with(ConnectionId("test-session"))
        mock_websocket.close.assert_called_once()

    def test_send_request_to_session_not_found(self, client, mock_auth):
        """Test sending request to non-existent session."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = None
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.post("/reverse-proxy/sessions/nonexistent/request", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_send_request_to_session_websocket_error(self, client, mock_auth):
        """Test sending request when WebSocket fails."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user")
        typed_manager.send_request_nowait.side_effect = ConnectionError("WebSocket error")
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.post("/reverse-proxy/sessions/test-session/request", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})

        assert response.status_code == 500
        assert "Failed to send request" in response.json()["detail"]

    def test_sse_endpoint_success(self, mock_websocket):
        """Test SSE endpoint with existing session."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        typed_manager.get_session.return_value = replace(typed_manager.get_session.return_value, server_info={"name": "test-server"})
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            # This test does not use TestClient streaming; it validates the underlying
            # async generator behavior directly to avoid hanging on keepalive sleeps.
            from mcpgateway.routers.reverse_proxy import sse_endpoint

            dummy_request = Mock(spec=Request)
            dummy_request.is_disconnected = AsyncMock(side_effect=[False, True])

            async def _run():
                response = await sse_endpoint("test-session", dummy_request, credentials="test-user")  # pragma: allowlist secret
                agen = response.body_iterator
                first = await anext(agen)
                second = await anext(agen)
                with pytest.raises(StopAsyncIteration):
                    await anext(agen)
                return first, second

            with patch("mcpgateway.routers.reverse_proxy.asyncio.sleep", new=AsyncMock()):
                connected, keepalive = asyncio.run(_run())

            assert connected.startswith("event: connected\ndata: ")
            assert connected.endswith("\n\n")
            assert keepalive.startswith("event: keepalive\ndata: ")
            assert keepalive.endswith("\n\n")

    def test_sse_endpoint_handles_cancelled_error(self, mock_websocket):
        """SSE generator should re-raise CancelledError after yielding connected event."""
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = self.typed_session("test-user", mock_websocket)
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            from mcpgateway.routers.reverse_proxy import sse_endpoint

            dummy_request = Mock(spec=Request)
            dummy_request.is_disconnected = AsyncMock(return_value=False)

            async def _run():
                response = await sse_endpoint("test-session", dummy_request, credentials="test-user")  # pragma: allowlist secret
                agen = response.body_iterator
                first = await anext(agen)
                with pytest.raises(asyncio.CancelledError):
                    await anext(agen)
                return first

            with patch("mcpgateway.routers.reverse_proxy.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError())):
                connected = asyncio.run(_run())

            assert connected.startswith("event: connected\ndata: ")

    def test_sse_endpoint_not_found(self, client):
        """Test SSE endpoint with non-existent session."""
        # Don't mock the endpoint for this test since we want the real 404 behavior
        typed_manager = Mock(spec=ReverseProxySessionManager)
        typed_manager.get_session.return_value = None
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = client.get("/reverse-proxy/sse/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]


# --------------------------------------------------------------------------- #
# Helper function tests                                                       #
# --------------------------------------------------------------------------- #


class TestGetUserFromCredentials:
    """Test _get_user_from_credentials function."""

    def test_get_websocket_bearer_token_accepts_lowercase_scheme(self):
        """Reverse-proxy WebSocket token parser should accept lowercase bearer scheme."""
        # First-Party
        from mcpgateway.routers import reverse_proxy as rp

        websocket = Mock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {"authorization": "bearer lower-case-token"}

        assert rp._get_websocket_bearer_token(websocket) == "lower-case-token"

    def test_get_websocket_bearer_token_ignores_query_token(self):
        """Reverse-proxy WebSocket token parser should ignore query-string tokens."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = Mock(spec=WebSocket)
        websocket.query_params = {"token": "legacy-token"}
        websocket.headers = {}

        assert rp._get_websocket_bearer_token(websocket) is None

    @staticmethod
    def _authenticated_websocket(*, token_scopes: list[str] | None, team_id: str | None = "team-canonical"):
        websocket = Mock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer valid-token", "user-agent": "test-client"}
        websocket.client = Mock(host="127.0.0.1")
        token_teams = [team_id] if team_id is not None else None
        payload = {"scopes": {"permissions": token_scopes or []}}
        websocket.state = SimpleNamespace(_jwt_verified_payload=("valid-token", payload), team_id=team_id, token_teams=token_teams, token_use="api", token_scopes=token_scopes)
        websocket.scope = {"type": "websocket", "state": vars(websocket.state)}
        return websocket

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("token_scopes", "missing_permission"),
        [
            (["servers.create"], "gateways.create"),
            (["gateways.create"], "servers.create"),
        ],
    )
    async def test_authenticate_reverse_proxy_websocket_requires_each_token_scope(self, token_scopes, missing_permission):
        """Each catalog-creation permission is independently required at Layer 1."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=token_scopes)
        checker = Mock()
        checker.has_permission = AsyncMock(return_value=True)
        checker.has_any_permission = AsyncMock(return_value=True)
        user = SimpleNamespace(email="owner@example.com", full_name="Owner", is_admin=False)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await rp._authenticate_reverse_proxy_websocket(websocket)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        checker.has_permission.assert_not_awaited()
        checker.has_any_permission.assert_not_awaited()
        assert missing_permission not in token_scopes

    @pytest.mark.asyncio
    async def test_authenticate_reverse_proxy_websocket_uses_authenticated_request_scopes(self):
        """Authorization must consume scope state produced by the authentication request."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=None, team_id=None)
        websocket.scope["state"] = {}
        checker = Mock()
        checker.has_permission = AsyncMock(return_value=True)
        user = SimpleNamespace(email="owner@example.com", full_name="Owner", is_admin=True)

        async def authenticate(_credentials, request):
            request.state._jwt_verified_payload = ("valid-token", {"scopes": {"permissions": ["tools.read"]}})
            request.state.token_scopes = ["tools.read"]
            request.state.token_teams = None
            request.state.team_id = None
            request.state.token_use = "api"
            return user

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=authenticate)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await rp._authenticate_reverse_proxy_websocket(websocket)

        assert exc_info.value.status_code == 403
        checker.has_permission.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing_permission", ["gateways.create", "servers.create"])
    async def test_authenticate_reverse_proxy_websocket_requires_each_rbac_permission(self, missing_permission):
        """Each catalog-creation permission is independently required at Layer 2."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=["gateways.create", "servers.create"])
        checker = Mock()
        checker.has_permission = AsyncMock(side_effect=lambda permission, **_kwargs: permission != missing_permission)
        checker.has_any_permission = AsyncMock(return_value=True)
        user = SimpleNamespace(email="owner@example.com", full_name="Owner", is_admin=False)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await rp._authenticate_reverse_proxy_websocket(websocket)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        checker.has_any_permission.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_scopes", [None, []])
    async def test_authenticate_reverse_proxy_websocket_empty_scope_inherits_rbac(self, token_scopes):
        """Absent and empty token scopes leave the Layer 2 decision authoritative."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=token_scopes)
        checker = Mock()
        checker.has_permission = AsyncMock(return_value=True)
        checker.has_any_permission = AsyncMock(return_value=False)
        user = SimpleNamespace(email="owner@example.com", full_name="Owner", is_admin=False)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            context = await rp._authenticate_reverse_proxy_websocket(websocket)

        assert context.owner_email == "owner@example.com"
        assert checker.has_permission.await_args_list == [
            call("gateways.create", team_id="team-canonical"),
            call("servers.create", team_id="team-canonical"),
        ]

    @pytest.mark.asyncio
    async def test_authenticate_database_api_token_without_jwt_payload_inherits_rbac(self):
        """A header-authenticated database token has no JWT restrictions to evaluate."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=[])
        del websocket.scope["state"]["_jwt_verified_payload"]
        checker = Mock()
        checker.has_permission = AsyncMock(return_value=True)
        user = SimpleNamespace(email="owner@example.com", full_name="Owner", is_admin=False)

        async def authenticate(_credentials, request):
            request.state.auth_method = "api_token"
            return user

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=authenticate)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker),
        ):
            context = await rp._authenticate_reverse_proxy_websocket(websocket)

        assert context.owner_email == "owner@example.com"
        assert checker.has_permission.await_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("team_id", ["team-canonical", None])
    async def test_authenticate_reverse_proxy_websocket_returns_safe_canonical_context(self, team_id):
        """The returned context contains canonical owner/team data and no credentials."""
        from mcpgateway.routers import reverse_proxy as rp

        websocket = self._authenticated_websocket(token_scopes=["gateways.*", "servers.*"], team_id=team_id)
        checker = Mock()
        checker.has_permission = AsyncMock(return_value=True)
        checker.has_any_permission = AsyncMock(return_value=False)
        user = SimpleNamespace(email="canonical@example.com", sub="ignored@example.com", full_name="Owner", is_admin=False)

        with (
            patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(return_value=user)),
            patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker) as checker_factory,
        ):
            context = await rp._authenticate_reverse_proxy_websocket(websocket)

        assert context.owner_email == "canonical@example.com"
        assert context.team_id == team_id
        assert not hasattr(context, "token")
        assert not hasattr(context, "token_scopes")
        assert not hasattr(context, "jwt_payload")
        assert checker.has_permission.await_args_list == [
            call("gateways.create", team_id=team_id),
            call("servers.create", team_id=team_id),
        ]
        transient_context = checker_factory.call_args.args[0]
        assert transient_context["email"] == "canonical@example.com"
        assert transient_context["team_id"] == team_id
        assert transient_context["token_teams"] == ([team_id] if team_id is not None else None)

    def test_dict_with_sub(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"sub": "user@test.com", "is_admin": False})
        assert user == "user@test.com"
        assert is_admin is False

    def test_dict_with_email_fallback(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"email": "user@test.com"})
        assert user == "user@test.com"
        assert is_admin is False

    def test_dict_with_uuid_sub_prefers_nested_email(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "user@test.com"}})
        assert user == "user@test.com"
        assert is_admin is False

    def test_dict_with_uuid_sub_without_email_does_not_return_uuid(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"sub": "11111111-1111-1111-1111-111111111111"})
        assert user is None
        assert is_admin is False

    def test_dict_nested_admin(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"sub": "admin@test.com", "user": {"is_admin": True}})
        assert user == "admin@test.com"
        assert is_admin is True

    def test_dict_top_level_admin(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials({"sub": "admin@test.com", "is_admin": True})
        assert user == "admin@test.com"
        assert is_admin is True

    def test_string_credentials(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials("user@test.com")
        assert user == "user@test.com"
        assert is_admin is False

    def test_anonymous_credentials(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials("anonymous")
        assert user is None
        assert is_admin is False

    def test_none_credentials(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials(None)
        assert user is None
        assert is_admin is False

    def test_empty_string_credentials(self):
        from mcpgateway.routers.reverse_proxy import _get_user_from_credentials

        user, is_admin = _get_user_from_credentials("")
        assert user is None
        assert is_admin is False


class TestValidateSessionOwnership:
    """Test _validate_session_ownership function."""

    @staticmethod
    def session(owner_email: str | None) -> ManagedSession:
        """Build a typed ownership fixture."""
        return ManagedSession(connection_id=ConnectionId("test-id"), local_id=LocalSessionId("local"), websocket=Mock(), last_heartbeat=datetime.now(tz=timezone.utc), owner_email=owner_email)

    def test_no_session_user_allows_access(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = self.session(None)
        # Should not raise
        _validate_session_ownership(session, "any-user", "test")

    def test_admin_bypasses_ownership(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = self.session("owner@test.com")
        # Admin should not raise
        _validate_session_ownership(session, {"sub": "admin@test.com", "is_admin": True}, "test")

    def test_owner_match_allows_access(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = self.session("owner@test.com")
        _validate_session_ownership(session, {"sub": "owner@test.com"}, "test")

    def test_owner_match_allows_uuid_sub_with_nested_email_credentials(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = self.session("owner@test.com")
        credentials = {"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "owner@test.com"}}
        _validate_session_ownership(session, credentials, "test")

    def test_non_owner_denied(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership
        from fastapi import HTTPException

        session = self.session("owner@test.com")
        with pytest.raises(HTTPException) as exc_info:
            _validate_session_ownership(session, {"sub": "other@test.com"}, "disconnect")
        assert exc_info.value.status_code == 403

    def test_stale_admin_claim_does_not_bypass_canonical_request_identity(self):
        """A demoted session user cannot retain cross-owner access through JWT claims."""
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        request = Mock(spec=Request)
        session = self.session("owner@test.com")
        credentials = {"sub": "demoted@test.com", "is_admin": True}

        with (
            patch("mcpgateway.routers.reverse_proxy.get_request_identity", return_value=("demoted@test.com", False)) as identity,
            pytest.raises(HTTPException) as exc_info,
        ):
            _validate_session_ownership(session, credentials, "disconnect", request=request)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        identity.assert_called_once_with(request, credentials)


class TestWebSocketAuthEdgeCases:
    """Test WebSocket authentication edge cases."""

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_http_exception(self, mock_websocket):
        """JWT verification raises HTTPException."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer bad-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token"))):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_general_exception(self, mock_websocket):
        """Unexpected authentication errors are not misclassified as invalid tokens."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer bad-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=ValueError("Malformed token"))):
            with pytest.raises(ValueError, match="Malformed token"):
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_query_token_http_exception(self, mock_websocket):
        """Query token verification raises HTTPException."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "bad-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_query_token_general_exception(self, mock_websocket):
        """Query token verification raises generic exception."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "bad-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_proxy_auth_no_header(self, mock_websocket):
        """Proxy auth enabled but no proxy header → reject."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_disconnect_exception(self, mock_websocket):
        """WebSocketDisconnect during message loop."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        context = SimpleNamespace(owner_email="owner@example.com", team_id=None)
        with patch("mcpgateway.routers.reverse_proxy._authenticate_reverse_proxy_websocket", new=AsyncMock(return_value=context)):
            await websocket_endpoint(mock_websocket, Mock())

        # Should have accepted and then cleanly disconnected
        mock_websocket.accept.assert_called_once()


class TestListSessionsFiltering:
    """Test session filtering by user role."""

    @pytest.fixture
    def admin_client(self):
        from fastapi import FastAPI

        app = FastAPI()

        def mock_require_auth():
            return {"sub": "admin@test.com", "is_admin": True}

        app.dependency_overrides[require_auth] = mock_require_auth
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture
    def user_client(self):
        from fastapi import FastAPI

        app = FastAPI()

        def mock_require_auth():
            return {"sub": "user@test.com", "is_admin": False}

        app.dependency_overrides[require_auth] = mock_require_auth
        app.include_router(router)
        return TestClient(app)

    def test_admin_sees_all_sessions(self, admin_client):
        """Admin user sees all sessions."""
        typed_manager = ReverseProxySessionManager()
        asyncio.run(typed_manager.connect(Mock(), LocalSessionId("s1"), owner_email="user1@test.com"))
        asyncio.run(typed_manager.connect(Mock(), LocalSessionId("s2"), owner_email="user2@test.com"))
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = admin_client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_user_sees_own_and_anonymous(self, user_client):
        """Regular user sees own sessions + anonymous ones."""
        typed_manager = ReverseProxySessionManager()
        own = asyncio.run(typed_manager.connect(Mock(), LocalSessionId("s1"), owner_email="user@test.com"))
        asyncio.run(typed_manager.connect(Mock(), LocalSessionId("s2"), owner_email="other@test.com"))
        anonymous = asyncio.run(typed_manager.connect(Mock(), LocalSessionId("s3")))
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=typed_manager)):
            response = user_client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {session["session_id"] for session in data["sessions"]} == {str(own.connection_id), str(anonymous.connection_id)}


# ---------------------------------------------------------------------------
# Token missing subject claim tests
# ---------------------------------------------------------------------------


class TestWebSocketTokenMissingSubject:
    """Tests for token payloads missing sub/email claim."""

    @pytest.mark.asyncio
    async def test_bearer_token_missing_subject(self, mock_websocket):
        """Bearer token auth failure is rejected."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token"))):
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_query_token_missing_subject(self, mock_websocket):
        """Query token auth failure is rejected."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "valid-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
        get_current_user.assert_not_awaited()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
    @pytest.fixture(autouse=True)
    def allow_http_rbac(self):
        """Allow Layer-2 checks by default; deny-path tests override this seam."""
        checker = Mock(has_permission=AsyncMock(return_value=True))
        with patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker):
            yield checker
