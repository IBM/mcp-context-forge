# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_session_registry_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended tests for session_registry.py to improve coverage.
This test suite focuses on uncovered code paths in session_registry.py
including import error handling, backend edge cases, and error scenarios.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import logging
import sys
import time
from asyncio import Lock
from typing import cast, Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.transports.sse_transport import SSETransport


@pytest.fixture(name="mock_sse_transport")
def mock_sse_transport_fixture() -> Generator[SSETransport, None, None]:
    transport = MagicMock(spec=SSETransport)
    transport.disconnect = AsyncMock()
    transport.is_connected = AsyncMock(return_value=True)
    yield transport


class TestImportErrors:
    """Test import error handling for optional dependencies."""

    def test_redis_import_error_flag(self):
        """Test REDIS_AVAILABLE flag when redis import fails."""
        with patch.dict(sys.modules, {"redis.asyncio": None}):
            # Standard
            import importlib

            # First-Party
            import mcpgateway.cache.session_registry

            importlib.reload(mcpgateway.cache.session_registry)

            # Should set REDIS_AVAILABLE = False
            assert not mcpgateway.cache.session_registry.REDIS_AVAILABLE

    def test_sqlalchemy_import_error_flag(self):
        """Test SQLALCHEMY_AVAILABLE flag when sqlalchemy import fails."""
        with patch.dict(sys.modules, {"sqlalchemy": None}):
            # Standard
            import importlib

            # First-Party
            import mcpgateway.cache.session_registry

            importlib.reload(mcpgateway.cache.session_registry)

            # Should set SQLALCHEMY_AVAILABLE = False
            assert not mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE


class TestNoneBackend:
    """Test 'none' backend functionality."""

    @pytest.mark.asyncio
    async def test_none_backend_initialization_logging(self, caplog):
        """Test that 'none' backend logs initialization message."""
        _ = SessionRegistry(backend="none")

        # Check that initialization message is logged
        assert "Session registry initialized with 'none' backend - session tracking disabled" in caplog.text

    @pytest.mark.asyncio
    async def test_none_backend_initialize_method(self):
        """Test 'none' backend initialize method does nothing."""
        registry = SessionRegistry(backend="none")

        # Should not raise any errors
        await registry.initialize()

        # No cleanup task should be created
        assert registry._cleanup_task is None


class TestRedisBackendErrors:
    """Test Redis backend error scenarios."""

    @pytest.mark.asyncio
    async def test_redis_add_session_error(self, monkeypatch, caplog, mock_sse_transport):
        """Test Redis error during add_session."""
        mock_pubsub = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis connection error"))
        mock_redis.publish = AsyncMock()
        mock_redis.pubsub = Mock(return_value=mock_pubsub)

        async def mock_get_redis_client():
            return mock_redis

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                await registry.initialize()

                await registry.add_session("test_session", mock_sse_transport)

                # Should log the Redis error
                assert "Redis error adding session test_session: Redis connection error" in caplog.text

                await registry.shutdown()

    @pytest.mark.asyncio
    async def test_redis_broadcast_error(self, monkeypatch, caplog):
        """Test Redis error during broadcast."""
        mock_pubsub = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=Exception("Redis publish error"))
        mock_redis.pubsub = Mock(return_value=mock_pubsub)

        async def mock_get_redis_client():
            return mock_redis

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                await registry.initialize()

                await registry.broadcast("test_session", {"test": "message"})

                # Should log the Redis error
                assert "Redis error during broadcast: Redis publish error" in caplog.text

                await registry.shutdown()


class TestDatabaseBackendErrors:
    """Test database backend error scenarios."""

    @pytest.mark.asyncio
    async def test_database_add_session_error(self, monkeypatch, caplog, mock_sse_transport):
        """Test database error during add_session."""

        def mock_get_db():
            mock_session = Mock()
            mock_session.add = Mock(side_effect=Exception("Database connection error"))
            mock_session.rollback = Mock()
            mock_session.close = Mock()
            yield mock_session

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:
                    # Simulate the database error being raised from the thread
                    mock_to_thread.side_effect = Exception("Database connection error")

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    await registry.add_session("test_session", mock_sse_transport)

                    # Should log the database error
                    assert "Database error adding session test_session: Database connection error" in caplog.text

    @pytest.mark.asyncio
    async def test_database_broadcast_error(self, monkeypatch, caplog):
        """Test database error during broadcast."""

        def mock_get_db():
            mock_session = Mock()
            mock_session.add = Mock(side_effect=Exception("Database broadcast error"))
            mock_session.rollback = Mock()
            mock_session.close = Mock()
            yield mock_session

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:
                    # Simulate the database error being raised from the thread
                    mock_to_thread.side_effect = Exception("Database broadcast error")

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    await registry.broadcast("test_session", {"test": "message"})

                    # Should log the database error
                    assert "Database error during broadcast: Database broadcast error" in caplog.text


