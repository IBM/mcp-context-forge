# -*- coding: utf-8 -*-
"""Tests for the Performance Tracker Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import time
from collections import deque
from unittest.mock import patch

# First-Party
from mcpgateway.services.performance_tracker import get_performance_tracker, PerformanceTracker


class TestPerformanceTrackerInit:
    """Tests for PerformanceTracker initialization."""

    def test_init_creates_deque_with_maxlen(self):
        """Test that initialization creates deque with maxlen from settings."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 500
            tracker = PerformanceTracker()

            assert tracker.max_samples == 500
            assert isinstance(tracker.operation_timings, dict)

            # Add an item to trigger defaultdict factory
            tracker.operation_timings["test_operation"].append(1.0)
            assert isinstance(tracker.operation_timings["test_operation"], deque)
            assert tracker.operation_timings["test_operation"].maxlen == 500

    def test_init_uses_default_max_samples(self):
        """Test that initialization uses default 1000 if setting not present."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            # Simulate setting not being present
            mock_settings.perf_max_samples_per_operation = None
            type(mock_settings).perf_max_samples_per_operation = property(lambda self: getattr(self, "_perf_max_samples_per_operation", None))

            with patch("mcpgateway.services.performance_tracker.getattr") as mock_getattr:
                mock_getattr.return_value = 1000
                tracker = PerformanceTracker()
                assert tracker.max_samples == 1000


class TestBufferEviction:
    """Tests for automatic buffer eviction behavior with deque."""

    def test_buffer_automatically_evicts_oldest_when_full(self):
        """Test that deque automatically evicts oldest items when maxlen is reached."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 5  # Small buffer for testing
            tracker = PerformanceTracker()

            operation_name = "test_operation"

            # Add 10 items (twice the maxlen)
            for i in range(10):
                tracker.operation_timings[operation_name].append(float(i))

            # Should only have last 5 items
            assert len(tracker.operation_timings[operation_name]) == 5
            assert list(tracker.operation_timings[operation_name]) == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_buffer_size_never_exceeds_maxlen(self):
        """Test that buffer size never exceeds maxlen regardless of append count."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            operation_name = "database_query"

            # Add 1000 items (10x maxlen)
            for i in range(1000):
                tracker.operation_timings[operation_name].append(float(i))

            # Should never exceed maxlen
            assert len(tracker.operation_timings[operation_name]) == 100
            # Should contain last 100 items
            expected = list(range(900, 1000))
            assert list(tracker.operation_timings[operation_name]) == [float(x) for x in expected]

    def test_record_timing_respects_buffer_limit(self):
        """Test that record_timing method respects buffer size limit."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 3
            # Mock getattr to return proper threshold values
            with patch("mcpgateway.services.performance_tracker.getattr") as mock_getattr:

                def getattr_side_effect(_obj, attr, default=None):
                    if attr == "perf_max_samples_per_operation":
                        return 3
                    return default

                mock_getattr.side_effect = getattr_side_effect

                tracker = PerformanceTracker()

                operation_name = "tool_invocation"

                # Record 5 timings
                for i in range(5):
                    tracker.record_timing(operation_name, float(i))

                # Should only have last 3
                assert len(tracker.operation_timings[operation_name]) == 3
                assert list(tracker.operation_timings[operation_name]) == [2.0, 3.0, 4.0]

    def test_track_operation_context_manager_respects_buffer_limit(self):
        """Test that track_operation context manager respects buffer size limit."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 3
            # Mock getattr to return proper threshold values
            with patch("mcpgateway.services.performance_tracker.getattr") as mock_getattr:

                def getattr_side_effect(_obj, attr, default=None):
                    if attr == "perf_max_samples_per_operation":
                        return 3
                    return default

                mock_getattr.side_effect = getattr_side_effect

                tracker = PerformanceTracker()

                operation_name = "cache_operation"

                # Track 5 operations
                for _ in range(5):
                    with tracker.track_operation(operation_name, log_slow=False):
                        pass  # Minimal operation

                # Should only have last 3 timings
                assert len(tracker.operation_timings[operation_name]) == 3

    def test_multiple_operations_have_independent_buffers(self):
        """Test that different operations have independent buffers with same maxlen."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 5
            tracker = PerformanceTracker()

            # Add to multiple operations
            for i in range(10):
                tracker.operation_timings["op1"].append(float(i))
                tracker.operation_timings["op2"].append(float(i * 2))

            # Each should have only 5 items
            assert len(tracker.operation_timings["op1"]) == 5
            assert len(tracker.operation_timings["op2"]) == 5

            # Each should have different values
            assert list(tracker.operation_timings["op1"]) == [5.0, 6.0, 7.0, 8.0, 9.0]
            assert list(tracker.operation_timings["op2"]) == [10.0, 12.0, 14.0, 16.0, 18.0]


class TestDequeOperations:
    """Tests for deque-specific operations and compatibility."""

    def test_deque_append_is_o1(self):
        """Test that appending to full deque is O(1) by measuring many operations."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 1000
            tracker = PerformanceTracker()

            operation_name = "performance_test"

            # Fill the buffer
            for i in range(1000):
                tracker.operation_timings[operation_name].append(float(i))

            # Measure time for many appends when buffer is full
            start = time.time()
            for i in range(10000):
                tracker.operation_timings[operation_name].append(float(i))
            duration = time.time() - start

            # Should complete quickly (< 0.1 seconds for 10k operations)
            # This would timeout with O(n) list.pop(0) approach
            assert duration < 0.1, f"Append operations too slow: {duration}s for 10k items"

    def test_get_statistics_works_with_deque(self):
        """Test that get_statistics works correctly with deque."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            operation_name = "test_stats"

            # Add some timings
            for i in range(50):
                tracker.operation_timings[operation_name].append(float(i))

            stats = tracker.get_operation_stats(operation_name)

            assert stats["sample_count"] == 50
            assert stats["avg_duration_ms"] == 24.5 * 1000  # Average of 0-49 converted to ms
            assert stats["min_duration_ms"] == 0.0
            assert stats["max_duration_ms"] == 49.0 * 1000

    def test_check_performance_degradation_works_with_deque(self):
        """Test that check_performance_degradation works with deque after list conversion."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            operation_name = "degradation_test"

            # Add historical timings (faster) - need more than 10 for proper comparison
            for _ in range(50):
                tracker.operation_timings[operation_name].append(0.1)

            # Add recent timings (slower - 3x to ensure detection)
            for _ in range(10):
                tracker.operation_timings[operation_name].append(0.3)

            result = tracker.check_performance_degradation(operation_name)

            # Should detect degradation (recent avg is 3x historical, exceeds 2x threshold)
            assert result["degraded"] is True


class TestSingletonPattern:
    """Tests for the singleton get_performance_tracker function."""

    def test_get_performance_tracker_returns_same_instance(self):
        """Test that get_performance_tracker returns the same instance."""
        tracker1 = get_performance_tracker()
        tracker2 = get_performance_tracker()

        assert tracker1 is tracker2

    def test_get_performance_tracker_returns_performance_tracker(self):
        """Test that get_performance_tracker returns PerformanceTracker instance."""
        tracker = get_performance_tracker()

        assert isinstance(tracker, PerformanceTracker)
