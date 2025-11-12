import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time

from mcpgateway.cache.session_pool import (
    PoolKey,
    PooledSession,
    SessionPool,
    TransportType,
)


@pytest.mark.asyncio
class TestSessionPool:
    @pytest.fixture
    def mock_registry(self):
        registry = AsyncMock()
        return registry

    @pytest.fixture
    def mock_transport(self):
        transport = AsyncMock()
        transport.session_id = "sess-123"
        transport.is_connected.return_value = True
        return transport

    def test_poolkey_equality_and_hash(self):
        key1 = PoolKey("user1", "server1", TransportType.SSE)
        key2 = PoolKey("user1", "server1", TransportType.SSE)
        key3 = PoolKey("user2", "server1", TransportType.SSE)
        assert key1 == key2
        assert key1 != key3
        assert hash(key1) == hash(key2)

    def test_pooledsession_age_and_idle_time(self, mock_transport):
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        time.sleep(0.01)
        assert session.age > 0
        assert session.idle_time > 0

    def test_capture_and_restore_state(self, mock_transport):
        mock_transport._intialization_complete = True
        mock_transport._last_activity = 12345
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        session.capture_state()
        assert "intialization_complete" in session.state_snapshot
        mock_transport._intialization_complete = False
        mock_transport._last_activity = 0
        session.restore_state()
        assert mock_transport._intialization_complete is True
        assert mock_transport._last_activity == 12345

@pytest.mark.asyncio
async def test_create_new_session_sse(self, mock_registry):
    # Mock the _registry.add_session since it's awaited
    mock_registry.add_session = AsyncMock()

    # Patch the SSETransport class used in session_pool
    with patch("mcpgateway.cache.session_pool.SSETransport", autospec=True) as mock_sse_cls:
        # Create a mock instance that will be returned by SSETransport()
        mock_instance = MagicMock()
        mock_instance.session_id = "sess-1"
        mock_instance.connect = AsyncMock()  # connect() is awaited in code
        mock_sse_cls.return_value = mock_instance

        pool = SessionPool(mock_registry)
        pool.TRANSPORT_CLASSES[TransportType.SSE] = mock_sse_cls

        # Act: Call method under test
        session = await pool._create_new_session("u1", "s1", "http://x", TransportType.SSE)

        # Assert: Correct behavior
        mock_sse_cls.assert_called_once_with(base_url="http://x", pooled=True, pool_key="u1:s1")
        mock_instance.connect.assert_awaited_once()
        mock_registry.add_session.assert_awaited_once_with("sess-1", mock_instance, pooled=True)
        assert session.transport is mock_instance
        assert session.transport.session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_is_session_valid_true(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        with patch("mcpgateway.cache.session_pool.settings") as mock_settings:
            mock_settings.session_pool_ttl = 9999
            mock_settings.session_pool_max_idle_time = 9999
            result = await pool._is_session_valid(session)
            assert result is True

    @pytest.mark.asyncio
    async def test_is_session_valid_false_due_to_age(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        session.created_at -= 99999
        with patch("mcpgateway.cache.session_pool.settings") as mock_settings:
            mock_settings.session_pool_ttl = 1
            mock_settings.session_pool_max_idle_time = 9999
            result = await pool._is_session_valid(session)
            assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_session_removes_from_pool(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        key = PoolKey("u1", "s1", TransportType.SSE)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        pool._pool[key] = session
        await pool._cleanup_session(key, session)
        assert key not in pool._pool
        mock_registry.remove_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_capture_all_states(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        key = PoolKey("u1", "s1", TransportType.SSE)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        pool._pool[key] = session
        result = await pool.capture_all_states()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_restore_session_state(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        key = PoolKey("u1", "s1", TransportType.SSE)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        pool._pool[key] = session
        state = {"state": {"intialization_complete": True, "last_activity": 123}}
        result = await pool.restore_session_state("sess-123", state)
        assert result is True

    def test_get_pool_stats(self, mock_registry):
        pool = SessionPool(mock_registry)
        stats = pool.get_pool_stats()
        assert "metrics" in stats
        assert "active_sessions" in stats

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up(self, mock_transport, mock_registry):
        pool = SessionPool(mock_registry)
        key = PoolKey("u1", "s1", TransportType.SSE)
        session = PooledSession(mock_transport, "u1", "s1", TransportType.SSE)
        pool._pool[key] = session
        await pool.shutdown()
        assert len(pool._pool) == 0
