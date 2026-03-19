# -*- coding: utf-8 -*-
"""Tests for the MCP session pool cancel scope fix (#3737).

Covers:
- Background owner task lifecycle (creation, failure, shutdown)
- Transport-aware is_closed detection
- release() behavior with dead owner tasks
- _create_session() cleanup on CancelledError
- Health check anyio.fail_after integration

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_session_pool import MCPSessionPool, PooledSession, TransportType


class TestOwnerTaskLifecycle:
    """Tests for the background owner task lifecycle."""

    @pytest.mark.asyncio
    async def test_create_session_sets_owner_task_and_shutdown_event(self):
        """Created sessions should have an owner task and shutdown event."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                pooled = await pool._create_session("http://test:8080", None, TransportType.SSE, None)

        assert pooled.owner_task is not None
        assert pooled.shutdown_event is not None
        assert not pooled.owner_task.done()
        await pool._close_session(pooled)

    @pytest.mark.asyncio
    async def test_is_closed_detects_dead_owner_task(self):
        """is_closed should return True when the owner task has finished."""
        done_task = asyncio.get_event_loop().create_future()
        done_task.set_result(None)  # Mark as done

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=asyncio.ensure_future(done_task),
        )
        # Allow the task to complete
        await asyncio.sleep(0)
        assert pooled.is_closed is True

    @pytest.mark.asyncio
    async def test_is_closed_false_when_owner_task_alive(self):
        """is_closed should return False when the owner task is still running."""
        event = asyncio.Event()

        async def wait_forever():
            await event.wait()

        task = asyncio.create_task(wait_forever())

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=task,
        )
        assert pooled.is_closed is False
        event.set()
        await task

    @pytest.mark.asyncio
    async def test_close_session_signals_shutdown_event(self):
        """_close_session should set the shutdown event to signal the owner task."""
        shutdown = asyncio.Event()
        task_done = asyncio.Event()

        async def owner_coro():
            await shutdown.wait()
            task_done.set()

        task = asyncio.create_task(owner_coro())

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=task,
            _shutdown_event=shutdown,
        )

        pool = MCPSessionPool()
        await pool._close_session(pooled)
        assert shutdown.is_set()
        assert task.done()

    @pytest.mark.asyncio
    async def test_close_session_force_cancels_on_timeout(self):
        """_close_session should force-cancel the owner task if it doesn't exit in time."""
        shutdown = asyncio.Event()

        async def stuck_coro():
            shutdown.set()  # Acknowledge but don't exit
            await asyncio.sleep(9999)

        task = asyncio.create_task(stuck_coro())
        await asyncio.sleep(0)  # Let it start

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=task,
            _shutdown_event=asyncio.Event(),  # Owner ignores this
        )

        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool._get_cleanup_timeout", return_value=0.1):
            await pool._close_session(pooled)

        assert task.done()

    @pytest.mark.asyncio
    async def test_owner_fails_before_readiness_propagates_error(self):
        """If the owner task fails before signaling readiness, _create_session should raise."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with pytest.raises(RuntimeError, match="Failed to create MCP session"):
                await pool._create_session("http://test:8080", None, TransportType.SSE, None)


class TestTransportAwareIsClosed:
    """Tests for transport-aware is_closed detection (from PR #3605)."""

    def test_is_closed_detects_closed_write_stream(self):
        """is_closed should detect a closed _write_stream."""
        mock_session = MagicMock()
        mock_session._write_stream = MagicMock()
        mock_session._write_stream._closed = True

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        assert pooled.is_closed is True

    def test_is_closed_detects_zero_receive_channels(self):
        """is_closed should detect zero open receive channels."""
        mock_session = MagicMock()
        mock_session._write_stream = MagicMock()
        mock_session._write_stream._closed = False
        mock_state = MagicMock()
        mock_state.open_receive_channels = 0
        mock_session._write_stream._state = mock_state

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        assert pooled.is_closed is True

    def test_is_closed_false_when_stream_healthy(self):
        """is_closed should return False when the stream is healthy."""
        mock_session = MagicMock()
        mock_session._write_stream = MagicMock()
        mock_session._write_stream._closed = False
        mock_state = MagicMock()
        mock_state.open_receive_channels = 1
        mock_session._write_stream._state = mock_state

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        assert pooled.is_closed is False

    def test_is_closed_degrades_gracefully_without_write_stream(self):
        """is_closed should not crash if session has no _write_stream attribute."""
        mock_session = MagicMock(spec=[])  # No attributes

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        assert pooled.is_closed is False


class TestReleaseWithDeadOwner:
    """Tests for release() when the owner task has died."""

    @pytest.mark.asyncio
    async def test_release_discard_true_with_dead_owner_cleans_up(self):
        """release(discard=True) with dead owner should still remove from active and release semaphore."""
        pool = MCPSessionPool()

        done_future = asyncio.get_event_loop().create_future()
        done_future.set_result(None)

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=asyncio.ensure_future(done_future),
            _shutdown_event=asyncio.Event(),
        )
        await asyncio.sleep(0)  # Let task complete

        # Set up pool structures
        pool_key = pool._make_pool_key("http://test:8080", {}, TransportType.STREAMABLE_HTTP, "anonymous", "")
        pool_obj = await pool._get_or_create_pool(pool_key)
        pool._semaphores[pool_key] = asyncio.Semaphore(0)  # All slots consumed
        pool._active[pool_key] = {pooled}

        assert pooled.is_closed is True  # Owner task is done

        await pool.release(pooled, discard=True)

        # Verify cleanup happened
        assert pooled not in pool._active.get(pool_key, set())
        assert pool._evictions >= 1

    @pytest.mark.asyncio
    async def test_release_discard_false_with_dead_owner_still_discards(self):
        """release(discard=False) with dead owner should auto-discard."""
        pool = MCPSessionPool()

        done_future = asyncio.get_event_loop().create_future()
        done_future.set_result(None)

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            _owner_task=asyncio.ensure_future(done_future),
            _shutdown_event=asyncio.Event(),
        )
        await asyncio.sleep(0)

        pool_key = pool._make_pool_key("http://test:8080", {}, TransportType.STREAMABLE_HTTP, "anonymous", "")
        await pool._get_or_create_pool(pool_key)
        pool._semaphores[pool_key] = asyncio.Semaphore(0)
        pool._active[pool_key] = {pooled}

        # Even with discard=False, is_closed triggers auto-discard
        await pool.release(pooled, discard=False)
        assert pool._evictions >= 1


