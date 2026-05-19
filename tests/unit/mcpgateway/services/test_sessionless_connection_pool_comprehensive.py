# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sessionless_connection_pool_comprehensive.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

Comprehensive unit tests for SessionlessConnectionPool to achieve 95%+ coverage.
Covers all missing lines from the diff-cover report.
"""

# Standard
import asyncio
from contextlib import asynccontextmanager, contextmanager
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import anyio
from mcp import McpError
import pytest

# First-Party
from mcpgateway.services.sessionless_connection_pool import (
    _compute_auth_fingerprint,
    get_sessionless_connection_pool,
    init_sessionless_connection_pool,
    PooledConnection,
    SessionlessConnectionPool,
    SessionlessConnectionPoolNotInitializedError,
    shutdown_sessionless_connection_pool,
)
from mcpgateway.services.upstream_session_registry import TransportType


@pytest.fixture
def mock_client_session():
    """Create a mock MCP ClientSession."""
    session = AsyncMock()
    session.ping = AsyncMock()
    session.list_tools = AsyncMock()
    session.list_prompts = AsyncMock()
    session.list_resources = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    return session


@pytest.fixture
def mock_transport_ctx():
    """Create a mock transport context."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
    ctx.__aexit__ = AsyncMock()
    return ctx


@pytest.fixture
async def pool():
    """Create a SessionlessConnectionPool instance for testing."""
    return SessionlessConnectionPool(
        idle_validation_seconds=5.0,
        health_check_timeout_seconds=2.0,
        session_create_timeout_seconds=10.0,
        shutdown_timeout_seconds=5.0,
    )


class TestPooledConnection:
    """Test PooledConnection dataclass."""

    def test_idle_seconds_property(self):
        """Test idle_seconds property calculation (line 101)."""
        conn = PooledConnection(
            session=MagicMock(),
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )
        # Set last_used to 5 seconds ago
        conn.last_used = time.time() - 5.0

        idle = conn.idle_seconds
        assert 4.9 <= idle <= 5.1  # Allow small timing variance


class TestComputeAuthFingerprint:
    """Test _compute_auth_fingerprint function."""

    def test_no_headers(self):
        """Test with no headers (line 110-111)."""
        result = _compute_auth_fingerprint(None)
        assert result == ""

    def test_empty_headers(self):
        """Test with empty headers dict (line 110-111)."""
        result = _compute_auth_fingerprint({})
        assert result == ""

    def test_no_auth_headers(self):
        """Test with headers but no auth headers (line 120-121)."""
        headers = {"content-type": "application/json", "user-agent": "test"}
        result = _compute_auth_fingerprint(headers)
        assert result == ""

    def test_authorization_header(self):
        """Test with authorization header (line 114-118)."""
        headers = {"authorization": "Bearer token123"}
        result = _compute_auth_fingerprint(headers)

        # Verify it's a 16-char hex string (line 125)
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

        # Verify it's deterministic
        result2 = _compute_auth_fingerprint(headers)
        assert result == result2

    def test_multiple_auth_headers(self):
        """Test with multiple auth headers (line 114-118)."""
        headers = {
            "authorization": "Bearer token123",
            "x-api-key": "key456",
            "x-auth-token": "token789",
        }
        result = _compute_auth_fingerprint(headers)
        assert len(result) == 16

    def test_case_insensitive_matching(self):
        """Test case-insensitive header matching (line 117)."""
        headers1 = {"Authorization": "Bearer token"}
        headers2 = {"authorization": "Bearer token"}

        result1 = _compute_auth_fingerprint(headers1)
        result2 = _compute_auth_fingerprint(headers2)

        assert result1 == result2

    def test_sorted_headers(self):
        """Test that headers are sorted for consistent fingerprints (line 116)."""
        headers1 = {"x-api-key": "key1", "authorization": "Bearer token"}
        headers2 = {"authorization": "Bearer token", "x-api-key": "key1"}

        result1 = _compute_auth_fingerprint(headers1)
        result2 = _compute_auth_fingerprint(headers2)

        assert result1 == result2


