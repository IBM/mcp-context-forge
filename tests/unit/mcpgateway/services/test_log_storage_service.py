# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_log_storage_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for LogStorageService.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.services.log_storage_service import LogEntry, LogStorageService


@pytest.mark.asyncio
async def test_log_entry_creation():
    """Test LogEntry creation with all fields."""
    entry = LogEntry(level=LogLevel.INFO, entity_type="tool", entity_id="tool-1", entity_name="Test Tool", message="Test message", logger="test.logger", data={"key": "value"}, request_id="req-123")

    assert entry.id  # Should have auto-generated UUID
    assert entry.level == LogLevel.INFO
    assert entry.entity_type == "tool"
    assert entry.entity_id == "tool-1"
    assert entry.entity_name == "Test Tool"
    assert entry.message == "Test message"
    assert entry.logger == "test.logger"
    assert entry.data == {"key": "value"}
    assert entry.request_id == "req-123"
    assert entry._size > 0


@pytest.mark.asyncio
async def test_log_entry_size_calculation():
    """Test LogEntry size calculation."""
    entry = LogEntry(
        level=LogLevel.INFO,
        message="Test message",
    )

    # Verify that the entry has a reasonable size
    assert entry._size > 0
    # Should be at least as big as the message
    assert entry._size >= len("Test message")
    # Should be less than some reasonable upper bound
    assert entry._size < 10000  # 10KB max for a simple log entry


@pytest.mark.asyncio
async def test_log_storage_service_initialization():
    """Test LogStorageService initialization with default settings."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        assert service._max_size_bytes == 1024 * 1024
        assert service._current_size_bytes == 0
        assert len(service._buffer) == 0
        assert len(service._entity_index) == 0
        assert len(service._request_index) == 0
        assert len(service._subscribers) == 0


@pytest.mark.asyncio
async def test_add_log_basic():
    """Test adding a basic log entry."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        await service.add_log(level=LogLevel.INFO, message="Test log message")

        assert len(service._buffer) == 1
        assert service._buffer[0].message == "Test log message"
        assert service._buffer[0].level == LogLevel.INFO
        assert service._current_size_bytes > 0


@pytest.mark.asyncio
async def test_add_log_with_entity():
    """Test adding log with entity information."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        await service.add_log(level=LogLevel.INFO, message="Entity log", entity_type="tool", entity_id="tool-1", entity_name="Test Tool")

        assert len(service._buffer) == 1
        assert service._buffer[0].entity_type == "tool"
        assert service._buffer[0].entity_id == "tool-1"
        assert service._buffer[0].entity_name == "Test Tool"

        # Check entity index
        assert "tool:tool-1" in service._entity_index
        assert len(service._entity_index["tool:tool-1"]) == 1


@pytest.mark.asyncio
async def test_add_log_with_existing_entity_index_key():
    """Cover branch when entity index key already exists."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()
        await service.add_log(level=LogLevel.INFO, message="Entity log 1", entity_type="tool", entity_id="tool-1")
        await service.add_log(level=LogLevel.INFO, message="Entity log 2", entity_type="tool", entity_id="tool-1")

        assert len(service._entity_index["tool:tool-1"]) == 2


@pytest.mark.asyncio
async def test_add_log_with_request_id():
    """Test adding log with request ID."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        await service.add_log(level=LogLevel.INFO, message="Request log", request_id="req-123")

        assert len(service._buffer) == 1
        assert service._buffer[0].request_id == "req-123"

        # Check request index
        assert "req-123" in service._request_index
        assert len(service._request_index["req-123"]) == 1


@pytest.mark.asyncio
async def test_size_based_eviction():
    """Test that old logs are evicted when buffer size is exceeded."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        # Set very small buffer (1KB)
        mock_settings.log_buffer_size_mb = 0.001  # 1KB

        service = LogStorageService()

        # Add logs until we exceed the buffer
        for i in range(100):
            await service.add_log(
                level=LogLevel.INFO,
                message=f"Log message {i} " + "x" * 100,  # Make each log reasonably sized
            )

        # Buffer should not exceed max size
        assert service._current_size_bytes <= service._max_size_bytes
        # Should have evicted some logs
        assert len(service._buffer) < 100
        # Most recent log should be preserved
        assert "Log message 99" in service._buffer[-1].message


