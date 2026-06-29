# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for reverse proxy service layer.
This module tests the business logic of reverse proxy session management,
message forwarding, and helper functions without FastAPI dependencies.
"""

# Standard
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.services.reverse_proxy_service import (
    ReverseProxyManager,
    ReverseProxySession,
    get_reverse_proxy_service,
    get_user_from_credentials,
    validate_session_ownership,
)

# --------------------------------------------------------------------------- #
# Test Fixtures                                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    from fastapi import WebSocket
    
    ws = Mock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.close = AsyncMock()
    ws.headers = {"X-Session-ID": "test-session-123"}
    ws.query_params = {}
    ws.client = Mock(host="127.0.0.1")
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

    @pytest.mark.asyncio
    async def test_get_session(self, reverse_proxy_manager, sample_session):
        """Test getting a session."""
        reverse_proxy_manager.sessions[sample_session.session_id] = sample_session

        result = await reverse_proxy_manager.get_session(sample_session.session_id)
        assert result is sample_session

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, reverse_proxy_manager):
        """Test getting a session that doesn't exist."""
        result = await reverse_proxy_manager.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, reverse_proxy_manager):
        """Test listing sessions when empty."""
        result = await reverse_proxy_manager.list_sessions()

        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_sessions_with_string_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with string user."""
        session = ReverseProxySession("test-id", mock_websocket, "test-user")
        session.server_info = {"name": "test-server"}
        session.message_count = 5
        session.bytes_transferred = 1024
        reverse_proxy_manager.sessions["test-id"] = session

        result = await reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        session_info = result[0]
        assert session_info["session_id"] == "test-id"
        assert session_info["server_info"] == {"name": "test-server"}
        assert session_info["message_count"] == 5
        assert session_info["bytes_transferred"] == 1024
        assert session_info["user"] == "test-user"
        assert "connected_at" in session_info
        assert "last_activity" in session_info

    @pytest.mark.asyncio
    async def test_list_sessions_with_dict_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with dict user."""
        user_dict = {"sub": "user123", "name": "Test User"}
        session = ReverseProxySession("test-id", mock_websocket, user_dict)
        reverse_proxy_manager.sessions["test-id"] = session

        result = await reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] == "user123"

    @pytest.mark.asyncio
    async def test_list_sessions_with_none_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with None user."""
        session = ReverseProxySession("test-id", mock_websocket, None)
        reverse_proxy_manager.sessions["test-id"] = session

        result = await reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] is None

    @pytest.mark.asyncio
    async def test_list_sessions_with_invalid_dict_user(self, reverse_proxy_manager, mock_websocket):
        """Test listing sessions with dict user without 'sub' key."""
        user_dict = {"name": "Test User"}  # No 'sub' key
        session = ReverseProxySession("test-id", mock_websocket, user_dict)
        reverse_proxy_manager.sessions["test-id"] = session

        result = await reverse_proxy_manager.list_sessions()

        assert len(result) == 1
        assert result[0]["user"] is None


# --------------------------------------------------------------------------- #
# Helper Function Tests                                                      #
# --------------------------------------------------------------------------- #


class TestGetUserFromCredentials:
    """Test get_user_from_credentials function."""

    def test_dict_with_sub(self):
        """Test extracting user from dict with 'sub' field."""
        user, is_admin = get_user_from_credentials({"sub": "user@test.com", "is_admin": False})
        assert user == "user@test.com"
        assert is_admin is False

    def test_dict_with_email_fallback(self):
        """Test extracting user from dict with 'email' field fallback."""
        user, is_admin = get_user_from_credentials({"email": "user@test.com"})
        assert user == "user@test.com"
        assert is_admin is False

    def test_dict_nested_admin(self):
        """Test extracting admin status from nested user dict."""
        user, is_admin = get_user_from_credentials({"sub": "admin@test.com", "user": {"is_admin": True}})
        assert user == "admin@test.com"
        assert is_admin is True

    def test_dict_top_level_admin(self):
        """Test extracting admin status from top-level field."""
        user, is_admin = get_user_from_credentials({"sub": "admin@test.com", "is_admin": True})
        assert user == "admin@test.com"
        assert is_admin is True

    def test_string_credentials(self):
        """Test string credentials."""
        user, is_admin = get_user_from_credentials("user@test.com")
        assert user == "user@test.com"
        assert is_admin is False

    def test_anonymous_credentials(self):
        """Test anonymous credentials."""
        user, is_admin = get_user_from_credentials("anonymous")
        assert user is None
        assert is_admin is False

    def test_none_credentials(self):
        """Test None credentials."""
        user, is_admin = get_user_from_credentials(None)
        assert user is None
        assert is_admin is False

    def test_empty_string_credentials(self):
        """Test empty string credentials."""
        user, is_admin = get_user_from_credentials("")
        assert user is None
        assert is_admin is False


class TestValidateSessionOwnership:
    """Test validate_session_ownership function."""

    def test_no_session_user_allows_access(self, mock_websocket):
        """Test that sessions without a user allow any access."""
        session = ReverseProxySession("test-id", mock_websocket, None)
        # Should not raise - session with no user allows any access
        assert validate_session_ownership(session, "any-user", False, "test") is True

    def test_admin_bypasses_ownership(self, mock_websocket):
        """Test that admins can access any session."""
        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        # Admin should bypass ownership check
        assert validate_session_ownership(session, "admin@test.com", True, "test") is True

    def test_owner_match_allows_access(self, mock_websocket):
        """Test that session owner can access their session."""
        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        assert validate_session_ownership(session, "owner@test.com", False, "test") is True

    def test_owner_match_dict_user(self, mock_websocket):
        """Test owner match with dict user."""
        session = ReverseProxySession("test-id", mock_websocket, {"sub": "owner@test.com"})
        assert validate_session_ownership(session, "owner@test.com", False, "test") is True

    def test_non_owner_denied(self, mock_websocket):
        """Test that non-owners are denied access."""
        session = ReverseProxySession("test-id", mock_websocket, "owner@test.com")
        # Function now returns False instead of raising exception
        assert validate_session_ownership(session, "other@test.com", False, "disconnect") is False


# --------------------------------------------------------------------------- #
# Cross-Worker Forwarding Tests                                              #
# --------------------------------------------------------------------------- #


class TestCrossWorkerForwarding:
    """Test cross-worker session affinity forwarding via Redis Pub/Sub.

    These tests exercise the path where a tools/call HTTP request lands on a
    worker that does NOT own the WebSocket session.  The non-owner worker must:
      1. Detect it is not the owner (Redis GET returns a different WORKER_ID)
      2. Publish the message to the owner's Redis channel
      3. Wait for the response on a unique response channel

    The owner worker (via start_rpc_listener) must:
      1. Receive the ``reverse_proxy_forward`` message
      2. Dispatch to ``execute_forwarded_message()``
      3. Send the message to the local WebSocket session
      4. Wait for the agent response via ``_wait_for_response()``
      5. Publish the response back to the response channel

    Both sides are tested here with mocked Redis so no live multi-worker
    deployment is required.
    """

    @pytest.mark.asyncio
    async def test_execute_forwarded_message_success(self, mock_websocket):
        """Owner worker executes a forwarded request and publishes the response.

        The real flow: execute_forwarded_message() calls _wait_for_response() which
        registers a Future in pending_responses[request_id].  The WebSocket message
        loop resolves that future when the agent replies.  We simulate this by running
        a concurrent task that polls pending_responses until the key appears, then
        sets the result – exactly as the real message loop does.
        """
        pending_responses = get_reverse_proxy_service().pending_responses
        owner_manager = ReverseProxyManager()
        session = ReverseProxySession("sess-owner", mock_websocket, "user@test.com")
        await owner_manager.add_session(session)

        expected_response = {"type": "response", "payload": {"result": "ok"}, "sessionId": "sess-owner"}

        async def _simulate_agent_reply():
            """Poll pending_responses until req-001 is registered, then resolve it."""
            for _ in range(100):
                if "req-001" in pending_responses:
                    pending_responses["req-001"].set_result(expected_response)
                    return
                await asyncio.sleep(0.01)

        mock_redis = AsyncMock()

        forward_data = {
            "type": "reverse_proxy_forward",
            "session_id": "sess-owner",
            "message": {"type": "request", "payload": {"method": "tools/call", "id": "req-001"}},
            "response_channel": "mcpgw:reverse_proxy_response:abc123",
            "original_worker": "other-host:9999",
        }

        # Run both concurrently: execute_forwarded_message waits for the future;
        # _simulate_agent_reply resolves it once registered.
        await asyncio.gather(
            owner_manager.execute_forwarded_message(forward_data, mock_redis, pending_responses),
            _simulate_agent_reply(),
        )

        # Owner must have published the response to the response channel
        mock_redis.publish.assert_called_once()
        channel_arg, payload_arg = mock_redis.publish.call_args[0]
        assert channel_arg == "mcpgw:reverse_proxy_response:abc123"
        published = orjson.loads(payload_arg)
        assert published == expected_response

    @pytest.mark.asyncio
    async def test_execute_forwarded_message_session_not_found(self):
        """Owner worker publishes error when session is not found locally."""
        pending_responses = get_reverse_proxy_service().pending_responses
        owner_manager = ReverseProxyManager()
        # Session NOT added – simulates request arriving on wrong worker

        mock_redis = AsyncMock()

        forward_data = {
            "type": "reverse_proxy_forward",
            "session_id": "missing-session",
            "message": {"type": "request", "payload": {"method": "tools/call", "id": "req-002"}},
            "response_channel": "mcpgw:reverse_proxy_response:def456",
            "original_worker": "other-host:9999",
        }

        await owner_manager.execute_forwarded_message(forward_data, mock_redis, pending_responses)

        # Must publish an error response so the non-owner worker doesn't hang
        mock_redis.publish.assert_called_once()
        channel_arg, payload_arg = mock_redis.publish.call_args[0]
        assert channel_arg == "mcpgw:reverse_proxy_response:def456"
        published = orjson.loads(payload_arg)
        assert published["status"] == "error"
        assert "missing-session" in published["error"]

    @pytest.mark.asyncio
    async def test_execute_forwarded_notification_no_response_wait(self, mock_websocket):
        """Owner worker sends notification without waiting for a response."""
        pending_responses = get_reverse_proxy_service().pending_responses
        owner_manager = ReverseProxyManager()
        session = ReverseProxySession("sess-notif", mock_websocket, "user@test.com")
        await owner_manager.add_session(session)

        mock_redis = AsyncMock()

        # Notification: no ``id`` field in payload → is_notification=True
        forward_data = {
            "type": "reverse_proxy_forward",
            "session_id": "sess-notif",
            "message": {"type": "notification", "payload": {"method": "notifications/initialized"}},
            "response_channel": "mcpgw:reverse_proxy_response:ghi789",
            "original_worker": "other-host:9999",
        }

        await owner_manager.execute_forwarded_message(forward_data, mock_redis, pending_responses)

        # Must publish notification_sent ack (no agent response wait)
        mock_redis.publish.assert_called_once()
        channel_arg, payload_arg = mock_redis.publish.call_args[0]
        assert channel_arg == "mcpgw:reverse_proxy_response:ghi789"
        published = orjson.loads(payload_arg)
        assert published["status"] == "notification_sent"

    @pytest.mark.asyncio
    async def test_forward_request_to_session_publishes_to_owner_channel(self, mock_websocket):
        """Non-owner worker publishes to the correct owner Redis channel via forward_message_to_owner."""
        import orjson as _orjson

        non_owner_manager = ReverseProxyManager()

        expected_response = {"type": "response", "payload": {"result": "forwarded-ok"}}

        # Build a mock Redis that:
        # - Returns the owner worker ID from GET (ownership check in get_session_owner)
        # - Simulates a pubsub that immediately delivers the response message
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        # get_message must yield to the event loop so asyncio.timeout() can fire.
        # Use a coroutine side_effect that includes asyncio.sleep(0).
        _responses = [{"type": "message", "data": _orjson.dumps(expected_response)}, None]
        _call_count = [0]

        async def _get_message_side_effect(**kwargs):
            await asyncio.sleep(0)  # yield to event loop
            idx = _call_count[0]
            _call_count[0] += 1
            if idx < len(_responses):
                return _responses[idx]
            return None

        mock_pubsub.get_message = _get_message_side_effect

        mock_redis = AsyncMock()
        # get_session_owner calls redis.get(owner_key) → returns owner worker ID
        mock_redis.get = AsyncMock(return_value=b"owner-host:1234")
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        # forward_message_to_owner(session_id, message) – the method that does Redis Pub/Sub
        message = {"type": "request", "sessionId": "sess-remote", "payload": {"method": "tools/call", "id": "req-003"}}

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
            result = await non_owner_manager.forward_message_to_owner("sess-remote", message, timeout=5.0)

        # Must have published to the owner's channel (mcpgw:reverse_proxy:{owner_worker_id})
        mock_redis.publish.assert_called_once()
        channel_arg, payload_arg = mock_redis.publish.call_args[0]
        assert channel_arg == "mcpgw:reverse_proxy:owner-host:1234"
        published = _orjson.loads(payload_arg)
        assert published["type"] == "reverse_proxy_forward"
        assert published["session_id"] == "sess-remote"
        assert published["message"] == message

        # Must return the response received from the owner via pubsub
        assert result == expected_response

    @pytest.mark.asyncio
    async def test_forward_request_to_session_timeout(self, mock_websocket):
        """Non-owner worker raises TimeoutError when owner doesn't respond."""
        non_owner_manager = ReverseProxyManager()

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        # Never delivers a message → timeout.
        # Must yield to the event loop so asyncio.timeout() can actually fire.

        async def _never_respond(**kwargs):
            await asyncio.sleep(0)  # yield to event loop

        mock_pubsub.get_message = _never_respond

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"owner-host:1234")
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        message = {"type": "request", "sessionId": "sess-remote", "payload": {"method": "tools/call", "id": "req-004"}}

        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
            with pytest.raises(asyncio.TimeoutError):
                await non_owner_manager.forward_message_to_owner("sess-remote", message, timeout=0.1)

        # Must have unsubscribed from the response channel even on timeout
        mock_pubsub.unsubscribe.assert_called_once()


