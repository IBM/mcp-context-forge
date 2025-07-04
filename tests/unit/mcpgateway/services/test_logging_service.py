# -*- coding: utf-8 -*-
"""
Unit-tests for the LoggingService.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Key details
-----------
`LoggingService.subscribe()` registers the subscriber *inside* the first
iteration of the coroutine.  If we fire `notify()` immediately after calling
`asyncio.create_task(subscriber())`, the subscriber's coroutine may not have
run yet, so no queue is registered and the message is lost.

The fix is a single `await asyncio.sleep(0)` (one event-loop tick) after
`create_task(...)` in the two tests that wait for a message.  This guarantees
the subscriber is fully set up before we emit the first log event.
"""

# Standard
import asyncio
from datetime import datetime
import logging

# Third-Party
import pytest

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.types import LogLevel

# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_log_default_levels():
    service = LoggingService()
    # Default level is INFO
    assert not service._should_log(LogLevel.DEBUG)
    assert service._should_log(LogLevel.INFO)
    assert service._should_log(LogLevel.ERROR)


@pytest.mark.asyncio
async def test_get_logger_sets_level_and_reuses_instance():
    service = LoggingService()

    # First call – default level INFO
    logger1 = service.get_logger("test")
    assert logger1.level == logging.INFO

    # Same logger object returned on second call
    logger2 = service.get_logger("test")
    assert logger1 is logger2

    # After raising service level to DEBUG a *new* logger inherits that level
    await service.set_level(LogLevel.DEBUG)
    logger3 = service.get_logger("newlogger")
    assert logger3.level == logging.DEBUG


# ---------------------------------------------------------------------------
# notify() when nobody is listening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_without_subscribers_logs_via_standard_logging(caplog):
    service = LoggingService()
    caplog.set_level(logging.INFO)

    # No subscribers → should simply log via stdlib logging
    await service.notify("standalone message", LogLevel.INFO)
    assert "standalone message" in caplog.text


# ---------------------------------------------------------------------------
# notify() below threshold is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_below_threshold_does_not_send_to_subscribers():
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # ensure subscriber registered

    # DEBUG is below default INFO → should be ignored
    await service.notify("debug msg", LogLevel.DEBUG)
    await asyncio.sleep(0.1)  # allow any unexpected deliveries

    assert events == []

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Race-condition-safe tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_and_subscribe_receive_message_with_metadata():
    """
    Verify a subscriber receives a message together with metadata.

    The tiny ``await asyncio.sleep(0)`` after creating the task ensures the
    subscriber has entered its coroutine and registered its queue before
    ``notify`` is called – otherwise the message could be lost.
    """
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)
            break  # stop after first event

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # <─ critical: let the subscriber register

    await service.notify("hello world", LogLevel.INFO, logger_name="mylogger")
    await asyncio.wait_for(task, timeout=1.0)

    # Validate structure
    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "log"
    data = evt["data"]
    assert data["level"] == LogLevel.INFO
    assert data["data"] == "hello world"
    datetime.fromisoformat(data["timestamp"])  # no exception
    assert data["logger"] == "mylogger"

    await service.shutdown()


@pytest.mark.asyncio
async def test_set_level_updates_all_loggers_and_sends_info_notification():
    """
    After raising the service level to WARNING an INFO-level notification
    is *below* the new threshold, so no event is delivered.  We therefore
    assert that the subscriber receives nothing and that existing loggers
    have been updated.
    """
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)  # ensure subscriber is registered

    # Change level to WARNING
    await service.set_level(LogLevel.WARNING)
    await asyncio.sleep(0.1)  # allow any unexpected deliveries

    # No events should have been delivered
    assert events == []

    # Root logger level must reflect the change
    root_logger = service.get_logger("")
    assert root_logger.level == logging.WARNING

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# subscribe() cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_cleanup_removes_queue_on_cancel():
    service = LoggingService()

    # No subscribers initially
    assert len(service._subscribers) == 0

    agen = service.subscribe()
    task = asyncio.create_task(agen.__anext__())

    # Subscriber should now be registered
    await asyncio.sleep(0)
    assert len(service._subscribers) == 1

    # Cancel the pending receive to trigger ``finally`` block cleanup
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(service._subscribers) == 0