@pytest.mark.asyncio
async def test_get_logs_no_filters():
    """Test getting logs without filters."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add some logs
        for i in range(5):
            await service.add_log(level=LogLevel.INFO, message=f"Log {i}")

        result = await service.get_logs()

        assert len(result) == 5
        assert result[0]["message"] == "Log 4"  # Most recent first
        assert result[4]["message"] == "Log 0"  # Oldest last


@pytest.mark.asyncio
async def test_get_logs_with_limit_offset():
    """Test getting logs with pagination."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add 10 logs
        for i in range(10):
            await service.add_log(level=LogLevel.INFO, message=f"Log {i}")

        # Get first page
        result = await service.get_logs(limit=3, offset=0)
        assert len(result) == 3
        assert result[0]["message"] == "Log 9"

        # Get second page
        result = await service.get_logs(limit=3, offset=3)
        assert len(result) == 3
        assert result[0]["message"] == "Log 6"


@pytest.mark.asyncio
async def test_get_logs_filter_by_level():
    """Test filtering logs by level."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different levels
        await service.add_log(level=LogLevel.DEBUG, message="Debug log")
        await service.add_log(level=LogLevel.INFO, message="Info log")
        await service.add_log(level=LogLevel.WARNING, message="Warning log")
        await service.add_log(level=LogLevel.ERROR, message="Error log")

        # Filter by ERROR level (returns ERROR and higher)
        result = await service.get_logs(level=LogLevel.ERROR)
        assert len(result) == 1
        assert result[0]["message"] == "Error log"

        # Filter by WARNING level (returns WARNING, ERROR, and higher)
        result = await service.get_logs(level=LogLevel.WARNING)
        assert len(result) == 2  # Warning and Error
        messages = [log["message"] for log in result]
        assert "Warning log" in messages
        assert "Error log" in messages


@pytest.mark.asyncio
async def test_get_logs_filter_by_entity():
    """Test filtering logs by entity."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different entities
        await service.add_log(level=LogLevel.INFO, message="Tool log", entity_type="tool", entity_id="tool-1")
        await service.add_log(level=LogLevel.INFO, message="Resource log", entity_type="resource", entity_id="res-1")
        await service.add_log(level=LogLevel.INFO, message="Another tool log", entity_type="tool", entity_id="tool-2")

        # Filter by entity type
        result = await service.get_logs(entity_type="tool")
        assert len(result) == 2

        # Filter by specific entity
        result = await service.get_logs(entity_type="tool", entity_id="tool-1")
        assert len(result) == 1
        assert result[0]["message"] == "Tool log"


@pytest.mark.asyncio
async def test_get_logs_filter_by_request_id():
    """Test filtering logs by request ID."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different request IDs
        await service.add_log(level=LogLevel.INFO, message="Request 1 log 1", request_id="req-1")
        await service.add_log(level=LogLevel.INFO, message="Request 2 log", request_id="req-2")
        await service.add_log(level=LogLevel.INFO, message="Request 1 log 2", request_id="req-1")

        # Filter by request ID
        result = await service.get_logs(request_id="req-1")
        assert len(result) == 2
        assert all(log["request_id"] == "req-1" for log in result)


@pytest.mark.asyncio
async def test_get_logs_search():
    """Test searching logs by message content."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different messages
        await service.add_log(level=LogLevel.INFO, message="Starting server on port 8000")
        await service.add_log(level=LogLevel.INFO, message="Connection established")
        await service.add_log(level=LogLevel.ERROR, message="Failed to start server")
        await service.add_log(level=LogLevel.INFO, message="Server shutdown complete")

        # Search for "server"
        result = await service.get_logs(search="server")
        assert len(result) == 3
        assert all("server" in log["message"].lower() for log in result)

        # Case-insensitive search
        result = await service.get_logs(search="SERVER")
        assert len(result) == 3


