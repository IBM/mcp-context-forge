# -*- coding: utf-8 -*-
"""Tests for the metrics buffer service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.metrics_buffer_service import MetricsBufferService


class TestMetricsBufferServiceInit:
    """Tests for MetricsBufferService initialization."""

    def test_init_defaults(self):
        """Test service initialization with defaults."""
        service = MetricsBufferService()

        assert service.enabled is True
        assert service.recording_enabled is True
        assert service.flush_interval == 60
        assert service.max_buffer_size == 1000

    def test_init_custom_values(self):
        """Test service initialization with custom values."""
        service = MetricsBufferService(
            flush_interval=30,
            max_buffer_size=500,
            enabled=False,
        )

        assert service.enabled is False
        assert service.flush_interval == 30
        assert service.max_buffer_size == 500


class TestDbMetricsRecordingEnabled:
    """Tests for DB_METRICS_RECORDING_ENABLED switch."""

    def test_recording_disabled_skips_tool_metric(self):
        """When recording_enabled=False, record_tool_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        # Buffer should remain empty
        assert len(service._tool_metrics) == 0

    def test_recording_disabled_skips_resource_metric(self):
        """When recording_enabled=False, record_resource_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_resource_metric(
            resource_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._resource_metrics) == 0

    def test_recording_disabled_skips_prompt_metric(self):
        """When recording_enabled=False, record_prompt_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_prompt_metric(
            prompt_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._prompt_metrics) == 0

    def test_recording_disabled_skips_server_metric(self):
        """When recording_enabled=False, record_server_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_server_metric(
            server_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._server_metrics) == 0

    def test_recording_disabled_skips_a2a_metric(self):
        """When recording_enabled=False, record_a2a_agent_metric is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_a2a_agent_metric(
            a2a_agent_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._a2a_agent_metrics) == 0

    def test_recording_disabled_skips_a2a_metric_with_duration(self):
        """When recording_enabled=False, record_a2a_agent_metric_with_duration is a no-op."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        service.record_a2a_agent_metric_with_duration(
            a2a_agent_id="test-id",
            response_time=0.5,
            success=True,
        )

        assert len(service._a2a_agent_metrics) == 0

    def test_recording_disabled_immediate_write_skipped(self):
        """When recording_enabled=False and buffer disabled, immediate writes are also skipped."""
        service = MetricsBufferService(enabled=False)  # Buffer disabled = immediate writes
        service.recording_enabled = False

        # This would normally trigger immediate DB write, but should be skipped
        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        # No exception, no write attempted
        assert len(service._tool_metrics) == 0

    def test_recording_enabled_records_normally(self):
        """When recording_enabled=True (default), metrics are recorded."""
        service = MetricsBufferService(enabled=True)
        # recording_enabled defaults to True

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic(),
            success=True,
        )

        assert len(service._tool_metrics) == 1

    def test_get_stats_includes_recording_enabled(self):
        """get_stats() includes recording_enabled status."""
        service = MetricsBufferService(enabled=True)
        stats = service.get_stats()

        assert "recording_enabled" in stats
        assert stats["recording_enabled"] is True

    @pytest.mark.asyncio
    async def test_start_skipped_when_recording_disabled(self):
        """When recording_enabled=False, start() does not create flush task."""
        service = MetricsBufferService(enabled=True)
        service.recording_enabled = False

        await service.start()

        # Flush task should not be created
        assert service._flush_task is None


class TestMetricsBufferServiceRecording:
    """Tests for normal metrics recording."""

    def test_record_tool_metric_with_error(self):
        """Test recording a failed tool metric."""
        service = MetricsBufferService(enabled=True)

        service.record_tool_metric(
            tool_id="test-id",
            start_time=time.monotonic() - 0.5,  # 500ms ago
            success=False,
            error_message="Something went wrong",
        )

        assert len(service._tool_metrics) == 1
        metric = service._tool_metrics[0]
        assert metric.tool_id == "test-id"
        assert metric.is_success is False
        assert metric.error_message == "Something went wrong"
        assert metric.response_time >= 0.5

    def test_record_a2a_metric_with_interaction_type(self):
        """Test recording an A2A metric with custom interaction type."""
        service = MetricsBufferService(enabled=True)

        service.record_a2a_agent_metric(
            a2a_agent_id="agent-123",
            start_time=time.monotonic(),
            success=True,
            interaction_type="stream",
        )

        assert len(service._a2a_agent_metrics) == 1
        metric = service._a2a_agent_metrics[0]
        assert metric.a2a_agent_id == "agent-123"
        assert metric.interaction_type == "stream"

    def test_multiple_metrics_buffered(self):
        """Test that multiple metrics are buffered correctly."""
        service = MetricsBufferService(enabled=True)

        for i in range(5):
            service.record_tool_metric(
                tool_id=f"tool-{i}",
                start_time=time.monotonic(),
                success=True,
            )

        assert len(service._tool_metrics) == 5
        assert service._total_buffered == 5


@pytest.mark.asyncio
async def test_start_creates_flush_task(monkeypatch):
    service = MetricsBufferService(enabled=True)
    service.recording_enabled = True
    service._flush_loop = AsyncMock()

    created = {}

    def _fake_create_task(coro):
        created["coro"] = coro
        task = MagicMock()
        task.done.return_value = False
        return task

    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)
    await service.start()

    assert service._flush_task is not None
    assert created["coro"] is not None
    created["coro"].close()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_flushes(monkeypatch):
    service = MetricsBufferService(enabled=True)

    class DummyTask:
        def __init__(self):
            self.cancel_called = False

        def cancel(self):
            self.cancel_called = True

        def __await__(self):
            async def _noop():
                return None

            return _noop().__await__()

    task = DummyTask()
    service._flush_task = task
    service._flush_all = AsyncMock()

    await service.shutdown()

    assert task.cancel_called is True
    service._flush_all.assert_awaited()


@pytest.mark.asyncio
async def test_flush_all_batches_metrics(monkeypatch):
    service = MetricsBufferService(enabled=True)

    service.record_tool_metric("tool-1", start_time=time.monotonic() - 0.1, success=True)
    service.record_resource_metric("resource-1", start_time=time.monotonic() - 0.2, success=False)

    captured = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    await service._flush_all()

    assert service._total_flushed == 2
    assert service._flush_count == 1
    assert captured["func"] == service._flush_to_db


def test_flush_to_db_writes_batches(monkeypatch):
    service = MetricsBufferService(enabled=True)

    holder = {}

    class DummyDB:
        def __init__(self):
            self.bulk_calls = []
            self.committed = False

        def bulk_insert_mappings(self, model, payload):
            self.bulk_calls.append((model, payload))

        def commit(self):
            self.committed = True

    class DummySession:
        def __enter__(self):
            holder["db"] = DummyDB()
            return holder["db"]

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.metrics_buffer_service.fresh_db_session", lambda: DummySession())

    tool_metric = SimpleNamespace(tool_id="t1", timestamp=time.time(), response_time=0.1, is_success=True, error_message=None)
    resource_metric = SimpleNamespace(resource_id="r1", timestamp=time.time(), response_time=0.2, is_success=False, error_message="err")

    service._flush_to_db([tool_metric], [resource_metric], [], [], [])
    assert holder["db"].committed is True
    assert holder["db"].bulk_calls


def test_record_tool_metric_falls_back_to_immediate_write(monkeypatch):
    service = MetricsBufferService(enabled=False)
    service.recording_enabled = True
    service._write_tool_metric_immediately = MagicMock()

    service.record_tool_metric("tool-1", start_time=time.monotonic(), success=True)

    service._write_tool_metric_immediately.assert_called_once()


def test_get_metrics_buffer_service_singleton(monkeypatch):
    from mcpgateway.services import metrics_buffer_service as mbs

    mbs._metrics_buffer_service = None
    first = mbs.get_metrics_buffer_service()
    second = mbs.get_metrics_buffer_service()
    assert first is second