class TestCreateSessionCancelledError:
    """Tests for _create_session cleanup on CancelledError."""

    @pytest.mark.asyncio
    async def test_create_session_cleans_up_on_outer_cancellation(self):
        """If _create_session is cancelled by an outer wait_for, the owner task should be cleaned up."""
        pool = MCPSessionPool()
        owner_tasks_created = []

        original_create_task = asyncio.create_task

        def tracking_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            owner_tasks_created.append(task)
            return task

        # Use a transport whose __aenter__ hangs forever to trigger timeout
        transport_ctx = MagicMock()

        async def hang_forever(*_args, **_kwargs):
            await asyncio.sleep(9999)

        transport_ctx.__aenter__ = hang_forever
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("asyncio.create_task", side_effect=tracking_create_task):
                with pytest.raises((asyncio.TimeoutError, RuntimeError)):
                    await asyncio.wait_for(
                        pool._create_session("http://test:8080", None, TransportType.SSE, None),
                        timeout=0.1,
                    )

        # Allow cleanup to run
        await asyncio.sleep(0.2)

        # The owner task should have been cancelled/cleaned up
        assert len(owner_tasks_created) >= 1
        for task in owner_tasks_created:
            assert task.done(), "Owner task should be done after cancellation cleanup"


class TestHealthCheckAnyioTimeout:
    """Tests for health check using anyio.fail_after."""

    @pytest.mark.asyncio
    async def test_health_check_timeout_raises_timeout_error(self):
        """Health check timeout should be caught and handled."""
        pool = MCPSessionPool(health_check_methods=["ping", "skip"])
        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        pooled.session.send_ping = AsyncMock(side_effect=TimeoutError())

        result = await pool._run_health_check_chain(pooled)
        # "ping" times out → falls through to "skip" → returns True
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_all_timeout_returns_false(self):
        """When all health check methods timeout, should return False."""
        pool = MCPSessionPool(health_check_methods=["ping"])
        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )
        pooled.session.send_ping = AsyncMock(side_effect=TimeoutError())

        result = await pool._run_health_check_chain(pooled)
        assert result is False
        assert pool._health_check_failures == 1


class TestValidateSessionWithOwnerTask:
    """Tests for _validate_session with owner task awareness."""

    @pytest.mark.asyncio
    async def test_validate_rejects_dead_owner_session(self):
        """_validate_session should reject sessions with dead owner tasks."""
        pool = MCPSessionPool()

        done_future = asyncio.get_event_loop().create_future()
        done_future.set_result(None)

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            created_at=time.time(),
            last_used=time.time(),
            _owner_task=asyncio.ensure_future(done_future),
        )
        await asyncio.sleep(0)

        result = await pool._validate_session(pooled)
        assert result is False


class TestPromptPooledRegression:
    """Regression tests for prompt service using the pool (plan requirement)."""

    @pytest.mark.asyncio
    async def test_pooled_get_prompt_succeeds(self):
        """Pooled get_prompt() should succeed when pool is available."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_prompt_result = MagicMock()
        mock_prompt_result.messages = []
        mock_prompt_result.description = "test prompt"

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(return_value=None)
        session_instance.get_prompt = AsyncMock(return_value=mock_prompt_result)

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                async with pool.session(
                    url="http://test:8080",
                    headers={},
                    transport_type=TransportType.SSE,
                ) as pooled:
                    result = await pooled.session.get_prompt("test-prompt", arguments={})

        assert result == mock_prompt_result
        session_instance.get_prompt.assert_awaited_once_with("test-prompt", arguments={})
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_pooled_get_prompt_fallback_when_pool_unavailable(self):
        """get_mcp_session_pool() raising RuntimeError should be handled by callers."""
        from mcpgateway.services.mcp_session_pool import get_mcp_session_pool

        # When pool is not initialized, get_mcp_session_pool raises RuntimeError
        with pytest.raises(RuntimeError, match="not initialized"):
            get_mcp_session_pool()