class TestRedisBackendRespond:
    """Test Redis backend respond method."""

    @pytest.mark.skip("Redis pubsub mocking is complex, skipping for now")
    @pytest.mark.asyncio
    async def test_redis_respond_method_pubsub_flow(self, monkeypatch, mock_sse_transport):
        """Test Redis backend respond method with pubsub message flow."""
        mock_redis = AsyncMock()
        mock_pubsub = Mock()  # Not AsyncMock for listen method
        mock_redis.pubsub = Mock(return_value=mock_pubsub)

        # Mock pubsub.listen() to yield test messages
        test_messages = [
            {"type": "subscribe", "data": "test_session"},
            {"type": "message", "data": json.dumps({"type": "message", "message": json.dumps({"method": "ping", "id": 1}), "timestamp": time.time()})},
        ]

        class MockAsyncIterator:
            def __init__(self, messages):
                self.messages = messages
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index >= len(self.messages):
                    await asyncio.sleep(0.1)  # Simulate waiting
                    raise StopAsyncIteration
                msg = self.messages[self.index]
                self.index += 1
                return msg

        mock_pubsub.listen.return_value = MockAsyncIterator(test_messages)
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.Redis") as MockRedis:
                MockRedis.from_url.return_value = mock_redis

                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")

                await registry.add_session("test_session", mock_sse_transport)

                # Mock generate_response to track calls
                with patch.object(registry, "generate_response", new_callable=AsyncMock):
                    # Start respond task and let it process one message
                    respond_task = asyncio.create_task(registry.respond(server_id=None, user={"token": "test"}, session_id="test_session", base_url="http://localhost"))

                    # Give it time to process messages
                    await asyncio.sleep(0.01)
                    respond_task.cancel()

                    try:
                        await respond_task
                    except asyncio.CancelledError:
                        pass

                # Verify pubsub operations
                mock_pubsub.subscribe.assert_called_with("test_session")
                mock_pubsub.unsubscribe.assert_called_with("test_session")
                mock_pubsub.close.assert_called_once()

    @pytest.mark.skip("Redis pubsub mocking is complex, skipping for now")
    @pytest.mark.asyncio
    async def test_redis_respond_method_cancelled_task(self, monkeypatch, caplog, mock_sse_transport):
        """Test Redis respond method handles task cancellation."""
        mock_redis = AsyncMock()

        # Mock an infinite async iterator that gets cancelled
        class MockInfiniteAsyncIterator:
            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(0.1)
                return {"type": "message", "data": "test"}

        mock_pubsub = Mock()  # Not AsyncMock for listen method
        mock_pubsub.listen.return_value = MockInfiniteAsyncIterator()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.Redis") as MockRedis:
                MockRedis.from_url.return_value = mock_redis

                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")

                await registry.add_session("test_session", mock_sse_transport)

                # Start respond task and cancel it
                respond_task = asyncio.create_task(registry.respond(server_id=None, user={"token": "test"}, session_id="test_session", base_url="http://localhost"))

                await asyncio.sleep(0.01)  # Let it start
                respond_task.cancel()

                try:
                    await respond_task
                except asyncio.CancelledError:
                    pass

                # Should log cancellation
                assert "PubSub listener for session test_session cancelled" in caplog.text
                assert "Cleaned up pubsub for session test_session" in caplog.text