@pytest.mark.asyncio
async def test_get_logs_time_range():
    """Test filtering logs by time range."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with specific timestamps
        now = datetime.now(timezone.utc)

        # Create log with past timestamp
        old_entry = LogEntry(level=LogLevel.INFO, message="Old log")
        # Manually set old timestamp
        old_entry.timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        service._buffer.append(old_entry)
        service._current_size_bytes += old_entry._size

        # Add current log
        await service.add_log(level=LogLevel.INFO, message="Current log")

        # Filter by time range (should only include current log)
        # Use now + 1 day to ensure the current log falls within the range
        future_time = now + timedelta(days=1)
        result = await service.get_logs(start_time=datetime(2024, 6, 1, tzinfo=timezone.utc), end_time=future_time)
        assert len(result) == 1
        assert result[0]["message"] == "Current log"


@pytest.mark.asyncio
async def test_get_logs_time_range_excludes_entries_after_end_time():
    """Cover end_time upper-bound filter branch."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0
        service = LogStorageService()

        future_entry = LogEntry(level=LogLevel.INFO, message="Future log")
        future_entry.timestamp = datetime(2030, 1, 1, tzinfo=timezone.utc)
        service._buffer.append(future_entry)
        service._current_size_bytes += future_entry._size

        result = await service.get_logs(end_time=datetime(2025, 1, 1, tzinfo=timezone.utc))

        assert result == []


@pytest.mark.asyncio
async def test_remove_from_indices_branch_coverage():
    """Cover remaining _remove_from_indices index branches."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0
        service = LogStorageService()

        # Create shared indices with multiple IDs so deletion keeps key alive.
        e1 = await service.add_log(level=LogLevel.INFO, message="one", entity_type="tool", entity_id="tool-1", request_id="req-1")
        await service.add_log(level=LogLevel.INFO, message="two", entity_type="tool", entity_id="tool-1", request_id="req-1")

        service._remove_from_indices(e1)
        assert "tool:tool-1" in service._entity_index
        assert "req-1" in service._request_index

        # Entry with unknown entity key should hit "key not in index" branch.
        ghost = LogEntry(level=LogLevel.INFO, message="ghost", entity_type="tool", entity_id="missing", request_id=None)
        service._remove_from_indices(ghost)


@pytest.mark.asyncio
async def test_clear_logs():
    """Test clearing all logs."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add some logs
        for i in range(5):
            await service.add_log(level=LogLevel.INFO, message=f"Log {i}", entity_type="tool", entity_id=f"tool-{i}", request_id=f"req-{i}")

        assert len(service._buffer) == 5
        assert len(service._entity_index) > 0
        assert len(service._request_index) > 0
        assert service._current_size_bytes > 0

        # Clear logs (not async)
        count = service.clear()

        assert count == 5
        assert len(service._buffer) == 0
        assert len(service._entity_index) == 0
        assert len(service._request_index) == 0
        assert service._current_size_bytes == 0


@pytest.mark.asyncio
async def test_get_stats():
    """Test getting log statistics."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different levels
        await service.add_log(level=LogLevel.DEBUG, message="Debug")
        await service.add_log(level=LogLevel.INFO, message="Info 1")
        await service.add_log(level=LogLevel.INFO, message="Info 2")
        await service.add_log(level=LogLevel.WARNING, message="Warning")
        await service.add_log(level=LogLevel.ERROR, message="Error")

        stats = service.get_stats()

        assert stats["total_logs"] == 5
        assert stats["buffer_size_bytes"] > 0
        assert stats["buffer_size_bytes"] == service._current_size_bytes
        assert stats["max_size_mb"] == 1.0
        assert LogLevel.DEBUG in stats["level_distribution"]
        assert stats["level_distribution"][LogLevel.INFO] == 2
        assert stats["level_distribution"][LogLevel.WARNING] == 1
        assert stats["level_distribution"][LogLevel.ERROR] == 1


@pytest.mark.asyncio
async def test_subscribe_to_logs():
    """Test subscribing to log updates."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create subscription
        subscription = service.subscribe()
        subscriber_task = asyncio.create_task(anext(subscription))

        # Give subscriber time to register
        await asyncio.sleep(0.01)

        # Add a log
        await service.add_log(level=LogLevel.INFO, message="Test log")

        # Get the log from subscription
        try:
            log = await asyncio.wait_for(subscriber_task, timeout=1.0)
            assert log["type"] == "log_entry"
            assert log["data"]["message"] == "Test log"
            assert log["data"]["level"] == LogLevel.INFO
        finally:
            # Clean up
            await subscription.aclose()


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Test multiple subscribers receive logs."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create multiple subscriptions
        sub1 = service.subscribe()
        sub2 = service.subscribe()

        task1 = asyncio.create_task(anext(sub1))
        task2 = asyncio.create_task(anext(sub2))

        # Give subscribers time to register
        await asyncio.sleep(0.01)

        # Add a log
        await service.add_log(level=LogLevel.INFO, message="Broadcast log")

        # Both subscribers should receive the log
        try:
            log1 = await asyncio.wait_for(task1, timeout=1.0)
            log2 = await asyncio.wait_for(task2, timeout=1.0)

            assert log1["data"]["message"] == "Broadcast log"
            assert log2["data"]["message"] == "Broadcast log"
        finally:
            # Clean up
            await sub1.aclose()
            await sub2.aclose()


