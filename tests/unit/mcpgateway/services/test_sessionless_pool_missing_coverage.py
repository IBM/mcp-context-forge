# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sessionless_pool_missing_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

Unit tests to cover missing lines in SessionlessConnectionPool.
Targets lines: 191, 194-196, 198-201, 203-204, 209, 219, 221
"""

# Standard
from contextlib import asynccontextmanager, contextmanager
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import anyio
from mcp import McpError
from mcp.types import ErrorData
import pytest

# First-Party
from mcpgateway.services.sessionless_connection_pool import (
    PooledConnection,
    SessionlessConnectionPool,
)
from mcpgateway.services.upstream_session_registry import TransportType


@pytest.fixture
async def pool():
    """Create a SessionlessConnectionPool instance for testing."""
    return SessionlessConnectionPool(
        idle_validation_seconds=5.0,
        health_check_timeout_seconds=2.0,
        session_create_timeout_seconds=10.0,
        shutdown_timeout_seconds=5.0,
    )


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


class TestHealthCheckMissingLines:
    """Tests to cover missing lines in _probe_health method."""

    @pytest.mark.asyncio
    async def test_health_check_method_none_continues(self, pool, mock_client_session):
        """Test health check continues when method is None (line 191)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Remove ping method so getattr returns None
        delattr(mock_client_session, "ping")

        # Mock list_tools to succeed (so we don't hit line 209)
        mock_client_session.list_tools = AsyncMock()

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            result = await pool._probe_health(conn)
            # Should continue to next method and succeed with list_tools
            assert result is True
            assert mock_client_session.list_tools.called

    @pytest.mark.asyncio
    async def test_health_check_success_path(self, pool, mock_client_session):
        """Test successful health check path (lines 194-196)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock ping to succeed
        mock_client_session.ping = AsyncMock()

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
                result = await pool._probe_health(conn)
                assert result is True
                # Verify success debug log was called (line 195)
                mock_logger.debug.assert_called_with("Health check succeeded via %s", "ping")

    @pytest.mark.asyncio
    async def test_health_check_mcp_error_method_not_found_continues(self, pool):
        """Test McpError with METHOD_NOT_FOUND continues to next method (lines 198-199)."""
        # Create a fresh mock session for this test
        mock_session = AsyncMock()

        # Create actual McpError with METHOD_NOT_FOUND code
        error = McpError(ErrorData(code=-32601, message="Method not found"))
        # Add code attribute directly to the exception instance for getattr check
        error.code = -32601
        mock_session.ping = AsyncMock(side_effect=error)

        # Make list_tools also raise METHOD_NOT_FOUND to test continue behavior
        error2 = McpError(ErrorData(code=-32601, message="Method not found"))
        error2.code = -32601
        mock_session.list_tools = AsyncMock(side_effect=error2)

        # Make list_prompts succeed (AsyncMock succeeds by default)
        mock_session.list_prompts = AsyncMock()

        conn = PooledConnection(
            session=mock_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            result = await pool._probe_health(conn)
            # Should continue through ping and list_tools (both METHOD_NOT_FOUND) and succeed with list_prompts
            assert result is True
            # Verify methods were called in order (proving line 199 continue was executed)
            assert mock_session.ping.called
            assert mock_session.list_tools.called
            assert mock_session.list_prompts.called

    @pytest.mark.asyncio
    async def test_health_check_mcp_error_other_code_fails(self, pool, mock_client_session):
        """Test McpError with non-METHOD_NOT_FOUND code returns False (lines 198, 200-201)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock ping to raise a different McpError
        error = McpError(ErrorData(code=-32000, message="Server error"))
        mock_client_session.ping.side_effect = error

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
                result = await pool._probe_health(conn)
                assert result is False
                # Verify debug log was called (line 200)
                mock_logger.debug.assert_called_with("Health check failed via %s: %s", "ping", error)

    @pytest.mark.asyncio
    async def test_health_check_transport_error_logs_debug(self, pool, mock_client_session):
        """Test transport errors log debug message (lines 203-204)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock ping to raise transport error
        mock_client_session.ping.side_effect = anyio.EndOfStream()

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
                result = await pool._probe_health(conn)
                assert result is False
                # Verify debug log was called (line 203)
                mock_logger.debug.assert_called_with("Health check failed via %s (transport error)", "ping")

    @pytest.mark.asyncio
    async def test_health_check_all_methods_fail_returns_false(self, pool, mock_client_session):
        """Test health check returns False when all methods fail (line 209)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Mock all methods to raise METHOD_NOT_FOUND (so they all continue)
        method_not_found = McpError(ErrorData(code=-32601, message="Method not found"))
        mock_client_session.ping.side_effect = method_not_found
        mock_client_session.list_tools.side_effect = method_not_found
        mock_client_session.list_prompts.side_effect = method_not_found
        mock_client_session.list_resources.side_effect = method_not_found

        result = await pool._probe_health(conn)
        # All methods exhausted, should return False (line 209)
        assert result is False


class TestCloseConnectionMissingLines:
    """Tests to cover missing lines in _close_connection method."""

    @pytest.mark.asyncio
    async def test_close_connection_success(self, pool, mock_client_session, mock_transport_ctx):
        """Test successful connection close (lines 219, 221)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=mock_transport_ctx,
        )

        # Ensure connection is not already closed
        conn.is_closed = False

        # Patch anyio.fail_after to be a pass-through context manager
        with patch("mcpgateway.services.sessionless_connection_pool.anyio.fail_after") as mock_fail_after:
            @contextmanager
            def passthrough_cm(*args, **kwargs):
                yield
            mock_fail_after.side_effect = passthrough_cm

            await pool._close_connection(conn)

            # Verify both __aexit__ methods were called (lines 219, 221)
            mock_client_session.__aexit__.assert_awaited_once_with(None, None, None)
            mock_transport_ctx.__aexit__.assert_awaited_once_with(None, None, None)

            # Verify connection is marked as closed
            assert conn.is_closed is True

    @pytest.mark.asyncio
    async def test_close_connection_already_closed(self, pool, mock_client_session, mock_transport_ctx):
        """Test close connection when already closed (early return)."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=mock_transport_ctx,
        )

        # Mark connection as already closed
        conn.is_closed = True

        await pool._close_connection(conn)

        # Verify __aexit__ methods were NOT called (early return at line 214)
        mock_client_session.__aexit__.assert_not_awaited()
        mock_transport_ctx.__aexit__.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_connection_with_exception(self, pool, mock_client_session, mock_transport_ctx):
        """Test close connection handles exceptions gracefully."""
        conn = PooledConnection(
            session=mock_client_session,
            url="http://test.com",
            transport_type=TransportType.SSE,
            transport_ctx=mock_transport_ctx,
        )

        conn.is_closed = False

        # Mock session __aexit__ to raise an exception
        mock_client_session.__aexit__.side_effect = RuntimeError("Close failed")

        with patch("mcpgateway.services.sessionless_connection_pool.logger") as mock_logger:
            await pool._close_connection(conn)

            # Verify exception was logged (line 223)
            mock_logger.debug.assert_called()

            # Verify connection is still marked as closed (finally block, line 225)
            assert conn.is_closed is True