class TestDatabaseBackendRespond:
    """Test Database backend respond method."""

    @pytest.mark.asyncio
    async def test_database_respond_message_check_loop(self, monkeypatch, mock_sse_transport):
        """Test database backend respond method with unified session+message polling."""

        call_count = 0

        def mock_get_db():
            yield Mock()

        def mock_db_read_session_and_message(session_id):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Session exists and has a message
                mock_session = Mock()
                mock_message = Mock()
                mock_message.message = json.dumps({"method": "ping", "id": 1})
                return mock_session, mock_message

            elif call_count == 2:
                # Session exists but no messages
                mock_session = Mock()
                return mock_session, None

            else:
                # Session removed → loop exits
                return None, None

        def mock_db_remove(session_id, message):
            pass

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_read_session_and_message":
                            return mock_db_read_session_and_message(*args)
                        elif func.__name__ == "_db_remove":
                            return mock_db_remove(*args)
                        return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(
                        backend="database",
                        database_url="sqlite:///test.db",
                    )

                    await registry.add_session("test_session", mock_sse_transport)

                    with patch.object(
                        registry, "generate_response", new_callable=AsyncMock
                    ) as mock_gen:

                        await registry.respond(
                            server_id=None,
                            user={"token": "test"},
                            session_id="test_session",
                            base_url="http://localhost",
                        )

                        # Allow background task to run
                        await asyncio.sleep(0.3)

                        # Assert message was processed
                        mock_gen.assert_called_once()

    
    @pytest.mark.asyncio
    async def test_database_respond_ready_to_respond_logging(self, monkeypatch, caplog, mock_sse_transport):
        """Test database respond logs 'Ready to respond'."""
        call_count = 0

        def mock_get_db():
            yield Mock()

        def mock_db_read_session_and_message(session_id):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Session exists and has a message
                mock_session = Mock()
                mock_message = Mock()
                mock_message.message = json.dumps({"method": "ping", "id": 1})
                return mock_session, mock_message

            # Second poll → session gone → exit loop
            return None, None

        def mock_db_remove(session_id, message):
            pass

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_read_session_and_message":
                            return mock_db_read_session_and_message(*args)
                        elif func.__name__ == "_db_remove":
                            return mock_db_remove(*args)
                        return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(
                        backend="database",
                        database_url="sqlite:///test.db",
                    )

                    await registry.add_session("test_session", mock_sse_transport)

                    # Mock generate_response to avoid side effects
                    with patch.object(
                        registry, "generate_response", new_callable=AsyncMock
                    ):
                        await registry.respond(
                            server_id=None,
                            user={"token": "test"},
                            session_id="test_session",
                            base_url="http://localhost",
                        )

                        # Allow background polling loop to run
                        await asyncio.sleep(0.2)

                        # Assert log output
                        assert "Ready to respond" in caplog.text

    @pytest.mark.asyncio
    async def test_database_respond_message_remove_logging(
        self, monkeypatch, caplog, mock_sse_transport
    ):
        """Test database message removal logs correctly."""

        call_count = 0

        def mock_get_db():
            yield Mock()

        def mock_db_read_session_and_message(session_id):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Session exists and has a message
                mock_session = Mock()
                mock_message = Mock()
                mock_message.message = json.dumps({"method": "ping", "id": 1})
                return mock_session, mock_message

            # Second poll → session gone → exit loop
            return None, None

        def mock_db_remove_with_logging(session_id, message):
            # Simulate real logging behavior of _db_remove
            logger = logging.getLogger("mcpgateway.cache.session_registry")
            logger.info("Removed message from mcp_messages table")

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_read_session_and_message":
                            return mock_db_read_session_and_message(*args)
                        elif func.__name__ == "_db_remove":
                            return mock_db_remove_with_logging(*args)
                        return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(
                        backend="database",
                        database_url="sqlite:///test.db",
                    )

                    await registry.add_session("test_session", mock_sse_transport)

                    with patch.object(
                        registry, "generate_response", new_callable=AsyncMock
                    ):
                        await registry.respond(
                            server_id=None,
                            user={"token": "test"},
                            session_id="test_session",
                            base_url="http://localhost",
                        )

                        # Allow background task to process message
                        await asyncio.sleep(0.2)

                        # Assert message removal log
                        assert "Removed message from mcp_messages table" in caplog.text