class TestSessionlessConnectionPool:
    """Test SessionlessConnectionPool class."""

    @pytest.mark.asyncio
    async def test_get_key_lock_creates_new(self, pool):
        """Test _get_key_lock creates new lock (line 172-175)."""
        key = ("gw1", "http://test.com", "sse", "")

        lock = await pool._get_key_lock(key)
        assert lock is not None
        assert isinstance(lock, asyncio.Lock)
        assert key in pool._key_locks

    @pytest.mark.asyncio
    async def test_get_key_lock_returns_existing(self, pool):
        """Test _get_key_lock returns existing lock (line 172-175)."""
        key = ("gw1", "http://test.com", "sse", "")

        lock1 = await pool._get_key_lock(key)
        lock2 = await pool._get_key_lock(key)

        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_probe_health_skip_method(self, pool, mock_client_session):
        """Test health check with 'skip' method (line 183-186)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock health check chain to only have 'skip'
        with patch("mcpgateway.services.sessionless_connection_pool._HEALTH_CHECK_CHAIN", ["skip"]):
            result = await pool._probe_health(conn)
            assert result is True

    @pytest.mark.asyncio
    async def test_probe_health_mcp_error_fails(self, pool, mock_client_session):
        """Test health check with non-METHOD_NOT_FOUND McpError (line 197-201)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock ping to raise a different McpError
        from mcp.types import ErrorData
        error = McpError(ErrorData(code=-32000, message="Server error"))
        mock_client_session.ping.side_effect = error

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_mcp_error_with_code(self, pool, mock_client_session):
        """Test health check with McpError that has code attribute (line 198-201)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Create error with code attribute
        error = MagicMock(spec=McpError)
        error.code = -32000  # Not METHOD_NOT_FOUND
        mock_client_session.ping.side_effect = error

        with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
            result = await pool._probe_health(conn)
            assert result is False
            # Verify debug log was called (line 200)
            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_probe_health_transport_errors_with_debug(self, pool, mock_client_session):
        """Test health check transport errors log debug message (line 202-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = anyio.EndOfStream()

        with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
            result = await pool._probe_health(conn)
            assert result is False
            # Verify debug log was called (line 203)
            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_probe_health_all_methods_exhausted(self, pool, mock_client_session):
        """Test health check returns False when all methods fail (line 209)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # All methods fail
        mock_client_session.ping.side_effect = OSError()
        mock_client_session.list_tools.side_effect = OSError()
        mock_client_session.list_prompts.side_effect = OSError()
        mock_client_session.list_resources.side_effect = OSError()

        result = await pool._probe_health(conn)
        # Should return False after exhausting all methods (line 209)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_connection_session_exit_error(self, pool, mock_client_session, mock_transport_ctx):
        """Test closing connection when session.__aexit__ raises error (line 219, 221)."""
        mock_client_session.__aexit__.side_effect = Exception("Session close error")
        mock_transport_ctx.__aexit__ = AsyncMock()

        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=mock_transport_ctx,
            is_closed=False,
        )

        with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
            await pool._close_connection(conn)
            # Connection should be marked as closed despite error (line 225)
            assert conn.is_closed is True
            # Debug log should be called (line 223)
            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_probe_health_timeout_error(self, pool, mock_client_session):
        """Test health check with TimeoutError (line 202-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = TimeoutError()

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_os_error(self, pool, mock_client_session):
        """Test health check with OSError (line 202-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = OSError("Connection reset")

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_closed_resource_error(self, pool, mock_client_session):
        """Test health check with ClosedResourceError (line 202-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = anyio.ClosedResourceError()

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_broken_resource_error(self, pool, mock_client_session):
        """Test health check with BrokenResourceError (line 202-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = anyio.BrokenResourceError()

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_generic_exception(self, pool, mock_client_session):
        """Test health check with generic exception (line 205-207)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        mock_client_session.ping.side_effect = ValueError("Unexpected error")

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_health_all_methods_fail(self, pool, mock_client_session):
        """Test health check when all methods fail (line 209)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # All methods raise errors
        mock_client_session.ping.side_effect = OSError()
        mock_client_session.list_tools.side_effect = OSError()
        mock_client_session.list_prompts.side_effect = OSError()
        mock_client_session.list_resources.side_effect = OSError()

        result = await pool._probe_health(conn)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_connection_already_closed(self, pool):
        """Test closing already closed connection (line 213-214)."""
        conn = PooledConnection(
            session=MagicMock(),
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
            is_closed=True,
        )

        await pool._close_connection(conn)
        # Should return early without errors

    @pytest.mark.asyncio
    async def test_close_connection_exception(self, pool, mock_client_session, mock_transport_ctx):
        """Test closing connection with exception (line 216-223, 225)."""
        mock_client_session.__aexit__.side_effect = Exception("Close error")

        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=mock_transport_ctx,
            is_closed=False,
        )

        await pool._close_connection(conn)
        assert conn.is_closed is True

    @pytest.mark.asyncio
    async def test_create_connection_sse(self, pool):
        """Test creating SSE connection (line 237-238, 245-248)."""
        with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
            with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
                # Make fail_after a pass-through context manager (synchronous, not async)
                @contextmanager
                def passthrough_cm(timeout):
                    yield
                mock_fail_after.side_effect = passthrough_cm

                mock_transport = MagicMock()
                mock_read = AsyncMock()
                mock_write = AsyncMock()
                mock_transport.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
                mock_sse.return_value = mock_transport

                with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_cls:
                    mock_session = AsyncMock()
                    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                    mock_session.initialize = AsyncMock()
                    mock_session_cls.return_value = mock_session

                    conn = await pool._create_connection(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers={"authorization": "Bearer token"},
                        transport_type=TransportType.SSE,
                    )

                    assert conn is not None
                    assert conn.url == "http://test.com"
                    assert conn.transport_type == TransportType.SSE
                    assert mock_sse.called

    @pytest.mark.asyncio
    async def test_create_connection_streamable_http(self, pool):
        """Test creating StreamableHTTP connection (line 253-254)."""
        with patch("mcpgateway.services.sessionless_connection_pool.streamablehttp_client") as mock_http:
            with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
                # Make fail_after a pass-through context manager (synchronous, not async)
                @contextmanager
                def passthrough_cm(timeout):
                    yield
                mock_fail_after.side_effect = passthrough_cm

                mock_transport = MagicMock()
                mock_read = AsyncMock()
                mock_write = AsyncMock()
                mock_transport.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
                mock_http.return_value = mock_transport

                with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_cls:
                    mock_session = AsyncMock()
                    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                    mock_session.initialize = AsyncMock()
                    mock_session_cls.return_value = mock_session

                    conn = await pool._create_connection(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.STREAMABLE_HTTP,
                    )

                    assert conn is not None
                    assert conn.transport_type == TransportType.STREAMABLE_HTTP
                    assert mock_http.called

    @pytest.mark.asyncio
    async def test_create_connection_unsupported_transport(self, pool):
        """Test creating connection with unsupported transport (line 260)."""
        # Create a mock transport type that will fail the isinstance check
        class InvalidTransport:
            value = "invalid"

        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(timeout):
                yield
            mock_fail_after.side_effect = passthrough_cm

            with pytest.raises(ValueError, match="Unsupported transport type"):
                await pool._create_connection(
                    gateway_id="gw1",
                    url="http://test.com",
                    headers=None,
                    transport_type=InvalidTransport(),  # type: ignore
                )

    @pytest.mark.asyncio
    async def test_create_connection_timeout(self, pool):
        """Test connection creation timeout (line 246)."""
        with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
            with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
                # Make fail_after raise TimeoutError
                @contextmanager
                def timeout_cm(timeout):
                    raise TimeoutError("Connection timeout")
                    yield  # Never reached
                mock_fail_after.side_effect = timeout_cm

                mock_transport = MagicMock()
                mock_sse.return_value = mock_transport

                with pytest.raises(TimeoutError):
                    await pool._create_connection(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.SSE,
                    )

    @pytest.mark.asyncio
    async def test_acquire_empty_gateway_id(self, pool):
        """Test acquire with empty gateway_id (line 316-318)."""
        with pytest.raises(ValueError, match="gateway_id is required"):
            async with pool.acquire(
                gateway_id="",
                url="http://test.com",
                headers=None,
                transport_type=TransportType.SSE,
            ):
                pass

    @pytest.mark.asyncio
    async def test_acquire_creates_new_connection(self, pool):
        """Test acquire creates new connection when none exists (line 320-322, 324-329)."""
        with patch.object(pool, "_create_connection") as mock_create:
            mock_conn = PooledConnection(
                session=AsyncMock(),
                url="http://test.com",
                transport_type=TransportType.SSE,
                transport_ctx=MagicMock(),
            )
            mock_create.return_value = mock_conn

            async with pool.acquire(
                gateway_id="gw1",
                url="http://test.com",
                headers=None,
                transport_type=TransportType.SSE,
            ) as conn:
                assert conn is mock_conn
                assert pool._creates == 1
                assert pool._reuses == 0

    @pytest.mark.asyncio
    async def test_acquire_reuses_healthy_connection(self, pool):
        """Test acquire reuses healthy connection (line 333-336, 338-339)."""
        # Pre-populate pool with a connection
        mock_conn = PooledConnection(
            session=AsyncMock(),
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )
        mock_conn.last_used = time.time()  # Recently used

        key = ("gw1", "http://test.com", "sse", "")
        pool._connections[key] = mock_conn

        async with pool.acquire(
            gateway_id="gw1",
            url="http://test.com",
            headers=None,
            transport_type=TransportType.SSE,
        ) as conn:
            assert conn is mock_conn
            assert pool._reuses == 1

    @pytest.mark.asyncio
    async def test_acquire_recreates_unhealthy_connection(self, pool):
        """Test acquire recreates unhealthy idle connection (line 333-339)."""
        # Pre-populate pool with an old connection
        mock_old_conn = PooledConnection(
            session=AsyncMock(),
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )
        mock_old_conn.last_used = time.time() - 10.0  # Old enough to trigger health check

        key = ("gw1", "http://test.com", "sse", "")
        pool._connections[key] = mock_old_conn

        # Mock health check to fail
        with patch.object(pool, "_probe_health", return_value=False):
            with patch.object(pool, "_close_connection") as mock_close:
                with patch.object(pool, "_create_connection") as mock_create:
                    mock_new_conn = PooledConnection(
                        session=AsyncMock(),
                        url="http://test.com",
                        transport_type=TransportType.SSE,
                        transport_ctx=MagicMock(),
                    )
                    mock_create.return_value = mock_new_conn

                    async with pool.acquire(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.SSE,
                    ) as conn:
                        assert conn is mock_new_conn
                        assert pool._health_check_recreates == 1
                        assert mock_close.called

    @pytest.mark.asyncio
    async def test_acquire_connection_none_error(self, pool):
        """Test acquire raises error if connection is None (line 353-354)."""
        with patch.object(pool, "_create_connection", return_value=None):
            with pytest.raises(RuntimeError, match="Connection unexpectedly None"):
                async with pool.acquire(
                    gateway_id="gw1",
                    url="http://test.com",
                    headers=None,
                    transport_type=TransportType.SSE,
                ):
                    pass

    @pytest.mark.asyncio
    async def test_acquire_updates_connection_metadata(self, pool):
        """Test acquire updates last_used and use_count (line 356-357)."""
        with patch.object(pool, "_create_connection") as mock_create:
            mock_conn = PooledConnection(
                session=AsyncMock(),
                url="http://test.com",
                transport_type=TransportType.SSE,
                transport_ctx=MagicMock(),
            )
            mock_create.return_value = mock_conn

            initial_time = time.time()
            async with pool.acquire(
                gateway_id="gw1",
                url="http://test.com",
                headers=None,
                transport_type=TransportType.SSE,
            ) as conn:
                assert conn.use_count == 1
                assert conn.last_used >= initial_time

    @pytest.mark.asyncio
    async def test_acquire_handles_os_error(self, pool):
        """Test acquire handles OSError during use (line 362-371)."""
        with patch.object(pool, "_create_connection") as mock_create:
            mock_conn = PooledConnection(
                session=AsyncMock(),
                url="http://test.com",
                transport_type=TransportType.SSE,
                transport_ctx=MagicMock(),
            )
            mock_create.return_value = mock_conn

            with patch.object(pool, "_close_connection") as mock_close:
                with pytest.raises(OSError):
                    async with pool.acquire(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.SSE,
                    ) as conn:
                        raise OSError("Connection error")

                # Verify connection was evicted
                assert mock_close.called

    @pytest.mark.asyncio
    async def test_acquire_handles_closed_resource_error(self, pool):
        """Test acquire handles ClosedResourceError (line 362-371)."""
        with patch.object(pool, "_create_connection") as mock_create:
            mock_conn = PooledConnection(
                session=AsyncMock(),
                url="http://test.com",
                transport_type=TransportType.SSE,
                transport_ctx=MagicMock(),
            )
            mock_create.return_value = mock_conn

            with patch.object(pool, "_close_connection") as mock_close:
                with pytest.raises(anyio.ClosedResourceError):
                    async with pool.acquire(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.SSE,
                    ) as conn:
                        raise anyio.ClosedResourceError()

                assert mock_close.called

    @pytest.mark.asyncio
    async def test_acquire_handles_broken_resource_error(self, pool):
        """Test acquire handles BrokenResourceError (line 362-371)."""
        with patch.object(pool, "_create_connection") as mock_create:
            mock_conn = PooledConnection(
                session=AsyncMock(),
                url="http://test.com",
                transport_type=TransportType.SSE,
                transport_ctx=MagicMock(),
            )
            mock_create.return_value = mock_conn

            with patch.object(pool, "_close_connection") as mock_close:
                with pytest.raises(anyio.BrokenResourceError):
                    async with pool.acquire(
                        gateway_id="gw1",
                        url="http://test.com",
                        headers=None,
                        transport_type=TransportType.SSE,
                    ) as conn:
                        raise anyio.BrokenResourceError()

                assert mock_close.called

    @pytest.mark.asyncio
    async def test_shutdown(self, pool):
        """Test shutdown closes all connections (line 376-380)."""
        # Add some connections
        conn1 = PooledConnection(
            session=AsyncMock(),
            url="http://test1.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )
        conn2 = PooledConnection(
            session=AsyncMock(),
            url="http://test2.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        pool._connections[("gw1", "http://test1.com", "sse", "")] = conn1
        pool._connections[("gw2", "http://test2.com", "sse", "")] = conn2

        with patch.object(pool, "_close_connection") as mock_close:
            await pool.shutdown()

            assert mock_close.call_count == 2
            assert len(pool._connections) == 0
            assert len(pool._key_locks) == 0

    def test_get_metrics(self, pool):
        """Test get_metrics returns correct metrics (line 382-389)."""
        pool._creates = 5
        pool._reuses = 10
        pool._health_check_recreates = 2
        pool._connections = {("gw1", "url", "sse", ""): MagicMock()}

        metrics = pool.get_metrics()

        assert metrics["creates"] == 5
        assert metrics["reuses"] == 10
        assert metrics["health_check_recreates"] == 2
        assert metrics["active_connections"] == 1


class TestSingletonFunctions:
    """Test singleton management functions."""

    @pytest.mark.asyncio
    async def test_init_sessionless_connection_pool(self):
        """Test init_sessionless_connection_pool creates singleton."""
        # Reset singleton
        import mcpgateway.services.sessionless_connection_pool as pool_module
        pool_module._sessionless_pool = None

        pool = await init_sessionless_connection_pool()
        assert pool is not None
        assert isinstance(pool, SessionlessConnectionPool)

        # Second call returns same instance
        pool2 = await init_sessionless_connection_pool()
        assert pool2 is pool

        # Cleanup
        await shutdown_sessionless_connection_pool()

    def test_get_sessionless_connection_pool_not_initialized(self):
        """Test get_sessionless_connection_pool raises error when not initialized (line 428)."""
        # Reset singleton
        import mcpgateway.services.sessionless_connection_pool as pool_module
        pool_module._sessionless_pool = None

        with pytest.raises(SessionlessConnectionPoolNotInitializedError):
            get_sessionless_connection_pool()

    @pytest.mark.asyncio
    async def test_get_sessionless_connection_pool_success(self):
        """Test get_sessionless_connection_pool returns initialized pool."""
        # Initialize pool
        pool = await init_sessionless_connection_pool()

        # Get pool
        retrieved = get_sessionless_connection_pool()
        assert retrieved is pool

        # Cleanup
        await shutdown_sessionless_connection_pool()

    @pytest.mark.asyncio
    async def test_shutdown_sessionless_connection_pool(self):
        """Test shutdown_sessionless_connection_pool cleans up singleton."""
        # Initialize pool
        await init_sessionless_connection_pool()

        # Shutdown
        await shutdown_sessionless_connection_pool()

        # Verify singleton is cleared
        import mcpgateway.services.sessionless_connection_pool as pool_module
        assert pool_module._sessionless_pool is None

    @pytest.mark.asyncio
    async def test_shutdown_when_not_initialized(self):
        """Test shutdown when pool not initialized."""
        # Reset singleton
        import mcpgateway.services.sessionless_connection_pool as pool_module
        pool_module._sessionless_pool = None

        # Should not raise error
        await shutdown_sessionless_connection_pool()