# NOTE: export_logs method doesn't exist in LogStorageService
# Export functionality is handled by admin.py directly


# NOTE: export_logs method doesn't exist in LogStorageService
# Export functionality is handled by admin.py directly


@pytest.mark.asyncio
async def test_entity_index_cleanup():
    """Test that entity index is cleaned up when logs are evicted."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        # Very small buffer to force eviction
        mock_settings.log_buffer_size_mb = 0.0001  # 100 bytes

        service = LogStorageService()

        # Add multiple logs with the same entity to ensure we can track cleanup
        first_logs = []
        for i in range(3):
            log = await service.add_log(level=LogLevel.INFO, message=f"Tool log {i}", entity_type="tool", entity_id="tool-1")
            first_logs.append(log.id)

        # Add many large logs without entity to force eviction
        for i in range(100):
            await service.add_log(
                level=LogLevel.INFO,
                message=f"Big log {i}" + "x" * 100,  # Make it big enough to force eviction
            )

        # Check that all first logs were evicted
        buffer_ids = {log.id for log in service._buffer}
        for log_id in first_logs:
            assert log_id not in buffer_ids, f"Log {log_id} should have been evicted"

        # The entity index should be cleaned up
        entity_key = "tool:tool-1"
        if entity_key in service._entity_index:
            # None of the evicted logs should be in the index
            for log_id in first_logs:
                assert log_id not in service._entity_index[entity_key], f"Evicted log {log_id} still in entity index"


@pytest.mark.asyncio
async def test_request_index_cleanup():
    """Test that request index is cleaned up when logs are evicted."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        # Very small buffer to force eviction
        mock_settings.log_buffer_size_mb = 0.0001  # 100 bytes

        service = LogStorageService()

        # Add multiple logs with same request ID
        first_logs = []
        for i in range(3):
            log = await service.add_log(level=LogLevel.INFO, message=f"Request log {i}", request_id="req-123")
            first_logs.append(log.id)

        # Add many large logs to force eviction
        for i in range(100):
            await service.add_log(level=LogLevel.INFO, message=f"Big log {i}" + "x" * 100)

        # Check that all first logs were evicted
        buffer_ids = {log.id for log in service._buffer}
        for log_id in first_logs:
            assert log_id not in buffer_ids, f"Log {log_id} should have been evicted"

        # Check that the index doesn't contain stale references
        if "req-123" in service._request_index:
            # None of the evicted logs should be in the index
            for log_id in first_logs:
                assert log_id not in service._request_index["req-123"], f"Evicted log {log_id} still in request index"


@pytest.mark.asyncio
async def test_get_logs_ascending_order():
    """Test getting logs in ascending order."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add some logs
        for i in range(5):
            await service.add_log(level=LogLevel.INFO, message=f"Log {i}")

        result = await service.get_logs(order="asc")

        assert len(result) == 5
        assert result[0]["message"] == "Log 0"  # Oldest first
        assert result[4]["message"] == "Log 4"  # Most recent last


@pytest.mark.asyncio
async def test_get_logs_with_entity_id_no_type():
    """Test filtering logs by entity ID without entity type."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with entity ID but no type
        await service.add_log(
            level=LogLevel.INFO,
            message="Log with just ID",
            entity_id="entity-1",  # No entity_type
        )

        await service.add_log(level=LogLevel.INFO, message="Another log", entity_id="entity-2")

        # Filter by entity ID only
        result = await service.get_logs(entity_id="entity-1")
        assert len(result) == 1
        assert result[0]["message"] == "Log with just ID"