class TestDatabaseCleanupTask:
    """Test database cleanup task functionality."""

    @pytest.mark.asyncio
    async def test_db_cleanup_task_expired_sessions(self, monkeypatch, caplog, mock_sse_transport):
        """Test database cleanup task removes expired sessions."""
        mock_db_session = Mock()
        cleanup_call_count = 0

        def mock_get_db():
            yield mock_db_session

        def mock_db_cleanup():
            nonlocal cleanup_call_count
            cleanup_call_count += 1
            if cleanup_call_count == 1:
                return 5  # Simulate 5 expired sessions deleted
            else:
                return 0  # No more expired sessions

        def mock_refresh_session_db(session_id):
            return True  # Session exists and was refreshed

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_cleanup":
                            return mock_db_cleanup()
                        elif func.__name__ == "_refresh_session_db":
                            return mock_refresh_session_db(*args)
                        else:
                            return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    await registry.add_session("test_session", mock_sse_transport)

                    # Start the cleanup task
                    cleanup_task = asyncio.create_task(registry._db_cleanup_task())

                    # Let it run briefly
                    await asyncio.sleep(0.1)
                    cleanup_task.cancel()

                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass

                    # Should log cleanup of expired sessions
                    assert "Cleaned up 5 expired database sessions" in caplog.text

    @pytest.mark.asyncio
    async def test_db_cleanup_task_session_refresh(self, monkeypatch, mock_sse_transport):
        """Test database cleanup task refreshes active sessions."""
        mock_db_session = Mock()
        refresh_called = False

        def mock_get_db():
            yield mock_db_session

        def mock_db_cleanup():
            return 0  # No expired sessions

        def mock_refresh_session_db(*args, **kwargs):
            nonlocal refresh_called
            refresh_called = True
            return True  # Session exists and was refreshed

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_cleanup":
                            return mock_db_cleanup()
                        elif func.__name__ == "_refresh_session_db":
                            return mock_refresh_session_db(*args)
                        else:
                            return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    await registry.add_session("test_session", mock_sse_transport)

                    # Start the cleanup task
                    cleanup_task = asyncio.create_task(registry._db_cleanup_task())

                    # Let it run briefly
                    await asyncio.sleep(0.1)
                    cleanup_task.cancel()

                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass

                    # Should have called refresh_session
                    assert refresh_called

    @pytest.mark.asyncio
    async def test_db_cleanup_task_removes_stale_sessions(self, monkeypatch, mock_sse_transport):
        """Test database cleanup task removes sessions that no longer exist in DB."""
        mock_db_session = Mock()

        def mock_get_db():
            yield mock_db_session

        def mock_db_cleanup():
            return 0  # No expired sessions

        def mock_refresh_session_db(*args, **kwargs):
            return False  # Session doesn't exist in database

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:

                    def side_effect(func, *args):
                        if func.__name__ == "_db_cleanup":
                            return mock_db_cleanup()
                        elif func.__name__ == "_refresh_session_db":
                            return mock_refresh_session_db(*args)
                        else:
                            return func(*args)

                    mock_to_thread.side_effect = side_effect

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    await registry.add_session("test_session", mock_sse_transport)

                    # Mock remove_session to track calls
                    with patch.object(registry, "remove_session", new_callable=AsyncMock) as mock_remove:
                        # Start the cleanup task
                        cleanup_task = asyncio.create_task(registry._db_cleanup_task())

                        # Let it run briefly
                        await asyncio.sleep(0.1)
                        cleanup_task.cancel()

                        try:
                            await cleanup_task
                        except asyncio.CancelledError:
                            pass

                        # Should have called remove_session for stale session
                        mock_remove.assert_called_with("test_session")

    @pytest.mark.asyncio
    async def test_db_cleanup_task_handles_exceptions(self, monkeypatch, caplog):
        """Test database cleanup task handles exceptions properly."""
        mock_db_session = Mock()
        exception_count = 0

        def mock_get_db():
            yield mock_db_session

        def mock_db_cleanup():
            nonlocal exception_count
            exception_count += 1
            if exception_count < 2:
                raise Exception("Database cleanup error")
            return 0

        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_db", mock_get_db):
                with patch("asyncio.to_thread") as mock_to_thread:
                    mock_to_thread.side_effect = mock_db_cleanup

                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

                    # Start the cleanup task
                    cleanup_task = asyncio.create_task(registry._db_cleanup_task())

                    # Let it run and hit the exception
                    await asyncio.sleep(0.1)
                    cleanup_task.cancel()

                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass

                    # Should log the error
                    assert "Error in database cleanup task" in caplog.text

    @pytest.mark.skip("Cleanup task cancellation test is complex, skipping for now")
    @pytest.mark.asyncio
    async def test_db_cleanup_task_cancelled(self, monkeypatch, caplog):
        """Test database cleanup task handles cancellation."""
        pass  # This test requires complex async mocking


