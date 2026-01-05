# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Services Package.
Exposes core MCP Gateway services:
- Tool management
- Resource handling
- Prompt templates
- Gateway coordination
"""

from enum import IntEnum
import asyncio
import logging
from typing import Awaitable

logger = logging.getLogger("mcpgateway.task_scheduler")


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskScheduler:
    """Centralized scheduler that orders tasks by priority and limits concurrency.

    Usage: import from `mcpgateway.services` as `task_scheduler` and call
    `task_scheduler.schedule(coro, Priority.NORMAL)` to register a background
    coroutine. The scheduler will start tasks according to priority and the
    configured concurrency limit.
    """

    def __init__(self, max_concurrent: int = 3):
        self._queue: "asyncio.PriorityQueue[tuple[int, int, Awaitable]]" = asyncio.PriorityQueue()
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
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if not fut.done():
                            fut.set_exception(Exception("Background task failed"))
                        logger.exception("Background task failed")

            # Schedule all drained items; concurrency is controlled by semaphore inside _run_item.
            for prio, cnt, func, fut in items:
                asyncio.create_task(_run_item(func, fut))

    def schedule(self, func: "Callable[[], Awaitable]", priority: Priority = Priority.NORMAL) -> asyncio.Task:
        """Schedule a zero-argument callable that returns a coroutine for prioritized execution.

        The callable will be invoked by the scheduler when it's ready to run
        (avoids creating coroutine objects before scheduling). Returns an
        `asyncio.Task` that completes with the callable's coroutine result.
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

from mcpgateway.services.gateway_service import GatewayError, GatewayService
from mcpgateway.services.prompt_service import PromptError, PromptService
from mcpgateway.services.resource_service import ResourceError, ResourceService
from mcpgateway.services.tool_service import ToolError, ToolService

__all__ = [
    "ToolService",
    "ToolError",
    "ResourceService",
    "ResourceError",
    "PromptService",
    "PromptError",
    "GatewayService",
    "GatewayError",
]

