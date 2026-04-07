# -*- coding: utf-8 -*-
"""Tests for MetricBuffer utility class.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

# First-Party
from mcpgateway.db import ServerMetric, ToolMetric
from mcpgateway.utils.metric_buffer import MetricBuffer


class TestMetricBuffer:
    """Tests for MetricBuffer class."""

    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        session = MagicMock()
        session.execute = MagicMock()
        session.commit = MagicMock()
        session.__enter__ = MagicMock(return_value=MagicMock())
        session.__exit__ = MagicMock(return_value=False)

        factory = MagicMock(return_value=session)
        return factory

    @pytest.fixture
    def metric_buffer(self, mock_session_factory):
        """Create a MetricBuffer instance with small batch size for testing."""
        return MetricBuffer(mock_session_factory, ToolMetric, batch_size=5)

    def test_init_default_batch_size(self, mock_session_factory):
        """Should initialize with default batch size of 1000."""
        buffer = MetricBuffer(mock_session_factory, ToolMetric)
        assert buffer.batch_size == 1000
        assert buffer.buffer == []
        assert buffer.total_added == 0
        assert buffer.total_flushed == 0
        assert buffer.flush_count == 0

    def test_init_custom_batch_size(self, mock_session_factory):
        """Should initialize with custom batch size."""
        buffer = MetricBuffer(mock_session_factory, ToolMetric, batch_size=500)
        assert buffer.batch_size == 500

    def test_add_single_metric_no_flush(self, metric_buffer, mock_session_factory):
        """Should add metric without flushing when below batch size."""
        metric_data = {
            "tool_id": "test-uuid-1",
            "timestamp": datetime.now(timezone.utc),
            "response_time": 1.5,
            "is_success": True,
            "error_message": None,
        }

        metric_buffer.add(metric_data)

        assert len(metric_buffer.buffer) == 1
        assert metric_buffer.total_added == 1
        # Session should not be called yet
        mock_session_factory.assert_not_called()

    def test_add_multiple_metrics_no_flush(self, metric_buffer, mock_session_factory):
        """Should add multiple metrics without flushing when below batch size."""
        for i in range(4):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        assert len(metric_buffer.buffer) == 4
        assert metric_buffer.total_added == 4
        mock_session_factory.assert_not_called()

    def test_add_triggers_auto_flush_at_batch_size(self, metric_buffer, mock_session_factory):
        """Should automatically flush when batch size is reached."""
        # Add metrics up to batch size
        for i in range(5):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        # Buffer should be empty after auto-flush
        assert len(metric_buffer.buffer) == 0
        assert metric_buffer.total_added == 5
        assert metric_buffer.total_flushed == 5
        assert metric_buffer.flush_count == 1

        # Session should have been called
        mock_session_factory.assert_called_once()

    def test_flush_empty_buffer_no_op(self, metric_buffer, mock_session_factory):
        """Should do nothing when flushing empty buffer."""
        metric_buffer.flush()

        assert len(metric_buffer.buffer) == 0
        assert metric_buffer.total_flushed == 0
        assert metric_buffer.flush_count == 0
        mock_session_factory.assert_not_called()

    def test_flush_partial_buffer(self, metric_buffer, mock_session_factory):
        """Should flush all buffered metrics even when below batch size."""
        # Add 3 metrics
        for i in range(3):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        # Manually flush
        metric_buffer.flush()

        assert len(metric_buffer.buffer) == 0
        assert metric_buffer.total_added == 3
        assert metric_buffer.total_flushed == 3
        assert metric_buffer.flush_count == 1

    def test_flush_restores_buffer_on_failure(self, metric_buffer, mock_session_factory):
        """Should restore buffer on flush failure to prevent data loss."""
        # Add 2 metrics
        for i in range(2):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        # Make session fail
        mock_session_factory.side_effect = Exception("Database error")

        # Flush should raise exception
        with pytest.raises(Exception, match="Database error"):
            metric_buffer.flush()

        # Buffer should be restored
        assert len(metric_buffer.buffer) == 2
        assert metric_buffer.total_flushed == 0

    def test_get_stats(self, metric_buffer, mock_session_factory):
        """Should return correct statistics."""
        # Add some metrics
        for i in range(3):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        stats = metric_buffer.get_stats()

        assert stats["model"] == "tool_metrics"
        assert stats["batch_size"] == 5
        assert stats["current_buffer_size"] == 3
        assert stats["total_added"] == 3
        assert stats["total_flushed"] == 0
        assert stats["flush_count"] == 0

    def test_get_stats_after_flush(self, metric_buffer, mock_session_factory):
        """Should update statistics after flush."""
        # Add and flush metrics
        for i in range(7):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        stats = metric_buffer.get_stats()

        # 5 flushed, 2 remaining in buffer
        assert stats["current_buffer_size"] == 2
        assert stats["total_added"] == 7
        assert stats["total_flushed"] == 5
        assert stats["flush_count"] == 1

    def test_thread_safety(self, mock_session_factory):
        """Should be thread-safe for concurrent access."""
        # Standard
        import threading

        buffer = MetricBuffer(mock_session_factory, ToolMetric, batch_size=100)
        num_threads = 10
        metrics_per_thread = 10

        def add_metrics(thread_id):
            for i in range(metrics_per_thread):
                buffer.add({
                    "tool_id": f"thread-{thread_id}-metric-{i}",
                    "timestamp": datetime.now(timezone.utc),
                    "response_time": float(i),
                    "is_success": True,
                })

        # Create and start threads
        threads = []
        for t in range(num_threads):
            thread = threading.Thread(target=add_metrics, args=(t,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Total added should be correct
        assert buffer.total_added == num_threads * metrics_per_thread

    def test_server_metric_buffer(self, mock_session_factory):
        """Should work with ServerMetric model."""
        buffer = MetricBuffer(mock_session_factory, ServerMetric, batch_size=3)

        for i in range(3):
            buffer.add({
                "server_id": f"server-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        # Should have auto-flushed
        assert len(buffer.buffer) == 0
        assert buffer.total_flushed == 3
        assert buffer.flush_count == 1

    def test_multiple_flushes(self, metric_buffer, mock_session_factory):
        """Should handle multiple flushes correctly."""
        # Add 12 metrics (should trigger 2 auto-flushes at batch_size=5)
        for i in range(12):
            metric_buffer.add({
                "tool_id": f"test-uuid-{i}",
                "timestamp": datetime.now(timezone.utc),
                "response_time": float(i),
                "is_success": True,
            })

        # 10 flushed in 2 batches, 2 remaining
        assert len(metric_buffer.buffer) == 2
        assert metric_buffer.total_flushed == 10
        assert metric_buffer.flush_count == 2

        # Manual flush of remaining
        metric_buffer.flush()
        assert len(metric_buffer.buffer) == 0
        assert metric_buffer.total_flushed == 12
        assert metric_buffer.flush_count == 3

    @patch("mcpgateway.utils.metric_buffer.logger")
    def test_logs_error_on_flush_failure(self, mock_logger, metric_buffer, mock_session_factory):
        """Should log error on flush failure."""
        # Add metric
        metric_buffer.add({
            "tool_id": "test-uuid",
            "timestamp": datetime.now(timezone.utc),
            "response_time": 1.0,
            "is_success": True,
        })

        # Make session fail
        mock_session_factory.side_effect = Exception("DB connection failed")

        with pytest.raises(Exception):
            metric_buffer.flush()

        # Error should be logged
        mock_logger.error.assert_called_once()
        assert "Failed to flush" in mock_logger.error.call_args[0][0]