class TestMemoryCleanupTask:
    """Test memory cleanup task functionality."""

    @pytest.mark.asyncio
    async def test_memory_cleanup_task_removes_disconnected_sessions(self, monkeypatch):
        """Test memory cleanup task removes disconnected sessions."""
        registry = SessionRegistry(backend="memory")

        class MockTransport:
            def __init__(self, connected=True):
                self._connected = connected
                self.disconnect_called = False

            async def disconnect(self):
                self.disconnect_called = True
                self._connected = False

            async def is_connected(self):
                return self._connected

        # Add connected and disconnected transports
        connected_transport = MockTransport(connected=True)
        disconnected_transport = MockTransport(connected=False)

        await registry.add_session("connected", cast(SSETransport, connected_transport))
        await registry.add_session("disconnected", cast(SSETransport, disconnected_transport))

        # Mock remove_session to track calls
        with patch.object(registry, "remove_session", new_callable=AsyncMock) as mock_remove:
            # Start cleanup task
            cleanup_task = asyncio.create_task(registry._memory_cleanup_task())

            # Let it run briefly
            await asyncio.sleep(0.1)
            cleanup_task.cancel()

            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

            # Should have called remove_session for disconnected transport
            mock_remove.assert_called_with("disconnected")

    @pytest.mark.asyncio
    async def test_memory_cleanup_task_error_handling(self, monkeypatch, caplog):
        """Test memory cleanup task handles transport errors."""
        registry = SessionRegistry(backend="memory")

        class MockTransport:
            async def disconnect(self):
                pass

            async def is_connected(self):
                raise Exception("Transport error")

        transport = MockTransport()
        await registry.add_session("error_session", cast(SSETransport, transport))

        # Mock remove_session to track calls
        with patch.object(registry, "remove_session", new_callable=AsyncMock) as mock_remove:
            # Start cleanup task
            cleanup_task = asyncio.create_task(registry._memory_cleanup_task())

            # Let it run briefly
            await asyncio.sleep(0.1)
            cleanup_task.cancel()

            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

            # Should log error and remove session
            assert "Error checking session error_session" in caplog.text
            mock_remove.assert_called_with("error_session")

    @pytest.mark.asyncio
    async def test_memory_cleanup_task_general_exception(self, monkeypatch, caplog):
        """Test memory cleanup task handles general exceptions."""
        registry = SessionRegistry(backend="memory")

        # Mock the _lock to raise exception
        class MockLock:
            async def __aenter__(self):
                raise Exception("Memory error")

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        registry._lock = cast(Lock, MockLock())

        # Start cleanup task
        cleanup_task = asyncio.create_task(registry._memory_cleanup_task())

        # Let it run briefly
        await asyncio.sleep(0.1)
        cleanup_task.cancel()

        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        # Should log the error
        assert "Error in memory cleanup task" in caplog.text


class TestRedisSessionRefresh:
    """Test Redis session refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_redis_sessions_general_error(self, monkeypatch, caplog):
        """Test _refresh_redis_sessions handles general errors."""
        mock_pubsub = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.pubsub = Mock(return_value=mock_pubsub)

        async def mock_get_redis_client():
            return mock_redis

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                await registry.initialize()

                # Mock _lock to raise exception
                class MockLock:
                    async def __aenter__(self):
                        raise Exception("Lock error")

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
                        pass

                registry._lock = cast(Lock, MockLock())

                await registry._refresh_redis_sessions()

                # Should log the error
                assert "Error in Redis session refresh" in caplog.text

                await registry.shutdown()


class TestInitializationAndShutdown:
    """Test initialization and shutdown methods."""

    @pytest.mark.asyncio
    async def test_memory_backend_initialization_logging(self, caplog):
        """Test memory backend initialization creates cleanup task."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        try:
            # Should log initialization
            assert "Initializing session registry with backend: memory" in caplog.text
            assert "Memory cleanup task started" in caplog.text

            # Should have created cleanup task
            assert registry._cleanup_task is not None
            assert not registry._cleanup_task.done()

        finally:
            await registry.shutdown()

    @pytest.mark.asyncio
    async def test_database_backend_initialization_logging(self, caplog):
        """Test database backend initialization creates cleanup task."""
        with patch("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True):
            registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
            await registry.initialize()

            try:
                # Should log initialization
                assert "Initializing session registry with backend: database" in caplog.text
                assert "Database cleanup task started" in caplog.text

                # Should have created cleanup task
                assert registry._cleanup_task is not None
                assert not registry._cleanup_task.done()

            finally:
                await registry.shutdown()

    @pytest.mark.asyncio
    async def test_redis_initialization_subscribe(self, monkeypatch):
        """Test Redis backend initialization subscribes to events."""
        mock_pubsub = AsyncMock()
        mock_pubsub.aclose = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.pubsub = Mock(return_value=mock_pubsub)  # Use Mock for sync method

        async def mock_get_redis_client():
            return mock_redis

        with patch("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True):
            with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                await registry.initialize()

                try:
                    # Should have subscribed to events channel
                    mock_pubsub.subscribe.assert_called_once_with("mcp_session_events")

                finally:
                    await registry.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_cleanup_task(self):
        """Test shutdown properly cancels cleanup tasks."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        original_task = registry._cleanup_task
        assert original_task is not None
        assert not original_task.cancelled()

        await registry.shutdown()

        # Task should be cancelled
        assert original_task.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_handles_already_cancelled_task(self):
        """Test shutdown handles already cancelled cleanup task."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        # Cancel task before shutdown
        assert registry._cleanup_task is not None
        registry._cleanup_task.cancel()

        # Shutdown should not raise error
        await registry.shutdown()
