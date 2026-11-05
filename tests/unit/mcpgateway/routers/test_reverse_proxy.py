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
from unittest.mock import AsyncMock, call, Mock, patch

# Third-Party
import anyio
import anyio.to_thread
import orjson

# Third-Party
from fastapi import APIRouter, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest
# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Permissions
from mcpgateway.routers.reverse_proxy import router
from mcpgateway.services.reverse_proxy_protocol import JsonRpcRequest
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, LocalSessionId, ReverseProxySessionManager
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


# --------------------------------------------------------------------------- #
# WebSocket Endpoint Tests                                                   #
# --------------------------------------------------------------------------- #


class TestWebSocketEndpoint:
    """Test the typed WebSocket lifecycle against the session manager seam.

    Admission is mocked at the ``_authenticate_reverse_proxy_websocket`` seam;
    deny-path coverage lives in TestWebSocketAuthentication and friends.
    """

    _CONNECTION_ID = ConnectionId("test-connection-id")

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
        fake.disconnect.return_value = ()
        return fake

    @pytest.fixture(autouse=True)
    def patch_session_manager(self, session_manager):
        """Route the endpoint's session-manager singleton to the scripted fake."""
        with patch("mcpgateway.services.reverse_proxy_lifecycle.get_reverse_proxy_session_manager", new=AsyncMock(return_value=session_manager)):
            yield

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

        await websocket_endpoint(mock_websocket)

        mock_websocket.accept.assert_called_once()
        session_manager.connect.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_generates_connection_id_server_side(self, mock_websocket, session_manager):
        """The client-supplied X-Session-ID never becomes connection identity."""
        mock_websocket.headers = {"X-Session-ID": "client-controlled"}
        register_msg = {"type": "register", "server": {"name": "test-server"}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(register_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

        ack = self._sent_frames(mock_websocket)[0]
        assert ack["sessionId"] == str(self._CONNECTION_ID)
        assert ack["sessionId"] != "client-controlled"

    @pytest.mark.asyncio
    async def test_websocket_register_message(self, session_manager):
        """Register drives ack(processing) -> record server info -> complete(success)."""
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame({"type": "register", "server": {"name": "test-server", "description": "Test server", "protocol": "mcp"}})

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket))

        frames = websocket.sent_frames
        assert [frame["type"] for frame in frames] == ["register_ack", "register_complete"]
        assert frames[0]["status"] == "processing"
        assert frames[0]["sessionId"] == str(self._CONNECTION_ID)
        assert frames[1]["status"] == "success"
        assert frames[1]["sessionId"] == str(self._CONNECTION_ID)

        session_manager.record_server_info.assert_awaited_once()
        info_call = session_manager.record_server_info.await_args
        assert info_call.args[0] == self._CONNECTION_ID
        assert info_call.args[1]["name"] == "test-server"
        assert websocket.closed_code is None

    @pytest.mark.asyncio
    async def test_websocket_heartbeat_message(self, mock_websocket, session_manager):
        """Heartbeat is acknowledged with the connection-scoped id and a timestamp."""
        heartbeat_msg = {"type": "heartbeat"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(heartbeat_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

        frames = self._sent_frames(mock_websocket)
        assert len(frames) == 1
        assert frames[0]["type"] == "heartbeat"
        assert frames[0]["sessionId"] == str(self._CONNECTION_ID)
        assert "timestamp" in frames[0]
        session_manager.record_heartbeat.assert_awaited_once()
        assert session_manager.record_heartbeat.await_args.args[0] == self._CONNECTION_ID
        session_manager.record_server_info.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_websocket_response_resolves_pending_request(self, mock_websocket, session_manager):
        """A response frame resolves the pending request through the connection-scoped id."""
        response_msg = {"type": "response", "payload": {"jsonrpc": "2.0", "id": "req-1", "result": {"ok": True}}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(response_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

        session_manager.resolve_response.assert_called_once()
        resolve_call = session_manager.resolve_response.call_args
        assert resolve_call.args[0] == self._CONNECTION_ID
        assert resolve_call.args[1].payload.id == "req-1"
        mock_websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_duplicate_register_closes_connection(self, session_manager):
        """A second register on one connection is an error and closes 1008."""
        register_msg = {"type": "register", "server": {"name": "test-server"}}
        websocket = ScriptedReverseProxyWebSocket()
        websocket.queue_client_frame(register_msg)
        websocket.queue_client_frame(register_msg)

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(cast(WebSocket, websocket))

        frames = websocket.sent_frames
        frame_types = [frame["type"] for frame in frames]
        assert frame_types[0] == "register_ack"
        assert frame_types.count("error") == 1
        assert "already registered" in frames[frame_types.index("error")]["message"]
        assert websocket.closed_code == 1008
        session_manager.record_server_info.assert_awaited_once()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_unregister_message(self, mock_websocket, session_manager):
        """Unregister ends the connection cleanly without server frames or close."""
        unregister_msg = {"type": "unregister"}
        mock_websocket.receive_text.return_value = orjson.dumps(unregister_msg).decode()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

        mock_websocket.accept.assert_called_once()
        mock_websocket.send_text.assert_not_called()
        mock_websocket.close.assert_not_called()
        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)

    @pytest.mark.asyncio
    async def test_websocket_invalid_json(self, mock_websocket, session_manager):
        """Malformed frames get a typed error frame; the connection stays up."""
        mock_websocket.receive_text.side_effect = ["invalid json", WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

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
        from mcpgateway.services.reverse_proxy_lifecycle import _MAX_WEBSOCKET_FRAME_BYTES

        oversized_frame = "x" * (_MAX_WEBSOCKET_FRAME_BYTES + 1)
        mock_websocket.receive_text.return_value = oversized_frame

        await rp.websocket_endpoint(mock_websocket)

        session_manager.record_received.assert_not_called()
        mock_websocket.send_text.assert_not_called()
        mock_websocket.close.assert_awaited_once_with(code=1009, reason="message too large")

    @pytest.mark.asyncio
    async def test_websocket_inbound_accounting_uses_unicode_character_count(self, mock_websocket, session_manager):
        """Router receive accounting passes text length rather than encoded byte length."""
        frame = '{"type":"notification","payload":{"jsonrpc":"2.0","method":"通知/更新"}}'
        mock_websocket.receive_text.side_effect = [frame, WebSocketDisconnect()]

        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

        session_manager.record_received.assert_called_once_with(self._CONNECTION_ID, character_count=len(frame))
        assert len(frame) < len(frame.encode())

    @pytest.mark.asyncio
    async def test_websocket_unknown_message_type(self, mock_websocket, session_manager):
        """Frames outside the client contract are rejected with a typed error frame."""
        unknown_msg = {"type": "unknown", "data": "test"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(unknown_msg).decode(), WebSocketDisconnect()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        await websocket_endpoint(mock_websocket)

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

        await websocket_endpoint(mock_websocket)

        session_manager.connect.assert_awaited_once()
        mock_websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_unexpected_error_disconnects_typed_manager(self, mock_websocket, session_manager):
        """An unexpected loop error propagates but still disconnects typed state."""
        mock_websocket.receive_text.side_effect = [RuntimeError("boom"), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with pytest.raises(RuntimeError, match="boom"):
            await websocket_endpoint(mock_websocket)

        session_manager.disconnect.assert_awaited_once_with(self._CONNECTION_ID)


class TestLockedConnectionIO:
    """F4: one per-connection lock serializes every send and close on the socket."""

    @pytest.mark.asyncio
    async def test_send_text_is_serialized_through_the_connection_lock(self):
        """A concurrent send cannot interleave while the connection lock is held."""
        # First-Party
        from mcpgateway.services.reverse_proxy_lifecycle import _LockedConnectionIO

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
        from mcpgateway.services.reverse_proxy_lifecycle import _LockedConnectionIO

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

    def test_lifecycle_module_does_not_bind_service_singletons_at_import_time(self):
        """The lifecycle module must not carry gateway_service/server_service module attributes."""
        # First-Party
        from mcpgateway.services import reverse_proxy_lifecycle as lifecycle

        assert not hasattr(lifecycle, "gateway_service")
        assert not hasattr(lifecycle, "server_service")


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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
                await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

        membership.assert_not_called()
        mock_websocket.accept.assert_called_once()


# --------------------------------------------------------------------------- #
# HTTP Endpoint Tests                                                        #
# --------------------------------------------------------------------------- #


class TestAuthenticateReverseProxyWebSocket:
    """Test the WebSocket bearer-token parser and admission helper."""

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


class TestWebSocketAuthEdgeCases:
    """Test WebSocket authentication edge cases."""

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_http_exception(self, mock_websocket):
        """JWT verification raises HTTPException."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer bad-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token"))):
            await websocket_endpoint(mock_websocket)

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
                await websocket_endpoint(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_query_token_http_exception(self, mock_websocket):
        """Query token verification raises HTTPException."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "bad-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new_callable=AsyncMock) as get_current_user:
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

        # Should have accepted and then cleanly disconnected
        mock_websocket.accept.assert_called_once()


class TestWebSocketTokenMissingSubject:
    """Tests for token payloads missing sub/email claim."""

    @pytest.mark.asyncio
    async def test_bearer_token_missing_subject(self, mock_websocket):
        """Bearer token auth failure is rejected."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.get_current_user", new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token"))):
            await websocket_endpoint(mock_websocket)

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
            await websocket_endpoint(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.send_denial_response.assert_awaited_once()
        assert mock_websocket.send_denial_response.call_args.args[0].status_code == status.HTTP_401_UNAUTHORIZED
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
    @pytest.fixture(autouse=True)
    def allow_http_rbac(self):
        """Allow Layer-2 checks by default; deny-path tests override this seam."""
        checker = Mock(has_permission=AsyncMock(return_value=True))
        with patch("mcpgateway.routers.reverse_proxy.PermissionChecker", return_value=checker):
            yield checker
