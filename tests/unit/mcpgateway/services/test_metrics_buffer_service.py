# -*- coding: utf-8 -*-
"""Tests for the metrics buffer service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import time

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