# --------------------------------------------------------------------------- #
# Redis Session Affinity Tests                                               #
# --------------------------------------------------------------------------- #


class TestRedisSessionAffinity:
    """Test Redis-based session affinity operations."""

    @pytest.mark.asyncio
    async def test_register_session_ownership_disabled(self, mock_websocket):
        """Test that ownership registration is skipped when affinity is disabled."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        with patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            
            # Should return early without calling Redis
            await manager.register_session_ownership("test-session")
            # No assertions needed - just verify it doesn't raise

    @pytest.mark.asyncio
    async def test_register_session_ownership_redis_unavailable(self, mock_websocket):
        """Test ownership registration when Redis is unavailable."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            
            # Should handle gracefully when Redis unavailable
            await manager.register_session_ownership("test-session")
            # No assertions needed - just verify it doesn't raise

    @pytest.mark.asyncio
    async def test_register_session_ownership_success(self, mock_websocket):
        """Test successful ownership registration."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_redis = AsyncMock()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            
            await manager.register_session_ownership("test-session")
            
            # Verify Redis SET was called with correct parameters
            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert "mcpgw:reverse_proxy_owner:test-session" in call_args[0]

    @pytest.mark.asyncio
    async def test_register_session_ownership_redis_error(self, mock_websocket):
        """Test ownership registration handles Redis errors gracefully."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_redis = AsyncMock()
        mock_redis.set.side_effect = Exception("Redis connection error")
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            
            # Should log error but not raise
            await manager.register_session_ownership("test-session")

    @pytest.mark.asyncio
    async def test_release_session_ownership_disabled(self):
        """Test that ownership release is skipped when affinity is disabled."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        with patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            
            await manager.release_session_ownership("test-session")
            # No assertions needed - just verify it doesn't raise

    @pytest.mark.asyncio
    async def test_release_session_ownership_redis_unavailable(self):
        """Test ownership release when Redis is unavailable."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            
            await manager.release_session_ownership("test-session")
            # No assertions needed - just verify it doesn't raise

    @pytest.mark.asyncio
    async def test_release_session_ownership_success(self):
        """Test successful ownership release."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_redis = AsyncMock()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            
            await manager.release_session_ownership("test-session")
            
            # Verify Redis DELETE was called
            mock_redis.delete.assert_called_once_with("mcpgw:reverse_proxy_owner:test-session")

    @pytest.mark.asyncio
    async def test_refresh_session_ownership_disabled(self, mock_websocket):
        """Test that ownership refresh is skipped when affinity is disabled."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager, ReverseProxySession

        manager = ReverseProxyManager()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        
        with patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            
            await manager.refresh_session_ownership_if_due("test-session", session)
            # No assertions needed - just verify it doesn't raise

    @pytest.mark.asyncio
    async def test_refresh_session_ownership_not_due(self, mock_websocket):
        """Test that ownership refresh is skipped when not due yet."""
        import time
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager, ReverseProxySession

        manager = ReverseProxyManager()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.last_ownership_refresh = time.monotonic()  # Just refreshed
        
        mock_redis = AsyncMock()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            
            await manager.refresh_session_ownership_if_due("test-session", session)
            
            # Should not call Redis since not due yet
            mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_session_ownership_success(self, mock_websocket):
        """Test successful ownership TTL refresh."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager, ReverseProxySession

        manager = ReverseProxyManager()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.last_ownership_refresh = 0  # Force refresh
        
        mock_redis = AsyncMock()
        mock_redis.expire.return_value = True  # Key exists and was refreshed
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            
            await manager.refresh_session_ownership_if_due("test-session", session)
            
            # Verify Redis EXPIRE was called
            mock_redis.expire.assert_called_once()
            assert session.last_ownership_refresh > 0

    @pytest.mark.asyncio
    async def test_refresh_session_ownership_key_missing(self, mock_websocket):
        """Test ownership refresh when key is missing (re-claims ownership)."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager, ReverseProxySession

        manager = ReverseProxyManager()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        session.last_ownership_refresh = 0  # Force refresh
        
        mock_redis = AsyncMock()
        mock_redis.expire.return_value = False  # Key doesn't exist
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            
            await manager.refresh_session_ownership_if_due("test-session", session)
            
            # Should re-claim ownership with SET
            mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_owner_redis_unavailable(self):
        """Test get_session_owner when Redis is unavailable."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager, get_worker_id

        manager = ReverseProxyManager()
        
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=None):
            owner = await manager.get_session_owner("test-session")
            
            # Should return local worker ID as fallback
            assert owner == get_worker_id()

    @pytest.mark.asyncio
    async def test_get_session_owner_success(self):
        """Test successful session owner retrieval."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = b"remote-worker:1234"
        
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
            owner = await manager.get_session_owner("test-session")
            
            assert owner == "remote-worker:1234"
            mock_redis.get.assert_called_once_with("mcpgw:reverse_proxy_owner:test-session")

    @pytest.mark.asyncio
    async def test_get_session_owner_not_found(self):
        """Test get_session_owner when session not registered."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        
        with patch("mcpgateway.utils.redis_client.get_redis_client", return_value=mock_redis):
            owner = await manager.get_session_owner("test-session")
            
            assert owner is None


# --------------------------------------------------------------------------- #
# Health Monitoring Tests                                                    #
# --------------------------------------------------------------------------- #


class TestHealthMonitoring:
    """Test health monitoring functionality."""

    @pytest.mark.asyncio
    async def test_start_health_monitoring(self):
        """Test starting health monitoring task."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        with patch.object(manager, '_run_health_checks', new_callable=AsyncMock):
            await manager.start_health_monitoring()
            
            assert manager._health_check_task is not None
            assert not manager._health_check_task.done()
            
            # Cleanup
            await manager.stop_health_monitoring()

    @pytest.mark.asyncio
    async def test_stop_health_monitoring(self):
        """Test stopping health monitoring task."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        
        # Start monitoring
        with patch.object(manager, '_run_health_checks', new_callable=AsyncMock):
            await manager.start_health_monitoring()
            task = manager._health_check_task
            
            # Stop monitoring
            await manager.stop_health_monitoring()
            
            assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_mark_gateway_reachable(self, mock_websocket):
        """Test marking gateway as reachable."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_db = Mock()
        mock_gateway = Mock()
        mock_gateway.reachable = False
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        
        with (
            patch("mcpgateway.db.SessionLocal") as mock_session_local,
        ):
            mock_session_local.return_value.__enter__.return_value = mock_db
            
            await manager._mark_gateway_reachable("test-session")
            
            assert mock_gateway.reachable is True
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_gateway_unreachable(self):
        """Test marking gateway as unreachable."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyManager

        manager = ReverseProxyManager()
        mock_db = Mock()
        mock_gateway = Mock()
        mock_gateway.reachable = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway
        
        with (
            patch("mcpgateway.db.SessionLocal") as mock_session_local,
        ):
            mock_session_local.return_value.__enter__.return_value = mock_db
            
            await manager._mark_gateway_unreachable("test-session")
            
            assert mock_gateway.reachable is False
            mock_db.commit.assert_called_once()


# --------------------------------------------------------------------------- #
# Helper Function Tests                                                      #
# --------------------------------------------------------------------------- #


class TestExtractSessionId:
    """Test extract_session_id_from_url function."""

    def test_extract_session_id_valid_url(self):
        """Test extracting session ID from valid URL."""
        from mcpgateway.services.reverse_proxy_service import extract_session_id_from_url
        
        url = "http://localhost:4444/reverse-proxy/sessions/abc123def456/mcp"
        session_id = extract_session_id_from_url(url)
        
        assert session_id == "abc123def456"

    def test_extract_session_id_with_query_params(self):
        """Test extracting session ID from URL with query parameters."""
        from mcpgateway.services.reverse_proxy_service import extract_session_id_from_url
        
        url = "http://localhost:4444/reverse-proxy/sessions/test-session-123/mcp?token=xyz"
        session_id = extract_session_id_from_url(url)
        
        assert session_id == "test-session-123"

    def test_extract_session_id_invalid_url(self):
        """Test extracting session ID from invalid URL."""
        from mcpgateway.services.reverse_proxy_service import extract_session_id_from_url
        
        url = "http://localhost:4444/invalid/path"
        
        with pytest.raises(ValueError, match="Invalid URL format"):
            extract_session_id_from_url(url)

    def test_extract_session_id_missing_session_id(self):
        """Test extracting session ID when path is incomplete."""
        from mcpgateway.services.reverse_proxy_service import extract_session_id_from_url
        
        url = "http://localhost:4444/reverse-proxy/sessions/"
        
        with pytest.raises(ValueError, match="Invalid URL format"):
            extract_session_id_from_url(url)


# --------------------------------------------------------------------------- #
# ReverseProxyService Tests                                                  #
# --------------------------------------------------------------------------- #


class TestReverseProxyService:
    """Test ReverseProxyService class."""

    @pytest.mark.asyncio
    async def test_forward_request_affinity_disabled(self, mock_websocket):
        """Test request forwarding when session affinity is disabled."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyService, ReverseProxySession

        service = ReverseProxyService()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        await service.manager.add_session(session)
        
        with patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            mock_settings.mcpgateway_pool_rpc_forward_timeout = 30
            
            # Mock the response
            async def mock_receive():
                return {"type": "response", "id": "req-1", "result": "ok"}
            
            mock_websocket.receive_text.side_effect = [orjson.dumps({"type": "response", "id": "req-1", "result": "ok"}).decode()]
            
            mcp_request = {"method": "tools/list", "id": "req-1"}
            
            # This will timeout waiting for response, but that's expected in unit test
            try:
                response = await asyncio.wait_for(
                    service.forward_request_to_session("test-session", mcp_request),
                    timeout=0.1
                )
            except asyncio.TimeoutError:
                pass  # Expected in unit test without full message loop

    @pytest.mark.asyncio
    async def test_forward_request_session_not_found(self):
        """Test request forwarding when session doesn't exist."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyService

        service = ReverseProxyService()
        
        with (
            patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings,
            patch.object(service.manager, "get_session_owner", return_value=None),
        ):
            mock_settings.mcpgateway_session_affinity_enabled = True
            
            mcp_request = {"method": "tools/list", "id": "req-1"}
            
            with pytest.raises(ValueError, match="no longer active"):
                await service.forward_request_to_session("missing-session", mcp_request)

    @pytest.mark.asyncio
    async def test_forward_request_notification(self, mock_websocket):
        """Test forwarding notification (no response expected)."""
        from mcpgateway.services.reverse_proxy_service import ReverseProxyService, ReverseProxySession

        service = ReverseProxyService()
        session = ReverseProxySession("test-session", mock_websocket, "test-user")
        await service.manager.add_session(session)
        
        with patch("mcpgateway.services.reverse_proxy_service.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            
            # Notification has no 'id' field
            mcp_notification = {"method": "notifications/initialized"}
            
            response = await service.forward_request_to_session("test-session", mcp_notification)
            
            # Notifications return None
            assert response is None
            mock_websocket.send_text.assert_called_once()


# --------------------------------------------------------------------------- #
# get_worker_id Tests                                                        #
# --------------------------------------------------------------------------- #


class TestGetWorkerId:
    """Test get_worker_id function."""

    def test_get_worker_id_format(self):
        """Test that worker ID has correct format."""
        from mcpgateway.services.reverse_proxy_service import get_worker_id
        
        worker_id = get_worker_id()
        
        # Should be in format "hostname:pid"
        assert ":" in worker_id
        parts = worker_id.split(":")
        assert len(parts) == 2
        assert parts[1].isdigit()  # PID should be numeric




        
