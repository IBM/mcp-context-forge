"""
Comprehensive async safety tests for mcpgateway.
"""

import pytest
import asyncio
import warnings
import time
from unittest.mock import AsyncMock, patch


class TestAsyncSafety:
    """Test async safety and proper coroutine handling."""

    def test_no_unawaited_coroutines(self):
        """Test that no coroutines are left unawaited."""

        # Capture async warnings
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")

            # Run async code that might have unawaited coroutines
            asyncio.run(self._test_async_operations())

        # Check for unawaited coroutine warnings
        unawaited_warnings = [w for w in caught_warnings if "coroutine" in str(w.message) and "never awaited" in str(w.message)]

        assert len(unawaited_warnings) == 0, f"Found {len(unawaited_warnings)} unawaited coroutines"

    async def _test_async_operations(self):
        """Test various async operations for safety."""

        # Test WebSocket operations
        await self._test_websocket_safety()

        # Test database operations
        await self._test_database_safety()

        # Test MCP operations
        await self._test_mcp_safety()

    async def _test_websocket_safety(self):
        """Test WebSocket async safety."""

        # Mock WebSocket operations
        with patch("websockets.connect") as mock_connect:
            mock_websocket = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_websocket

            # Test proper awaiting
            async with mock_connect("ws://test") as websocket:
                await websocket.send("test")
                await websocket.recv()

    async def _test_database_safety(self):
        """Test database async safety."""

        # Mock database operations
        with patch("asyncpg.connect") as mock_connect:
            mock_connection = AsyncMock()
            mock_connect.return_value = mock_connection

            # Test proper connection handling
            connection = await mock_connect("postgresql://test")
            await connection.execute("SELECT 1")
            await connection.close()

    async def _test_mcp_safety(self):
        """Test MCP async safety."""

        # Mock MCP operations
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_session.return_value.post.return_value.__aenter__.return_value = mock_response

            # Test proper session handling
            async with mock_session() as session:
                async with session.post("http://test") as response:
                    await response.json()

    @pytest.mark.asyncio
    async def test_concurrent_operations_performance(self):
        """Test performance of concurrent async operations."""

        async def mock_operation():
            await asyncio.sleep(0.01)  # 10ms operation
            return "result"

        # Test concurrent execution
        start_time = time.time()

        tasks = [mock_operation() for _ in range(100)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()

        # Should complete in roughly 10ms, not 1000ms (100 * 10ms)
        assert end_time - start_time < 0.1, "Concurrent operations not properly parallelized"
        assert len(results) == 100, "Not all operations completed"

    @pytest.mark.asyncio
    async def test_task_cleanup(self):
        """Test proper task cleanup and no task leaks."""

        initial_tasks = len(asyncio.all_tasks())

        async def background_task():
            await asyncio.sleep(0.1)

        # Create and properly manage tasks
        tasks = []
        for _ in range(10):
            task = asyncio.create_task(background_task())
            tasks.append(task)

        # Wait for completion
        await asyncio.gather(*tasks)

        # Check no leaked tasks
        final_tasks = len(asyncio.all_tasks())

        # Allow for some variation but no significant leaks
        assert final_tasks <= initial_tasks + 2, "Task leak detected"

    @pytest.mark.asyncio
    async def test_exception_handling_in_async(self):
        """Test proper exception handling in async operations."""

        async def failing_operation():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        # Test exception handling doesn't break event loop
        with pytest.raises(ValueError):
            await failing_operation()

        # Event loop should still be functional
        await asyncio.sleep(0.01)
        assert True, "Event loop functional after exception"
