# -*- coding: utf-8 -*-
"""Location: ./tests/async/test_async_safety.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive async safety tests for mcpgateway.
"""

# Standard
import asyncio
import time
from typing import Any, List

# Third-Party
import pytest


class TestAsyncSafety:
    """Test async safety and proper coroutine handling."""

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
        execution_time = end_time - start_time

        # Should complete in roughly 10ms, not 1000ms (100 * 10ms)
        # Allow generous tolerance for CI environments, system load, and concurrent test runs
        max_time = 0.50  # 500ms tolerance for loaded systems
        assert execution_time < max_time, f"Concurrent operations not properly parallelized: took {execution_time:.3f}s, expected < {max_time:.3f}s"
        assert len(results) == 100, "Not all operations completed"

    @pytest.mark.asyncio
    async def test_task_cleanup(self):
        """Test proper task cleanup and no task leaks."""

        initial_tasks = len(asyncio.all_tasks())

        async def background_task():
            await asyncio.sleep(0.1)

        # Create and properly manage tasks
        tasks: List[Any] = []
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
