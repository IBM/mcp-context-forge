# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_reverse_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for reverse proxy router.
This module tests the reverse proxy functionality including WebSocket connections,
session management, and HTTP endpoints.
"""

# Standard
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import orjson

# Third-Party
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.routers.reverse_proxy import (
    manager,
    ReverseProxyManager,
    ReverseProxySession,
    router,
)
from mcpgateway.utils.verify_credentials import require_auth

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
    """Test WebSocket endpoint functionality.

    Note: These tests disable authentication to test WebSocket message handling.
    See TestWebSocketAuthentication for authentication tests.
    """

    @pytest.fixture(autouse=True)
    def mock_auth_settings(self):
        """Disable authentication for WebSocket endpoint tests."""
        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = False
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False
            yield mock_settings

    @pytest.mark.asyncio
    async def test_websocket_accept(self, mock_websocket):
        """Test WebSocket connection acceptance."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_generates_session_id(self, mock_websocket):
        """Test WebSocket generates session ID when not provided."""
        mock_websocket.headers = {}  # No X-Session-ID header
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db, patch("mcpgateway.routers.reverse_proxy.uuid.uuid4") as mock_uuid:
            mock_get_db.return_value = Mock()
            mock_uuid.return_value.hex = "generated-session-id"

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        mock_uuid.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_register_message(self, mock_websocket):
        """Test handling register message."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        register_msg = {"type": "register", "server": {"name": "test-server", "version": "1.0"}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(register_msg).decode(), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        # Should send register acknowledgment
        mock_websocket.send_text.assert_called()
        sent_data = orjson.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "register_ack"
        assert sent_data["status"] == "success"

    @pytest.mark.asyncio
    async def test_websocket_unregister_message(self, mock_websocket):
        """Test handling unregister message."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        unregister_msg = {"type": "unregister"}
        mock_websocket.receive_text.return_value = orjson.dumps(unregister_msg).decode()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            await websocket_endpoint(mock_websocket, Mock())

    @pytest.mark.asyncio
    async def test_websocket_heartbeat_message(self, mock_websocket):
        """Test handling heartbeat message."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        heartbeat_msg = {"type": "heartbeat"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(heartbeat_msg).decode(), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        # Should send heartbeat response
        mock_websocket.send_text.assert_called()
        sent_data = orjson.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "heartbeat"
        assert "timestamp" in sent_data

    @pytest.mark.asyncio
    async def test_websocket_response_message(self, mock_websocket):
        """Test handling response message."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        response_msg = {"type": "response", "id": 1, "result": {"data": "test"}}
        mock_websocket.receive_text.side_effect = [orjson.dumps(response_msg).decode(), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_websocket_notification_message(self, mock_websocket):
        """Test handling notification message."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        notification_msg = {"type": "notification", "method": "test/notification"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(notification_msg).decode(), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_websocket_unknown_message_type(self, mock_websocket):
        """Test handling unknown message type."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        unknown_msg = {"type": "unknown", "data": "test"}
        mock_websocket.receive_text.side_effect = [orjson.dumps(unknown_msg).decode(), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_websocket_invalid_json(self, mock_websocket):
        """Test handling invalid JSON."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        mock_websocket.receive_text.side_effect = ["invalid json", asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        # Should send error message
        mock_websocket.send_text.assert_called()
        sent_data = orjson.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "error"
        assert "Invalid JSON format" in sent_data["message"]

    @pytest.mark.asyncio
    async def test_websocket_general_exception(self, mock_websocket):
        """Test handling general exception during message processing."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}
        # First call succeeds, second call raises exception, third call cancels
        mock_websocket.receive_text.side_effect = [orjson.dumps({"type": "register", "server": {"name": "test"}}).decode(), Exception("Test exception"), asyncio.CancelledError()]

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
            mock_get_db.return_value = Mock()

            try:
                await websocket_endpoint(mock_websocket, Mock())
            except asyncio.CancelledError:
                pass

        # Should send register ack and error message
        assert mock_websocket.send_text.call_count >= 2


class TestWebSocketAuthentication:
    """Test WebSocket authentication functionality."""

    @pytest.mark.asyncio
    async def test_websocket_rejects_unauthenticated_when_auth_required(self, mock_websocket):
        """Test WebSocket rejects connection when auth required but no token provided."""
        mock_websocket.headers = {"X-Session-ID": "test-session"}  # No Authorization header
        mock_websocket.query_params = {}

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
                mock_get_db.return_value = Mock()

                await websocket_endpoint(mock_websocket, Mock())

        # Should NOT accept the connection
        mock_websocket.accept.assert_not_called()
        # Should close with policy violation
        mock_websocket.close.assert_called_once()
        assert mock_websocket.close.call_args[1]["code"] == 1008  # WS_1008_POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_websocket_accepts_with_valid_token(self, mock_websocket):
        """Test WebSocket accepts connection with valid JWT token."""
        mock_websocket.headers = {"X-Session-ID": "test-session", "Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db, patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_get_db.return_value = Mock()
                mock_verify.return_value = {"sub": "test-user", "email": "test@example.com"}

                try:
                    await websocket_endpoint(mock_websocket, Mock())
                except asyncio.CancelledError:
                    pass

        # Should accept the connection
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_accepts_proxy_auth(self, mock_websocket):
        """Test WebSocket accepts proxy authentication."""
        mock_websocket.headers = {"X-Session-ID": "test-session", "X-Authenticated-User": "proxy-user"}
        mock_websocket.query_params = {}
        mock_websocket.receive_text.side_effect = asyncio.CancelledError()

        # First-Party
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = "X-Authenticated-User"

            with patch("mcpgateway.routers.reverse_proxy.get_db") as mock_get_db:
                mock_get_db.return_value = Mock()

                try:
                    await websocket_endpoint(mock_websocket, Mock())
                except asyncio.CancelledError:
                    pass

        # Should accept the connection
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

    def test_sse_endpoint_success(self, client, mock_websocket):
        """Test SSE endpoint with existing session."""
        # Add a test session
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        manager.sessions["test-session"] = session

        try:
            # Skip this test for now due to SSE streaming complexity
            pytest.skip("SSE endpoint test requires complex streaming response mocking")
        finally:
            # Clean up
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
        from fastapi import HTTPException
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer bad-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.side_effect = HTTPException(status_code=401, detail="Invalid token")
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_general_exception(self, mock_websocket):
        """JWT verification raises generic exception."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer bad-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.side_effect = ValueError("Malformed token")
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_query_token_http_exception(self, mock_websocket):
        """Query token verification raises HTTPException."""
        from fastapi import HTTPException
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "bad-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.side_effect = HTTPException(status_code=401, detail="Invalid token")
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_query_token_general_exception(self, mock_websocket):
        """Query token verification raises generic exception."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "bad-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.side_effect = ValueError("Bad token")
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_proxy_auth_no_header(self, mock_websocket):
        """Proxy auth enabled but no proxy header → reject."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = "X-Authenticated-User"

            await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_disconnect_exception(self, mock_websocket):
        """WebSocketDisconnect during message loop."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {}
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = False
            mock_settings.mcp_client_auth_enabled = False

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
        """Bearer token verified but has no sub or email → ValueError caught."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {"Authorization": "Bearer valid-token"}
        mock_websocket.query_params = {}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.return_value = {"iss": "test", "iat": 123}  # No sub or email
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_token_missing_subject(self, mock_websocket):
        """Query token verified but has no sub or email → ValueError caught."""
        from mcpgateway.routers.reverse_proxy import websocket_endpoint

        mock_websocket.headers = {}
        mock_websocket.query_params = {"token": "valid-query-token"}

        with patch("mcpgateway.routers.reverse_proxy.settings") as mock_settings:
            mock_settings.auth_required = True
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = False

            with patch("mcpgateway.routers.reverse_proxy.verify_jwt_token") as mock_verify:
                mock_verify.return_value = {"iss": "test", "iat": 123}  # No sub or email
                await websocket_endpoint(mock_websocket, Mock())

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