@pytest.mark.asyncio
async def test_remove_from_indices_value_error():
    """Test _remove_from_indices handles ValueError gracefully."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create a log entry
        entry = LogEntry(level=LogLevel.INFO, message="Test", entity_type="tool", entity_id="tool-1", request_id="req-1")

        # Add to indices manually
        service._entity_index["tool:tool-1"] = ["other-id"]  # Wrong ID
        service._request_index["req-1"] = ["other-id"]  # Wrong ID

        # Should not raise ValueError
        service._remove_from_indices(entry)

        # Indices should still have the other ID
        assert "tool:tool-1" in service._entity_index
        assert "req-1" in service._request_index


@pytest.mark.asyncio
async def test_remove_from_indices_empty_cleanup():
    """Test _remove_from_indices removes empty index entries."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create a log entry
        entry = LogEntry(level=LogLevel.INFO, message="Test", entity_type="tool", entity_id="tool-1", request_id="req-1")

        # Add to indices with the correct ID
        service._entity_index["tool:tool-1"] = [entry.id]
        service._request_index["req-1"] = [entry.id]

        # Remove from indices
        service._remove_from_indices(entry)

        # Empty indices should be deleted
        assert "tool:tool-1" not in service._entity_index
        assert "req-1" not in service._request_index


@pytest.mark.asyncio
async def test_notify_subscribers_queue_full():
    """Test _notify_subscribers handles full queues gracefully."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create a queue with size 1
        queue = asyncio.Queue(maxsize=1)

        # Fill it
        await queue.put({"dummy": "data"})

        service._subscribers.append(queue)

        # Create a log entry
        entry = LogEntry(level=LogLevel.INFO, message="Test")

        # Should not raise even though queue is full
        await service._notify_subscribers(entry)

        # Queue should still be in subscribers
        assert queue in service._subscribers


@pytest.mark.asyncio
async def test_notify_subscribers_dead_queue():
    """Test _notify_subscribers removes dead queues."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Create a mock queue that raises an exception
        # Standard
        from unittest.mock import MagicMock

        mock_queue = MagicMock()
        mock_queue.put_nowait.side_effect = Exception("Queue is broken")

        service._subscribers.append(mock_queue)

        # Create a log entry
        entry = LogEntry(level=LogLevel.INFO, message="Test")

        # Should not raise
        await service._notify_subscribers(entry)

        # Dead queue should be removed
        assert mock_queue not in service._subscribers


@pytest.mark.asyncio
async def test_get_stats_with_entities():
    """Test get_stats with entity distribution."""
    with patch("mcpgateway.services.log_storage_service.settings") as mock_settings:
        mock_settings.log_buffer_size_mb = 1.0

        service = LogStorageService()

        # Add logs with different entity types
        await service.add_log(level=LogLevel.INFO, message="Tool log 1", entity_type="tool", entity_id="tool-1")
        await service.add_log(level=LogLevel.INFO, message="Tool log 2", entity_type="tool", entity_id="tool-2")
        await service.add_log(level=LogLevel.INFO, message="Resource log", entity_type="resource", entity_id="res-1")
        await service.add_log(level=LogLevel.INFO, message="No entity log")

        stats = service.get_stats()

        assert stats["entity_distribution"]["tool"] == 2
        assert stats["entity_distribution"]["resource"] == 1
        assert stats["unique_entities"] == 3  # tool:tool-1, tool:tool-2, resource:res-1


@pytest.mark.asyncio
async def test_log_entry_to_dict():
    """Test LogEntry.to_dict method."""
    entry = LogEntry(
        level=LogLevel.WARNING, message="Test warning", entity_type="server", entity_id="server-1", entity_name="Main Server", logger="test.logger", data={"custom": "data"}, request_id="req-abc"
    )

    result = entry.to_dict()

    assert result["id"] == entry.id
    assert result["level"] == LogLevel.WARNING
    assert result["message"] == "Test warning"
    assert result["entity_type"] == "server"
    assert result["entity_id"] == "server-1"
    assert result["entity_name"] == "Main Server"
    assert result["logger"] == "test.logger"
    assert result["data"] == {"custom": "data"}
    assert result["request_id"] == "req-abc"
    assert "timestamp" in result
