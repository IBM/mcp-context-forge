# -*- coding: utf-8 -*-
"""Utility: centralized background TaskScheduler.

This module contains the Priority enum and the TaskScheduler implementation.
It is intentionally lightweight so other packages can import the scheduler
without pulling the full `mcpgateway.services` package (avoids import cycles
and linting issues).
"""
# Future
from __future__ import annotations

# Standard
import asyncio
from enum import IntEnum
import logging
from typing import Awaitable, Callable

logger = logging.getLogger("mcpgateway.task_scheduler")


class Priority(IntEnum):
    """Priority levels for scheduled background tasks.

    Lower numeric value means higher scheduling priority (CRITICAL=0 runs
    before HIGH=1, etc.).
    """

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskScheduler:
    """Centralized scheduler that orders tasks by priority and limits concurrency.

    Usage: import `task_scheduler` from this module and call
    `task_scheduler.schedule(callable_returning_coro, Priority.NORMAL)` to
    register a background coroutine. The scheduler will invoke the callable
    when ready and manage concurrency.
    """

    def __init__(self, max_concurrent: int = 3):
        """Initialize the TaskScheduler.

        Args:
            max_concurrent: Maximum number of concurrent running tasks.
        """
        self._queue: "asyncio.PriorityQueue[tuple[int, int, Callable[[], Awaitable], asyncio.Future]]" = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._counter = 0
        self._manager_task: asyncio.Task | None = None
        self._running = False

    def _ensure_manager(self) -> None:
        if not self._running:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Not running inside an event loop yet; manager will be started
                # by the first call from an event loop context.
                return
            self._manager_task = loop.create_task(self._manager_loop())
            self._running = True

    async def _manager_loop(self) -> None:
        while True:
            # Wait for at least one item
            first_item = await self._queue.get()

            # Drain any currently-available items so we can order them by priority
            items = [first_item]
            try:
                while True:
                    items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                pass

            # Each item is (priority, counter, func, fut). Sort to enforce priority then FIFO among same-priority.
            items.sort(key=lambda t: (t[0], t[1]))

            async def _run_item(func, fut):
                async with self._semaphore:
                    try:
                        coro = func()
                        result = await coro
                        if not fut.done():
                            fut.set_result(result)
                    except Exception:
                        if not fut.done():
                            fut.set_exception(Exception("Background task failed"))
                        logger.exception("Background task failed")

            # Schedule all drained items; concurrency is controlled by semaphore inside _run_item.
            for _prio, _cnt, func, fut in items:
                asyncio.create_task(_run_item(func, fut))

    def schedule(self, func: "Callable[[], Awaitable]", priority: Priority = Priority.NORMAL) -> asyncio.Task:
        """Schedule a zero-argument callable that returns a coroutine for prioritized execution.

        The callable will be invoked by the scheduler when it's ready to run
        (avoids creating coroutine objects before scheduling).

        Args:
            func: A zero-argument callable which, when called, returns an awaitable/coroutine.
            priority: Scheduling priority; lower numeric value runs earlier.

        Returns:
            An ``asyncio.Task`` which will complete with the callable's coroutine result.
        """
        self._ensure_manager()
        self._counter += 1

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        # Put the callable and the future into the queue; the manager will
        # call the callable to obtain a coroutine and run it, then set the
        # future with the result or exception.
        self._queue.put_nowait((int(priority), self._counter, func, fut))

        async def _wait_future() -> object:
            return await fut

        return asyncio.create_task(_wait_future())


# Create a module-level scheduler instance with a small default concurrency.
task_scheduler = TaskScheduler(max_concurrent=3)

__all__ = ["task_scheduler", "TaskScheduler", "Priority"]
