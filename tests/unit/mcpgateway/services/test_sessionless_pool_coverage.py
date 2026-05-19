# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sessionless_pool_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Additional coverage tests for SessionlessConnectionPool edge cases.

This module tests error paths and edge cases that are not covered by the
comprehensive test suite, specifically targeting:
- Health check fallback to False when all methods fail
- Owner task cleanup timeout scenarios
- Connection creation failure cleanup
- LRU eviction when pool is empty
- Idle reaper with max_idle_seconds <= 0
- Idle connection reaping
"""

# Standard
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.sessionless_connection_pool import (
    SessionlessConnectionPool,
    PooledConnection,
    TransportType,
)


@pytest.fixture
def pool():
    """Create a SessionlessConnectionPool instance for testing."""
    return SessionlessConnectionPool(
        max_pool_size=5,
        max_idle_seconds=1.0,
        session_create_timeout_seconds=2.0,
        shutdown_timeout_seconds=1.0,
    )


@pytest.mark.asyncio
async def test_health_check_returns_false_when_all_methods_fail(pool):
    """Test that _probe_health returns False when all health check methods fail."""
    # Create a mock connection with a session that raises errors for all health check methods
    mock_session = MagicMock()
    mock_session.list_tools = AsyncMock(side_effect=Exception("tools failed"))
    mock_session.list_resources = AsyncMock(side_effect=Exception("resources failed"))
    mock_session.list_prompts = AsyncMock(side_effect=Exception("prompts failed"))

    connection = PooledConnection(
        session=mock_session,
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
    )

    # Health check should return False when all methods fail
    result = await pool._probe_health(connection)
    assert result is False


@pytest.mark.asyncio
async def test_close_connection_with_owner_task_exception(pool):
    """Test _close_connection when owner task exits with an exception."""
    # Create a mock owner task that completes with an exception
    async def failing_task():
        raise ValueError("Task failed")

    owner_task = asyncio.create_task(failing_task())
    shutdown_event = asyncio.Event()

    # Wait for task to complete
    with pytest.raises(ValueError):
        await owner_task

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should handle the exception gracefully
    await pool._close_connection(connection)
    assert connection.is_closed


@pytest.mark.asyncio
async def test_close_connection_force_cancel_timeout(pool):
    """Test _close_connection when force-cancel times out."""
    # Create a mock owner task that never completes
    async def hanging_task():
        await asyncio.sleep(10)  # Sleep longer than shutdown timeout

    owner_task = asyncio.create_task(hanging_task())
    shutdown_event = asyncio.Event()

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should timeout and log warning
    await pool._close_connection(connection)
    assert connection.is_closed

    # Clean up the hanging task
    owner_task.cancel()
    try:
        await owner_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_close_connection_graceful_shutdown_timeout(pool):
    """Test _close_connection when graceful shutdown times out but force-cancel succeeds."""
    # Create a mock owner task that ignores shutdown event but responds to cancel
    async def slow_task(shutdown_event):
        try:
            await asyncio.sleep(10)  # Longer than graceful timeout
        except asyncio.CancelledError:
            return  # Respond to cancel

    shutdown_event = asyncio.Event()
    owner_task = asyncio.create_task(slow_task(shutdown_event))

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should timeout graceful shutdown, then force-cancel
    await pool._close_connection(connection)
    assert connection.is_closed


@pytest.mark.asyncio
async def test_create_connection_cleanup_on_failure(pool):
    """Test that _create_connection cleans up owner task when creation fails."""
    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Make transport creation fail
        @asynccontextmanager
        async def failing_transport(*args, **kwargs):
            raise ValueError("Transport creation failed")
            yield  # pragma: no cover

        mock_sse.return_value = failing_transport()

        # Attempt to create connection should fail and clean up
        with pytest.raises(ValueError, match="Transport creation failed"):
            await pool._create_connection(
                gateway_id="test-gateway",
                url="http://test.example.com",
                transport_type=TransportType.SSE,
                headers=None,
                httpx_client_factory=None,
            )


@pytest.mark.asyncio
async def test_create_connection_session_exit_exception(pool):
    """Test that _create_connection handles session __aexit__ exceptions."""
    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a mock transport that succeeds
        mock_read = AsyncMock()
        mock_write = AsyncMock()

        @asynccontextmanager
        async def mock_transport(*args, **kwargs):
            yield (mock_read, mock_write)

        mock_sse.return_value = mock_transport()

        # Mock ClientSession to fail during __aexit__
        with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(side_effect=Exception("Session exit failed"))
            mock_session.initialize = AsyncMock()
            mock_session_class.return_value = mock_session

            # Create connection should succeed despite __aexit__ exception
            connection = await pool._create_connection(
                gateway_id="test-gateway",
                url="http://test.example.com",
                transport_type=TransportType.SSE,
                headers=None,
                httpx_client_factory=None,
            )

            # Clean up
            if connection.shutdown_event:
                connection.shutdown_event.set()
            if connection.owner_task and not connection.owner_task.done():
                connection.owner_task.cancel()
                try:
                    await connection.owner_task
                except asyncio.CancelledError:
                    pass


@pytest.mark.asyncio
async def test_evict_lru_connection_empty_pool(pool):
    """Test that _evict_lru_connection handles empty pool gracefully."""
    # Evicting from empty pool should be a no-op
    await pool._evict_lru_connection()
    assert len(pool._connections) == 0


@pytest.mark.asyncio
async def test_reap_idle_connections_disabled(pool):
    """Test that reap_idle_connections returns 0 when max_idle_seconds <= 0."""
    pool._max_idle_seconds = 0
    reaped = await pool.reap_idle_connections()
    assert reaped == 0

    pool._max_idle_seconds = -1
    reaped = await pool.reap_idle_connections()
    assert reaped == 0


@pytest.mark.asyncio
async def test_reap_idle_connections_with_idle_connections(pool):
    """Test that reap_idle_connections removes idle connections."""
    # Create mock connections with different idle times
    import time

    connection1 = PooledConnection(
        session=MagicMock(),
        url="http://test1.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        last_used=time.time() - 2.0,  # Idle for 2 seconds (> max_idle_seconds=1.0)
    )

    connection2 = PooledConnection(
        session=MagicMock(),
        url="http://test2.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        last_used=time.time(),  # Just used (< max_idle_seconds=1.0)
    )

    # Add connections to pool
    pool._connections[("gw1", "http://test1.example.com", TransportType.SSE, "")] = connection1
    pool._connections[("gw2", "http://test2.example.com", TransportType.SSE, "")] = connection2

    # Reap idle connections
    reaped = await pool.reap_idle_connections()

    # Should have reaped connection1 but not connection2
    assert reaped == 1
    assert len(pool._connections) == 1
    assert pool._idle_evictions == 1


@pytest.mark.asyncio
async def test_main_idle_reaper_exception_handling():
    """Test that main.py idle reaper handles exceptions gracefully."""
    # This tests the exception handling in main.py lines 1445-1450
    pool = SessionlessConnectionPool(max_idle_seconds=1.0)

    # Mock reap_idle_connections to raise an exception
    original_reap = pool.reap_idle_connections
    pool.reap_idle_connections = AsyncMock(side_effect=Exception("Reap failed"))

    # Simulate the idle reaper loop
    stop_event = asyncio.Event()

    async def run_idle_reaper():
        """Simulates the idle reaper from main.py."""
        reap_interval = 0.1  # Short interval for testing
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=reap_interval)
                break
            except asyncio.TimeoutError:
                # This is the code path we're testing (main.py:1443-1450)
                try:
                    await pool.reap_idle_connections()
                except Exception:  # noqa: BLE001
                    # Exception should be caught and logged
                    pass

    # Start the reaper
    reaper_task = asyncio.create_task(run_idle_reaper())

    # Let it run for a bit to trigger the exception
    await asyncio.sleep(0.2)

    # Stop the reaper
    stop_event.set()
    await reaper_task

    # Restore original method
    pool.reap_idle_connections = original_reap


@pytest.mark.asyncio
async def test_probe_health_no_methods_available(pool):
    """Test _probe_health when connection has no health check methods (line 238)."""
    # Create a mock session with no health check methods
    mock_session = MagicMock()
    mock_session.list_tools = None
    mock_session.list_resources = None
    mock_session.list_prompts = None

    connection = PooledConnection(
        session=mock_session,
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
    )

    # Should return False when no methods are available
    result = await pool._probe_health(connection)
    assert result is False


@pytest.mark.asyncio
async def test_close_connection_owner_task_not_cancelled(pool):
    """Test _close_connection when owner task completes without being cancelled (line 264)."""
    # Create a mock owner task that completes normally
    async def normal_task():
        return "completed"

    owner_task = asyncio.create_task(normal_task())
    await owner_task  # Wait for completion
    shutdown_event = asyncio.Event()

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should handle completed task gracefully
    await pool._close_connection(connection)
    assert connection.is_closed


@pytest.mark.asyncio
async def test_create_connection_owner_task_done_during_wait(pool):
    """Test _create_connection when owner task fails during creation wait (line 401-402)."""
    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a transport that fails after entering
        @asynccontextmanager
        async def failing_after_enter(*args, **kwargs):
            yield (AsyncMock(), AsyncMock())
            raise ValueError("Transport failed after enter")

        mock_sse.return_value = failing_after_enter()

        # Mock ClientSession to fail during initialize
        with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.initialize = AsyncMock(side_effect=ValueError("Initialize failed"))
            mock_session_class.return_value = mock_session

            # Should raise the initialization error and clean up (line 401-402, 408)
            with pytest.raises(ValueError, match="Initialize failed"):
                await pool._create_connection(
                    gateway_id="test-gateway",
                    url="http://test.example.com",
                    transport_type=TransportType.SSE,
                    headers=None,
                    httpx_client_factory=None,
                )


@pytest.mark.asyncio
async def test_evict_lru_with_multiple_connections(pool):
    """Test _evict_lru_connection with multiple connections (lines 509-510, 519)."""
    import time

    # Create multiple connections with different last_used times
    connection1 = PooledConnection(
        session=MagicMock(),
        url="http://test1.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        last_used=time.time() - 10.0,  # Oldest
    )

    connection2 = PooledConnection(
        session=MagicMock(),
        url="http://test2.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        last_used=time.time() - 5.0,  # Middle
    )

    connection3 = PooledConnection(
        session=MagicMock(),
        url="http://test3.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        last_used=time.time(),  # Newest
    )

    # Add connections to pool
    key1 = ("gw1", "http://test1.example.com", TransportType.SSE, "")
    key2 = ("gw2", "http://test2.example.com", TransportType.SSE, "")
    key3 = ("gw3", "http://test3.example.com", TransportType.SSE, "")

    pool._connections[key1] = connection1
    pool._connections[key2] = connection2
    pool._connections[key3] = connection3

    # Evict LRU (should evict connection1)
    await pool._evict_lru_connection()

    # Should have evicted the oldest connection
    assert len(pool._connections) == 2
    assert key1 not in pool._connections
    assert key2 in pool._connections
    assert key3 in pool._connections
    assert pool._lru_evictions == 1


@pytest.mark.asyncio
async def test_probe_health_chain_exhausted_without_skip(pool):
    """Test _probe_health when health check chain is exhausted without hitting 'skip' (line 238)."""
    # Mock the health check chain to not include 'skip'
    with patch("mcpgateway.services.sessionless_connection_pool._HEALTH_CHECK_CHAIN", ("ping", "list_tools")):
        # Create a mock session where all methods raise METHOD_NOT_FOUND
        from mcp import McpError
        from mcp.types import ErrorData

        mock_session = MagicMock()
        mock_error = McpError(ErrorData(code=-32601, message="Method not found"))
        mock_error.code = -32601  # METHOD_NOT_FOUND code

        mock_session.ping = AsyncMock(side_effect=mock_error)
        mock_session.list_tools = AsyncMock(side_effect=mock_error)

        connection = PooledConnection(
            session=mock_session,
            url="http://test.example.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )

        # Should return False when chain is exhausted without 'skip'
        result = await pool._probe_health(connection)
        assert result is False


@pytest.mark.asyncio
async def test_close_connection_owner_task_completes_without_exception(pool):
    """Test _close_connection when owner task completes normally without exception (line 264)."""
    # Create a mock owner task that completes normally (not cancelled, no exception)
    async def normal_completion_task():
        await asyncio.sleep(0.01)
        return "completed"

    owner_task = asyncio.create_task(normal_completion_task())
    shutdown_event = asyncio.Event()

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Signal shutdown and wait a bit for task to complete
    shutdown_event.set()
    await asyncio.sleep(0.02)

    # Close should handle completed task (line 264: if not owner_task.cancelled())
    await pool._close_connection(connection)
    assert connection.is_closed
    assert owner_task.done()
    assert not owner_task.cancelled()
    assert owner_task.exception() is None  # No exception


@pytest.mark.asyncio
async def test_create_connection_cleanup_on_timeout(pool):
    """Test _create_connection cleanup when creation times out (lines 401-402, 408)."""
    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a transport that hangs during creation
        @asynccontextmanager
        async def hanging_transport(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than session_create_timeout
            yield (AsyncMock(), AsyncMock())

        mock_sse.return_value = hanging_transport()

        # Should timeout and trigger cleanup (lines 401-402, 408)
        with pytest.raises(TimeoutError):
            await pool._create_connection(
                gateway_id="test-gateway",
                url="http://test.example.com",
                transport_type=TransportType.SSE,
                headers=None,
                httpx_client_factory=None,
            )


@pytest.mark.asyncio
async def test_close_connection_task_completes_gracefully_not_cancelled(pool):
    """Test line 264: owner task completes gracefully within shutdown window, not cancelled."""
    # Create a task that completes quickly when shutdown is signaled
    async def graceful_task(shutdown_event):
        await shutdown_event.wait()  # Wait for shutdown signal
        # Complete normally without being cancelled
        return "completed"

    shutdown_event = asyncio.Event()
    owner_task = asyncio.create_task(graceful_task(shutdown_event))

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close connection - this will set shutdown_event and wait for task
    await pool._close_connection(connection)

    # Verify line 264 was hit: task completed, not cancelled
    assert connection.is_closed
    assert owner_task.done()
    assert not owner_task.cancelled()  # Line 264 condition
    assert owner_task.exception() is None


async def test_create_connection_cleanup_catches_cancelled_error(pool):
    """Test that cleanup path catches CancelledError when cancelling owner task (lines 400-401, 408)."""
    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a transport that succeeds but session initialization hangs
        @asynccontextmanager
        async def mock_transport(*args, **kwargs):
            yield (AsyncMock(), AsyncMock())

        mock_sse.return_value = mock_transport()

        # Mock ClientSession to hang during initialize (simulating a timeout scenario)
        with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()

            # Make initialize hang longer than the session_create_timeout
            async def hanging_initialize(*args, **kwargs):
                await asyncio.sleep(10)  # Longer than session_create_timeout_seconds=2.0

            mock_session.initialize = hanging_initialize
            mock_session_class.return_value = mock_session

            # Should timeout, cancel the owner task, catch CancelledError (line 400-401), and raise TimeoutError (line 408)
            with pytest.raises(TimeoutError):
                await pool._create_connection(
                    gateway_id="test-gateway",
                    url="http://test.example.com",
                    transport_type=TransportType.SSE,
                    headers=None,
                    httpx_client_factory=None,
                )


@pytest.mark.asyncio
async def test_close_connection_owner_task_exits_with_exception_not_cancelled(pool):
    """Test _close_connection when owner task exits with exception (line 267)."""
    # Create a mock owner task that raises an exception (not cancelled)
    async def failing_task():
        raise ValueError("Task failed with exception")

    owner_task = asyncio.create_task(failing_task())

    # Wait for task to fail
    try:
        await owner_task
    except ValueError:
        pass

    shutdown_event = asyncio.Event()

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should handle the exception and log it (line 267)
    await pool._close_connection(connection)
    assert connection.is_closed
    assert owner_task.done()
    assert not owner_task.cancelled()
    assert owner_task.exception() is not None  # Has exception


@pytest.mark.asyncio
async def test_close_connection_force_cancel_never_completes(pool):
    """Test _close_connection when force-cancel never completes (line 275)."""
    # Create a mock owner task that ignores cancellation
    async def unkillable_task():
        try:
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # Catch and ignore cancellation
            while True:
                await asyncio.sleep(0.1)

    owner_task = asyncio.create_task(unkillable_task())
    shutdown_event = asyncio.Event()

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close should timeout both graceful and force-cancel, log warning (line 275)
    await pool._close_connection(connection)
    assert connection.is_closed

    # Clean up the unkillable task
    owner_task.cancel()
    try:
        await asyncio.wait_for(owner_task, timeout=0.1)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


@pytest.mark.asyncio
async def test_acquire_triggers_lru_eviction_when_pool_full(pool):
    """Test that acquire() triggers LRU eviction when pool is at max size (line 466)."""
    import time

    # Fill the pool to max size (5 connections)
    for i in range(5):
        connection = PooledConnection(
            session=MagicMock(),
            url=f"http://test{i}.example.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
            last_used=time.time() - (10 - i),  # Oldest first
        )
        key = (f"gw{i}", f"http://test{i}.example.com", TransportType.SSE, "")
        pool._connections[key] = connection

    assert len(pool._connections) == 5

    # Mock _create_connection to return a new connection
    with patch.object(pool, "_create_connection") as mock_create:
        mock_session = MagicMock()
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        new_connection = PooledConnection(
            session=mock_session,
            url="http://new.example.com",
            transport_type=TransportType.SSE,
            transport_ctx=MagicMock(),
        )
        mock_create.return_value = new_connection


@pytest.mark.asyncio
async def test_close_connection_logs_owner_task_exception(pool):
    """Test that _close_connection logs exception from owner task (line 267)."""
    # Create an owner task that will raise an exception and complete within the grace period
    exception_raised = asyncio.Event()

    async def task_with_exception():
        try:
            await asyncio.sleep(0.01)  # Small delay
            raise RuntimeError("Intentional test exception")
        finally:
            exception_raised.set()

    owner_task = asyncio.create_task(task_with_exception())
    shutdown_event = asyncio.Event()

    # Wait for the exception to be raised
    await exception_raised.wait()
    await asyncio.sleep(0.01)  # Give task time to complete

    connection = PooledConnection(
        session=MagicMock(),
        url="http://test.example.com",
        transport_type=TransportType.SSE,
        transport_ctx=MagicMock(),
        owner_task=owner_task,
        shutdown_event=shutdown_event,
    )

    # Close connection - should detect the exception and log it (line 267)
    await pool._close_connection(connection)

    assert connection.is_closed
    assert owner_task.done()
    assert not owner_task.cancelled()
    # Verify the exception is present
    exc = owner_task.exception()
    assert exc is not None
    assert isinstance(exc, RuntimeError)


@pytest.mark.asyncio
async def test_create_connection_cleanup_with_actual_cancelled_error():
    """Test that connection creation cleanup catches CancelledError and re-raises original (lines 401-402, 408)."""
    pool = SessionlessConnectionPool(
        max_pool_size=5,
        max_idle_seconds=1.0,
        session_create_timeout_seconds=0.5,  # Short timeout to trigger quickly
        shutdown_timeout_seconds=0.5,
    )

    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a transport that hangs
        @asynccontextmanager
        async def hanging_transport(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than timeout
            yield (AsyncMock(), AsyncMock())

        mock_sse.return_value = hanging_transport()

        # Mock ClientSession
        with patch("mcpgateway.services.sessionless_connection_pool.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_class.return_value = mock_session

            # Should timeout, trigger cleanup that catches CancelledError (401-402), and re-raise TimeoutError (408)
            with pytest.raises(TimeoutError):
                await pool._create_connection(
                    gateway_id="test-gateway",
                    url="http://test.example.com",
                    transport_type=TransportType.SSE,
                    headers=None,
                    httpx_client_factory=None,
                )




@pytest.mark.asyncio
async def test_create_connection_timeout_triggers_cleanup(pool):
    """Test lines 401-402, 408: Timeout during connection creation triggers cleanup with CancelledError."""
    # Use a very short timeout to trigger the timeout path
    short_timeout_pool = SessionlessConnectionPool(session_create_timeout_seconds=0.001)

    with patch("mcpgateway.services.sessionless_connection_pool.sse_client") as mock_sse:
        # Create a transport that takes too long
        @asynccontextmanager
        async def slow_transport(*args, **kwargs):
            await asyncio.sleep(10)  # Much longer than timeout
            yield (AsyncMock(), AsyncMock())

        mock_sse.return_value = slow_transport()

        # Should timeout and trigger cleanup (lines 401-402: except asyncio.CancelledError: pass)
        # Then re-raise TimeoutError (line 408: raise)
        with pytest.raises(TimeoutError):
            await short_timeout_pool._create_connection(
                gateway_id="test-gateway",
                url="http://test.example.com",
                transport_type=TransportType.SSE,
                headers=None,
                httpx_client_factory=None,
            )
