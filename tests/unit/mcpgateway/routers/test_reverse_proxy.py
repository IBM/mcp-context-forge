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
from datetime import datetime
import math
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, call, MagicMock, Mock, patch

# Third-Party
import anyio
import orjson

# Third-Party
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.gateway_service import GatewayCatalogReconcileResult
from mcpgateway.routers.reverse_proxy import (
    manager,
    ReverseProxyManager,
    ReverseProxySession,
    router,
)
from mcpgateway.services.reverse_proxy_catalog import AuthenticatedRegistrationContext, ReverseProxyCatalogService
from mcpgateway.services.reverse_proxy_discovery import ReverseProxyDiscoveryService
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, LocalSessionId, ReverseProxySessionManager, StableGatewayId
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


@pytest.fixture
def reverse_proxy_manager():
    """Create a fresh ReverseProxyManager instance."""
    return ReverseProxyManager()


@pytest.fixture
def sample_session(mock_websocket):
    """Create a sample ReverseProxySession."""
    return ReverseProxySession("test-session", mock_websocket, "test-user")


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


# --------------------------------------------------------------------------- #
# ReverseProxySession Tests                                                  #
# --------------------------------------------------------------------------- #


class TestReverseProxySession:
    """Test ReverseProxySession class."""

    def test_init(self, mock_websocket):
        """Test session initialization."""
        session = ReverseProxySession("test-id", mock_websocket, "test-user")

        assert session.session_id == "test-id"
        assert session.websocket is mock_websocket
        assert session.user == "test-user"
        assert session.server_info == {}
        assert isinstance(session.connected_at, datetime)
        assert isinstance(session.last_activity, datetime)
        assert session.message_count == 0
        assert session.bytes_transferred == 0

    def test_init_with_dict_user(self, mock_websocket):
        """Test session initialization with dict user."""
        user_dict = {"sub": "user123", "name": "Test User"}
        session = ReverseProxySession("test-id", mock_websocket, user_dict)

        assert session.user == user_dict

    def test_init_with_none_user(self, mock_websocket):
        """Test session initialization with None user."""
        session = ReverseProxySession("test-id", mock_websocket, None)

        assert session.user is None

    @pytest.mark.asyncio
    async def test_send_message(self, sample_session):
        """Test sending a message."""
        message = {"type": "test", "data": "hello"}

        await sample_session.send_message(message)

        expected_data = orjson.dumps(message).decode()
        sample_session.websocket.send_text.assert_called_once_with(expected_data)
        assert sample_session.bytes_transferred == len(expected_data)

    @pytest.mark.asyncio
    async def test_send_message_updates_activity(self, sample_session):
        """Test that sending a message updates last activity."""
        original_activity = sample_session.last_activity
        await asyncio.sleep(0.001)  # Small delay

        await sample_session.send_message({"test": "data"})

        assert sample_session.last_activity > original_activity

    @pytest.mark.asyncio
    async def test_receive_message(self, sample_session):
        """Test receiving a message."""
        test_data = {"type": "test", "content": "hello"}
        sample_session.websocket.receive_text.return_value = orjson.dumps(test_data).decode()

        result = await sample_session.receive_message()

        assert result == test_data
        assert sample_session.message_count == 1
        assert sample_session.bytes_transferred == len(orjson.dumps(test_data).decode())

    @pytest.mark.asyncio
    async def test_receive_message_updates_activity(self, sample_session):
        """Test that receiving a message updates last activity."""
        sample_session.websocket.receive_text.return_value = '{"test": "data"}'
        original_activity = sample_session.last_activity
        await asyncio.sleep(0.001)  # Small delay

        await sample_session.receive_message()

        assert sample_session.last_activity > original_activity

    @pytest.mark.asyncio
    async def test_receive_message_invalid_json(self, sample_session):
        """Test receiving invalid JSON."""
        sample_session.websocket.receive_text.return_value = "invalid json"

        with pytest.raises(orjson.JSONDecodeError):
            await sample_session.receive_message()


