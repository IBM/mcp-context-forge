# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""

import asyncio
import logging
from datetime import datetime

import pytest

from mcpgateway.services.logging_service import LoggingService  # noqa: E402
from mcpgateway.types import LogLevel  # noqa: E402


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
    # Default level INFO
    logger1 = service.get_logger("test")
    assert logger1.level == logging.INFO

    # Subsequent get_logger returns the same instance
    logger2 = service.get_logger("test")
    assert logger1 is logger2

    # Change service level to DEBUG and verify new logger gets updated level
    await service.set_level(LogLevel.DEBUG)
    logger3 = service.get_logger("newlogger")
    assert logger3.level == logging.DEBUG


@pytest.mark.asyncio
async def test_notify_without_subscribers_logs_via_standard_logging(caplog):
    service = LoggingService()
    caplog.set_level(logging.INFO)
    # No subscribers: should not raise
    await service.notify("standalone message", LogLevel.INFO)
    # Standard logging should have captured the message
    assert "standalone message" in caplog.text


@pytest.mark.asyncio
async def test_notify_below_threshold_does_not_send_to_subscribers():
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)

    task = asyncio.create_task(subscriber())
    # Send DEBUG while level is INFO: should be skipped
    await service.notify("debug msg", LogLevel.DEBUG)
    # Give a moment for any (unexpected) deliveries
    await asyncio.sleep(0.1)
    assert events == []

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_notify_and_subscribe_receive_message_with_metadata():
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)
            break

    task = asyncio.create_task(subscriber())
    await service.notify("hello world", LogLevel.INFO, logger_name="mylogger")
    await asyncio.wait_for(task, timeout=1.0)

    assert len(events) == 1
    evt = events[0]
    # Check structure
    assert evt["type"] == "log"
    data = evt["data"]
    assert data["level"] == LogLevel.INFO
    assert data["data"] == "hello world"
    # Timestamp is ISO-format parsable
    datetime.fromisoformat(data["timestamp"])
    # Logger name included
    assert data["logger"] == "mylogger"

    # Clean up
    await service.shutdown()


@pytest.mark.asyncio
async def test_set_level_updates_all_loggers_and_sends_info_notification():
    service = LoggingService()
    events = []

    async def subscriber():
        async for msg in service.subscribe():
            events.append(msg)
            break

    task = asyncio.create_task(subscriber())
    # Set to WARNING
    await service.set_level(LogLevel.WARNING)
    await asyncio.wait_for(task, timeout=1.0)

    # Verify notification event
    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "log"
    data = evt["data"]
    assert data["level"] == LogLevel.INFO
    assert "Log level set to WARNING" in data["data"]

    # Existing root logger level updated
    root_logger = service.get_logger("")
    assert root_logger.level == logging.WARNING

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_subscribe_cleanup_removes_queue_on_cancel():
    service = LoggingService()
    # No subscribers initially
    assert len(service._subscribers) == 0

    # Start subscription but don't yield any events
    agen = service.subscribe()
    task = asyncio.create_task(agen.__anext__())

    # Subscriber should be registered
    await asyncio.sleep(0)  # allow subscription setup
    assert len(service._subscribers) == 1

    # Cancel the pending next() to trigger cleanup
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Subscriber should have been removed
    assert len(service._subscribers) == 0