# --------------------------------------------------------------------------- #
# ReverseProxyManager Tests                                                  #
# --------------------------------------------------------------------------- #


class TestReverseProxyManager:
    """Test ReverseProxyManager class."""

    def test_init(self, reverse_proxy_manager):
        """Test manager initialization."""
        assert reverse_proxy_manager.sessions == {}
        assert reverse_proxy_manager._lock is not None

    @pytest.mark.asyncio
    async def test_add_session(self, reverse_proxy_manager, sample_session):
        """Test adding a session."""
        await reverse_proxy_manager.add_session(sample_session)

        assert sample_session.session_id in reverse_proxy_manager.sessions
        assert reverse_proxy_manager.sessions[sample_session.session_id] is sample_session

    @pytest.mark.asyncio
    async def test_remove_session(self, reverse_proxy_manager, sample_session):
        """Test removing a session."""
        await reverse_proxy_manager.add_session(sample_session)
        await reverse_proxy_manager.remove_session(sample_session.session_id)

        assert sample_session.session_id not in reverse_proxy_manager.sessions

    @pytest.mark.asyncio
    async def test_remove_nonexistent_session(self, reverse_proxy_manager):
        """Test removing a session that doesn't exist."""
        # Should not raise an exception
        await reverse_proxy_manager.remove_session("nonexistent")

        assert len(reverse_proxy_manager.sessions) == 0

    def test_get_session(self, reverse_proxy_manager, sample_session):
        """Test getting a session."""
        reverse_proxy_manager.sessions[sample_session.session_id] = sample_session

        result = reverse_proxy_manager.get_session(sample_session.session_id)
        assert result is sample_session

    def test_get_nonexistent_session(self, reverse_proxy_manager):
        """Test getting a session that doesn't exist."""
        result = reverse_proxy_manager.get_session("nonexistent")
        assert result is None

    def test_list_sessions_empty(self, reverse_proxy_manager):
        """Test listing sessions when empty."""
        result = reverse_proxy_manager.list_sessions()

        assert result == []
        assert isinstance(result, list)

    def test_list_sessions_with_string_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with string user."""
        session = ReverseProxySession("test-id", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        session.message_count = 5
        session.bytes_transferred = 1024
        reverse_proxy_manager.sessions["test-id"] = session

        result = reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        session_info = result[0]
        assert session_info["session_id"] == "test-id"
        assert session_info["server_info"] == {"name": "test-server"}
        assert session_info["message_count"] == 5
        assert session_info["bytes_transferred"] == 1024
        assert session_info["user"] == "test-user"
        assert "connected_at" in session_info
        assert "last_activity" in session_info

    def test_list_sessions_with_dict_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with dict user."""
        user_dict = {"sub": "user123", "name": "Test User"}
        session = ReverseProxySession("test-id", mock_websocket, user_dict)
        reverse_proxy_manager.sessions["test-id"] = session

        result = reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] == "user123"

    def test_list_sessions_with_uuid_dict_user_uses_signed_email(self, reverse_proxy_manager, mock_websocket):
        """Dict-shaped session users should expose the signed email, not UUID subject."""
        user_dict = {"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "owner@test.com"}}
        session = ReverseProxySession("test-id", mock_websocket, user_dict)
        reverse_proxy_manager.sessions["test-id"] = session

        result = reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] == "owner@test.com"

    def test_list_sessions_with_none_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with None user."""
        session = ReverseProxySession("test-id", mock_websocket, None)
        reverse_proxy_manager.sessions["test-id"] = session

        result = reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] is None

    def test_list_sessions_with_invalid_dict_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with dict user without 'sub' key."""
        user_dict = {"name": "Test User"}  # No 'sub' key
        session = ReverseProxySession("test-id", mock_websocket, user_dict)
        reverse_proxy_manager.sessions["test-id"] = session

        result = reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] is None


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
        fake.connect.return_value = ManagedSession(connection_id=self._CONNECTION_ID, local_id=LocalSessionId("local-test-id"), websocket=mock_websocket)
        return fake

    @pytest.fixture(autouse=True)
    def patch_session_manager(self, session_manager):
        """Route the endpoint's session-manager singleton to the scripted fake."""
        with patch("mcpgateway.routers.reverse_proxy.get_reverse_proxy_session_manager", new=AsyncMock(return_value=session_manager)):
            yield

    @pytest.fixture(autouse=True)
    def catalog_service(self):
        """Mock catalog registration at the router import site."""
        service = Mock(spec=ReverseProxyCatalogService)
        service.register.return_value = SimpleNamespace(stable_id=self._STABLE_ID, gateway=Mock(), server=Mock())
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service):
            yield service

    @pytest.fixture(autouse=True)
    def discovery_service(self):
        """Mock MCP discovery at the router import site."""
        service = Mock(spec=ReverseProxyDiscoveryService)
        service.discover_and_reconcile.return_value = Mock()
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyDiscoveryService", return_value=service):
            yield service

    @pytest.fixture(autouse=True)
    def clear_legacy_manager(self):
        """Keep the legacy observability mirror empty around each test."""
        manager.sessions.clear()
        yield
        manager.sessions.clear()

    @staticmethod
    def _sent_frames(mock_websocket) -> list[dict]:
        """Decode every frame the endpoint sent, in send order."""
        return [orjson.loads(call_args.args[0]) for call_args in mock_websocket.send_text.call_args_list]

    @pytest.mark.asyncio
    async def test_websocket_accept(self, mock_websocket, session_manager):
        """Accept follows admission, and disconnect cleans up both managers."""
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_called_once()
        session_manager.connect.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)
        assert manager.sessions == {}

    @pytest.mark.asyncio
    async def test_websocket_mirrors_legacy_manager_metadata(self, mock_websocket, session_manager):
        """D12: the legacy manager mirrors connection metadata for the HTTP admin endpoints."""
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch.object(manager, "add_session", wraps=manager.add_session) as add_spy, patch.object(manager, "remove_session", wraps=manager.remove_session) as remove_spy:
            await websocket_endpoint(mock_websocket, Mock())

        mirrored = add_spy.call_args.args[0]
        assert mirrored.session_id == str(self._CONNECTION_ID)
        assert mirrored.user == "test-user@example.com"
        remove_spy.assert_called_once_with(str(self._CONNECTION_ID))
        assert manager.sessions == {}

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
    async def test_websocket_register_message(self, session_manager, catalog_service, discovery_service):
        """Register drives ack(processing) -> catalog -> stable-id attach -> discovery -> complete(success)."""
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server", "description": "Test server", "protocol": "mcp"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket), Mock())

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

        session_manager.attach_stable_id.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)

        discovery_service.discover_and_reconcile.assert_awaited_once()
        discovery_call = discovery_service.discover_and_reconcile.await_args
        assert discovery_call.args[1] is session_manager
        assert discovery_call.args[2] == self._CONNECTION_ID
        assert discovery_call.args[3] is not None  # db_gateway row
        assert discovery_call.args[4] is not None  # db_server row
        assert discovery_call.kwargs["timeout_seconds"] == float(settings.tool_timeout)

        assert websocket.closed_code is None

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
        session_manager.attach_stable_id.assert_not_awaited()
        discovery_service.discover_and_reconcile.assert_not_awaited()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_register_discovery_failure_closes_connection(self, session_manager, catalog_service, discovery_service):
        """Discovery failure -> register_complete(error) then close 1008 after catalog persisted."""
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
        session_manager.attach_stable_id.assert_awaited_once_with(StableGatewayId(self._STABLE_ID), self._CONNECTION_ID)
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

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

        # anyio checkpoints let the first registration complete before the pump
        # takes the buffered duplicate; the duplicate is still rejected and closed.
        frames = websocket.sent_frames
        assert [frame["type"] for frame in frames] == ["register_ack", "register_complete", "error"]
        assert "already registered" in frames[2]["message"]
        assert websocket.closed_code == 1008
        catalog_service.register.assert_awaited_once()
        discovery_service.discover_and_reconcile.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_unregister_message(self, mock_websocket, session_manager):
        """Unregister ends the connection cleanly without server frames or close."""
        unregister_msg = {"type": "unregister"}
        mock_websocket.receive_text.return_value = orjson.dumps(unregister_msg).decode()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_called_once()
        mock_websocket.send_text.assert_not_called()
        mock_websocket.close.assert_not_called()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)
        assert manager.sessions == {}

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
    async def test_websocket_unexpected_error_disconnects_both_managers(self, mock_websocket, session_manager):
        """An unexpected loop error propagates but still disconnects both managers."""
        mock_websocket.receive_text.side_effect = [RuntimeError("boom"), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with pytest.raises(RuntimeError, match="boom"):
            await websocket_endpoint(mock_websocket, Mock())

        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)
        assert manager.sessions == {}


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
        with patch("mcpgateway.routers.reverse_proxy.ReverseProxyCatalogService", return_value=service):
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

    @pytest.fixture(autouse=True)
    def clear_legacy_manager(self):
        """Keep the legacy observability mirror empty around each test."""
        manager.sessions.clear()
        yield
        manager.sessions.clear()

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
        assert manager.sessions == {}


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
        mock_websocket.close.assert_awaited_once()
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
        mock_websocket.close.assert_awaited_once()
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
        mock_websocket.close.assert_awaited_once()
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
        mock_websocket.close.assert_awaited_once()
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
        # Should close with policy violation
        mock_websocket.close.assert_called_once()
        assert mock_websocket.close.call_args[1]["code"] == 1008  # WS_1008_POLICY_VIOLATION
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
        mock_websocket.close.assert_called_once()
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
        mock_websocket.close.assert_called_once()
        get_current_user.assert_not_awaited()


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

    def test_list_sessions_empty(self, client, mock_auth):
        """Test listing sessions when empty."""
        # Clear any existing sessions
        manager.sessions.clear()

        response = client.get("/reverse-proxy/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    def test_list_sessions_with_data(self, client, mock_auth, mock_websocket):
        """Test listing sessions with data."""
        # Add a test session
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        manager.sessions["test-session"] = session

        try:
            response = client.get("/reverse-proxy/sessions")

            assert response.status_code == 200
            data = response.json()
            assert len(data["sessions"]) == 1
            assert data["total"] == 1
            assert data["sessions"][0]["session_id"] == "test-session"
        finally:
            # Clean up
            manager.sessions.clear()

    def test_list_sessions_uuid_sub_with_nested_email_sees_email_owned_session(self, mock_websocket):
        """UUID-sub API-token payloads should match sessions owned by signed email."""
        # Third-Party
        from fastapi import FastAPI

        uuid_credentials = {"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "owner@test.com"}}
        app = FastAPI()
        app.dependency_overrides[require_auth] = lambda: uuid_credentials
        app.include_router(router)
        client = TestClient(app)

        session = ReverseProxySession("test-session", mock_websocket, "owner@test.com")
        session.server_info = {"name": "test-server"}
        manager.sessions["test-session"] = session

        try:
            response = client.get("/reverse-proxy/sessions")

            assert response.status_code == 200
            data = response.json()
            assert len(data["sessions"]) == 1
            assert data["total"] == 1
            assert data["sessions"][0]["session_id"] == "test-session"
        finally:
            manager.sessions.clear()

    def test_disconnect_session_success(self, client, mock_auth, mock_websocket):
        """Test disconnecting an existing session."""
        # Add a test session
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        manager.sessions["test-session"] = session

        try:
            response = client.delete("/reverse-proxy/sessions/test-session")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "disconnected"
            assert data["session_id"] == "test-session"

            # Session should be removed
            assert "test-session" not in manager.sessions
        finally:
            # Clean up
            manager.sessions.clear()

    def test_disconnect_session_not_found(self, client, mock_auth):
        """Test disconnecting a non-existent session."""
        response = client.delete("/reverse-proxy/sessions/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_send_request_to_session_success(self, client, mock_auth, mock_websocket):
        """Test sending request to existing session."""
        # Add a test session
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        manager.sessions["test-session"] = session

        try:
            mcp_request = {"method": "tools/list", "id": 1}
            response = client.post("/reverse-proxy/sessions/test-session/request", json=mcp_request)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "sent"
            assert data["session_id"] == "test-session"

            # Verify message was sent to WebSocket
            mock_websocket.send_text.assert_called_once()
        finally:
            # Clean up
            manager.sessions.clear()

    def test_send_request_to_session_not_found(self, client, mock_auth):
        """Test sending request to non-existent session."""
        mcp_request = {"method": "tools/list", "id": 1}
        response = client.post("/reverse-proxy/sessions/nonexistent/request", json=mcp_request)

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_send_request_to_session_websocket_error(self, client, mock_auth, mock_websocket):
        """Test sending request when WebSocket fails."""
        # Add a test session with failing WebSocket
        mock_websocket.send_text.side_effect = Exception("WebSocket error")
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        manager.sessions["test-session"] = session

        try:
            mcp_request = {"method": "tools/list", "id": 1}
            response = client.post("/reverse-proxy/sessions/test-session/request", json=mcp_request)

            assert response.status_code == 500
            data = response.json()
            assert "Failed to send request" in data["detail"]
        finally:
            # Clean up
            manager.sessions.clear()

    def test_sse_endpoint_success(self, mock_websocket):
        """Test SSE endpoint with existing session."""
        # Add a test session
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        manager.sessions["test-session"] = session

        try:
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

            assert connected["event"] == "connected"
            assert keepalive["event"] == "keepalive"
        finally:
            # Clean up
            manager.sessions.clear()

    def test_sse_endpoint_handles_cancelled_error(self, mock_websocket):
        """SSE generator should re-raise CancelledError after yielding connected event."""
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        manager.sessions["test-session"] = session

        try:
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

            assert connected["event"] == "connected"
        finally:
            manager.sessions.clear()

    def test_sse_endpoint_not_found(self, client):
        """Test SSE endpoint with non-existent session."""
        # Don't mock the endpoint for this test since we want the real 404 behavior
        response = client.get("/reverse-proxy/sse/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]


# --------------------------------------------------------------------------- #
# Integration Tests                                                          #
# --------------------------------------------------------------------------- #


class TestIntegration:
    """Integration tests for reverse proxy functionality."""

    @pytest.mark.asyncio
    async def test_session_lifecycle(self, reverse_proxy_manager, mock_websocket):
        """Test complete session lifecycle."""
        # Create session
        session = ReverseProxySession("lifecycle-test", mock_websocket, "test-user")

        # Add to manager
        await reverse_proxy_manager.add_session(session)
        assert reverse_proxy_manager.get_session("lifecycle-test") is session

        # Update session info
        session.server_info = {"name": "test-server", "version": "1.0"}

        # Send and receive messages
        await session.send_message({"type": "test", "data": "hello"})
        mock_websocket.receive_text.return_value = '{"type": "response", "id": 1}'
        received = await session.receive_message()

        assert received["type"] == "response"
        assert session.message_count == 1
        assert session.bytes_transferred > 0

        # List sessions
        sessions = reverse_proxy_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "lifecycle-test"

        # Remove session
        await reverse_proxy_manager.remove_session("lifecycle-test")
        assert reverse_proxy_manager.get_session("lifecycle-test") is None

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self, reverse_proxy_manager):
        """Test handling multiple concurrent sessions."""
        sessions = []

        # Create multiple sessions
        for i in range(5):
            ws = Mock(spec=WebSocket)
            ws.send_text = AsyncMock()
            session = ReverseProxySession(f"session-{i}", ws, f"user-{i}")
            sessions.append(session)
            await reverse_proxy_manager.add_session(session)

        # Verify all sessions are tracked
        assert len(reverse_proxy_manager.sessions) == 5

        # List sessions
        session_list = reverse_proxy_manager.list_sessions()
        assert len(session_list) == 5

        # Remove all sessions
        for session in sessions:
            await reverse_proxy_manager.remove_session(session.session_id)

        assert len(reverse_proxy_manager.sessions) == 0


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
    def _authenticated_websocket(*, token_scopes, team_id="team-canonical"):
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

    def test_no_session_user_allows_access(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = ReverseProxySession("test-id", mock_websocket, None)
        # Should not raise
        _validate_session_ownership(session, "any-user", "test")

    def test_admin_bypasses_ownership(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        # Admin should not raise
        _validate_session_ownership(session, {"sub": "admin@test.com", "is_admin": True}, "test")

    def test_owner_match_allows_access(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        _validate_session_ownership(session, {"sub": "owner@test.com"}, "test")

    def test_owner_match_allows_uuid_sub_with_nested_email_credentials(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        credentials = {"sub": "11111111-1111-1111-1111-111111111111", "user": {"email": "owner@test.com"}}
        _validate_session_ownership(session, credentials, "test")

    def test_owner_match_dict_user(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership

        session = ReverseProxySession("test-id", mock_websocket, {"sub": "owner@test.com"})
        _validate_session_ownership(session, {"sub": "owner@test.com"}, "test")

    def test_non_owner_denied(self, mock_websocket):
        from mcpgateway.routers.reverse_proxy import _validate_session_ownership
        from fastapi import HTTPException

        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        with pytest.raises(HTTPException) as exc_info:
            _validate_session_ownership(session, {"sub": "other@test.com"}, "disconnect")
        assert exc_info.value.status_code == 403


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
        mock_websocket.close.assert_called_once()

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
        mock_websocket.close.assert_called_once()
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
        mock_websocket.close.assert_called_once()
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
        mock_websocket.close.assert_called_once()
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

    def test_admin_sees_all_sessions(self, admin_client, mock_websocket):
        """Admin user sees all sessions."""
        manager.sessions.clear()
        s1 = ReverseProxySession("s1", mock_websocket, "user1@test.com")
        s2 = ReverseProxySession("s2", mock_websocket, "user2@test.com")
        manager.sessions["s1"] = s1
        manager.sessions["s2"] = s2

        try:
            response = admin_client.get("/reverse-proxy/sessions")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
        finally:
            manager.sessions.clear()

    def test_user_sees_own_and_anonymous(self, user_client, mock_websocket):
        """Regular user sees own sessions + anonymous ones."""
        manager.sessions.clear()
        s1 = ReverseProxySession("s1", mock_websocket, "user@test.com")
        s2 = ReverseProxySession("s2", mock_websocket, "other@test.com")
        s3 = ReverseProxySession("s3", mock_websocket, None)  # anonymous
        manager.sessions["s1"] = s1
        manager.sessions["s2"] = s2
        manager.sessions["s3"] = s3

        try:
            response = user_client.get("/reverse-proxy/sessions")
            assert response.status_code == 200
            data = response.json()
            # Should see own (s1) + anonymous (s3), not other's (s2)
            assert data["total"] == 2
            session_ids = [s["session_id"] for s in data["sessions"]]
            assert "s1" in session_ids
            assert "s3" in session_ids
            assert "s2" not in session_ids
        finally:
            manager.sessions.clear()


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
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_token_missing_subject(self, mock_websocket):
        """Query token auth failure is rejected."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "valid-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()
        get_current_user.assert_not_awaited()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
