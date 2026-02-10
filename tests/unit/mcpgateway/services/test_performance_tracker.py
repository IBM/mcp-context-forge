# -*- coding: utf-8 -*-
"""Tests for the Performance Tracker Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from collections import deque
from unittest.mock import patch

# Third-Party
import pytest

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
            # Internal _operation_timings is a defaultdict of deques
            assert isinstance(tracker._operation_timings, dict)

            # Use public API to add timing, then verify internal structure
            tracker.record_timing("test_operation", 1.0)
            assert isinstance(tracker._operation_timings["test_operation"], deque)
            assert tracker._operation_timings["test_operation"].maxlen == 500

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
    """Tests for automatic buffer eviction behavior with deque.

    Note: These tests verify internal deque behavior and buffer limits.
    They use the public API (record_timing) to add data and verify internal state.
    """

    def test_buffer_automatically_evicts_oldest_when_full(self):
        """Test that deque automatically evicts oldest items when maxlen is reached."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 5  # Small buffer for testing
            tracker = PerformanceTracker()

            operation_name = "test_operation"

            # Add 10 items via public API (twice the maxlen)
            for i in range(10):
                tracker.record_timing(operation_name, float(i))

            # Should only have last 5 items
            assert len(tracker._operation_timings[operation_name]) == 5
            assert list(tracker._operation_timings[operation_name]) == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_buffer_size_never_exceeds_maxlen(self):
        """Test that buffer size never exceeds maxlen regardless of append count."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            with patch("mcpgateway.services.performance_tracker.getattr") as mock_getattr:

                def getattr_side_effect(_obj, attr, default=None):
                    if attr == "perf_max_samples_per_operation":
                        return 100
                    return default

                mock_getattr.side_effect = getattr_side_effect
                tracker = PerformanceTracker()

                operation_name = "database_query"

                # Add 1000 items via public API (10x maxlen)
                for i in range(1000):
                    tracker.record_timing(operation_name, float(i))

                # Should never exceed maxlen
                assert len(tracker._operation_timings[operation_name]) == 100
                # Should contain last 100 items
                expected = list(range(900, 1000))
                assert list(tracker._operation_timings[operation_name]) == [float(x) for x in expected]

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

                # Record 5 timings via public API
                for i in range(5):
                    tracker.record_timing(operation_name, float(i))

                # Should only have last 3
                assert len(tracker._operation_timings[operation_name]) == 3
                assert list(tracker._operation_timings[operation_name]) == [2.0, 3.0, 4.0]

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

                # Track 5 operations via public API
                for _ in range(5):
                    with tracker.track_operation(operation_name, log_slow=False):
                        pass  # Minimal operation

                # Should only have last 3 timings
                assert len(tracker._operation_timings[operation_name]) == 3

    def test_multiple_operations_have_independent_buffers(self):
        """Test that different operations have independent buffers with same maxlen."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 5
            tracker = PerformanceTracker()

            # Add to multiple operations via public API
            for i in range(10):
                tracker.record_timing("op1", float(i))
                tracker.record_timing("op2", float(i * 2))

            # Each should have only 5 items
            assert len(tracker._operation_timings["op1"]) == 5
            assert len(tracker._operation_timings["op2"]) == 5

            # Each should have different values
            assert list(tracker._operation_timings["op1"]) == [5.0, 6.0, 7.0, 8.0, 9.0]
            assert list(tracker._operation_timings["op2"]) == [10.0, 12.0, 14.0, 16.0, 18.0]


class TestDequeOperations:
    """Tests for deque-specific operations and compatibility.

    Note: These tests verify internal deque behavior and buffer limits.
    """

    def test_record_timing_keeps_buffer_bounded_under_load(self):
        """Test that record_timing keeps buffer size bounded under heavy use."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 1000
            tracker = PerformanceTracker()

            operation_name = "performance_test"

            # Fill the buffer via public API
            for i in range(1000):
                tracker.record_timing(operation_name, float(i))

            # Perform many record_timing calls when buffer is full
            for i in range(10000):
                tracker.record_timing(operation_name, float(i))

            # Verify buffer maintained correct size
            assert len(tracker._operation_timings[operation_name]) == 1000

    def test_get_statistics_works_with_deque(self):
        """Test that get_statistics works correctly with deque."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            operation_name = "test_stats"

            # Add some timings via public API
            for i in range(50):
                tracker.record_timing(operation_name, float(i))

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

            # Add historical timings (faster) via public API - need more than 10 for proper comparison
            for _ in range(50):
                tracker.record_timing(operation_name, 0.1)

            # Add recent timings (slower - 3x to ensure detection)
            for _ in range(10):
                tracker.record_timing(operation_name, 0.3)

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


class TestSummaryCaching:
    """Tests for the version-based performance summary caching functionality.

    These tests verify the cache versioning mechanism. Most tests use the public API
    (record_timing) to add data. A few tests need to verify version mechanics directly
    and access internal state (_op_version, _summary_cache) for assertions.
    """

    def test_cache_hit_returns_equivalent_data(self):
        """Test that repeated calls without mutations return equivalent cached data."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summary twice - second should use cache (versions match)
            summary1 = tracker.get_performance_summary("test_op")
            summary2 = tracker.get_performance_summary("test_op")

            # Should be equivalent but not the same object (copy returned)
            assert summary1 == summary2
            assert summary1 is not summary2

            # Cache should have entry
            assert len(tracker._summary_cache) == 1

    def test_cache_invalidates_after_record_timing(self):
        """Test that cache is invalidated after record_timing()."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add initial timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summary to populate cache
            tracker.get_performance_summary("test_op")
            cache_key = ("test_op", 1)
            old_version = tracker._summary_cache[cache_key][0]

            # Record new timing - increments version
            tracker.record_timing("test_op", 100.0)

            # Cache entry still exists but version is stale
            # Next get_performance_summary will recompute
            summary2 = tracker.get_performance_summary("test_op")
            new_version = tracker._summary_cache[cache_key][0]

            # Version should have incremented
            assert new_version > old_version

            # Summary should reflect the new timing
            assert summary2["test_op"]["count"] == 11

    def test_cache_invalidates_after_track_operation(self):
        """Test that cache is invalidated after track_operation()."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add initial timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summary to populate cache
            tracker.get_performance_summary("test_op")
            cache_key = ("test_op", 1)
            old_version = tracker._summary_cache[cache_key][0]

            # Track new operation - increments version
            with tracker.track_operation("test_op", log_slow=False):
                pass

            # Version should have incremented
            assert tracker._op_version["test_op"] > old_version

    def test_cache_invalidates_after_clear_stats_specific(self):
        """Test that cache is invalidated after clear_stats() for specific operation."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings for two operations via public API
            for i in range(10):
                tracker.record_timing("op1", float(i))
                tracker.record_timing("op2", float(i))

            # Get summaries to populate cache
            tracker.get_performance_summary("op1")
            tracker.get_performance_summary("op2")
            op1_version = tracker._op_version["op1"]
            op2_version = tracker._op_version["op2"]

            # Clear stats for op1 only
            tracker.clear_stats("op1")

            # op1 version should increment, op2 should remain
            assert tracker._op_version["op1"] > op1_version
            assert tracker._op_version["op2"] == op2_version

    def test_cache_invalidates_after_clear_stats_all(self):
        """Test that cache is invalidated after clear_stats() for all operations."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings for two operations via public API
            for i in range(10):
                tracker.record_timing("op1", float(i))
                tracker.record_timing("op2", float(i))

            # Get summaries to populate cache
            tracker.get_performance_summary("op1")
            tracker.get_performance_summary("op2")
            tracker.get_performance_summary()  # All operations
            assert len(tracker._summary_cache) == 3

            # Clear all stats
            tracker.clear_stats()

            # All cache entries should be cleared
            assert len(tracker._summary_cache) == 0
            # Op versions should be cleared
            assert len(tracker._op_version) == 0

    def test_cache_invalidates_after_set_threshold(self):
        """Test that cache is invalidated after set_threshold()."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summary to populate cache
            tracker.get_performance_summary("test_op")
            old_version = tracker._op_version["test_op"]

            # Change threshold - increments version
            tracker.set_threshold("test_op", 0.5)

            # Version should have incremented
            assert tracker._op_version["test_op"] > old_version

    def test_cache_respects_min_samples_parameter(self):
        """Test that different min_samples produce independent cache entries."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summaries with different min_samples
            summary_min1 = tracker.get_performance_summary("test_op", min_samples=1)
            summary_min5 = tracker.get_performance_summary("test_op", min_samples=5)

            # Both should be cached separately
            assert ("test_op", 1) in tracker._summary_cache
            assert ("test_op", 5) in tracker._summary_cache
            assert len(tracker._summary_cache) == 2

            # Summaries should be equivalent (both have 10 samples)
            assert summary_min1 == summary_min5

    def test_cache_returns_copies_to_prevent_mutation(self):
        """Test that modifying returned summary doesn't affect cache."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings via public API
            for i in range(10):
                tracker.record_timing("test_op", float(i))

            # Get summary and modify it
            summary1 = tracker.get_performance_summary("test_op")
            original_count = summary1["test_op"]["count"]
            summary1["test_op"]["count"] = 999

            # Get summary again - should not be affected by mutation
            summary2 = tracker.get_performance_summary("test_op")
            assert summary2["test_op"]["count"] == original_count

    def test_all_operations_uses_global_version(self):
        """Test that 'all operations' summary uses global version for cache validation."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings for two operations via public API
            for i in range(10):
                tracker.record_timing("op1", float(i))
                tracker.record_timing("op2", float(i))

            # Get all operations summary to populate cache
            tracker.get_performance_summary()
            old_global_version = tracker._global_version

            # Record timing for op1 - increments global version
            tracker.record_timing("op1", 100.0)

            # Global version should have incremented
            assert tracker._global_version > old_global_version

            # Next all-ops summary will recompute
            summary = tracker.get_performance_summary()
            assert summary["op1"]["count"] == 11

    def test_specific_op_cache_not_affected_by_other_op_changes(self):
        """Test that specific operation cache remains valid when other operations change."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings for two operations via public API
            for i in range(10):
                tracker.record_timing("op1", float(i))
                tracker.record_timing("op2", float(i))

            # Get op1 summary to populate cache
            tracker.get_performance_summary("op1")
            op1_cache_key = ("op1", 1)

            # Record timing for op2 - should NOT affect op1's cache
            tracker.record_timing("op2", 100.0)

            # op1's cached version should still match current version
            op1_current_version = tracker._op_version["op1"]
            assert op1_cache_key in tracker._summary_cache
            assert tracker._summary_cache[op1_cache_key][0] == op1_current_version

            # Getting op1 summary should return cached result (no recompute)
            summary = tracker.get_performance_summary("op1")
            assert summary["op1"]["count"] == 10  # Still 10, not affected by op2

    def test_unknown_operation_uses_all_operations_cache_key(self):
        """Test that querying unknown operation normalizes to all-operations cache key."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Add timings for a real operation via public API
            for i in range(10):
                tracker.record_timing("real_op", float(i))

            # Query for non-existent operation - should fall back to all operations
            summary = tracker.get_performance_summary("nonexistent_op")

            # Should use _ALL_OPERATIONS_KEY, not "nonexistent_op"
            assert ("nonexistent_op", 1) not in tracker._summary_cache
            assert (tracker._ALL_OPERATIONS_KEY, 1) in tracker._summary_cache

            # Summary should contain the real operation
            assert "real_op" in summary

    def test_version_increments_are_independent_per_operation(self):
        """Test that version increments for one operation don't affect others."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Record timings for op1 multiple times
            for _ in range(5):
                tracker.record_timing("op1", 1.0)

            # Record timing for op2 once
            tracker.record_timing("op2", 1.0)

            # op1 should have version 5, op2 should have version 1
            assert tracker._op_version["op1"] == 5
            assert tracker._op_version["op2"] == 1

            # Global version should be 6 (5 + 1)
            assert tracker._global_version == 6

    def test_cache_evicts_oldest_entries_when_full(self):
        """Test that cache evicts oldest entries when exceeding max size."""
        with patch("mcpgateway.services.performance_tracker.settings") as mock_settings:
            mock_settings.perf_max_samples_per_operation = 100
            tracker = PerformanceTracker()

            # Temporarily lower max cache entries for testing
            original_max = tracker._MAX_CACHE_ENTRIES
            tracker._MAX_CACHE_ENTRIES = 5

            try:
                # Add timing data
                tracker.record_timing("test_op", 1.0)

                # Fill cache with different min_samples values
                for min_samples in range(10):
                    tracker.get_performance_summary("test_op", min_samples=min_samples)

                # Cache should be bounded
                assert len(tracker._summary_cache) <= 5

                # Most recent entries should still be present
                assert ("test_op", 9) in tracker._summary_cache
            finally:
                tracker._MAX_CACHE_ENTRIES = original_max


class TestPerformanceTrackerExtraCoverage:
    def test_track_operation_reraises_exception_and_records_timing(self):
        tracker = PerformanceTracker()
        operation = "test_op_error"

        with pytest.raises(RuntimeError, match="boom"):
            with tracker.track_operation(operation, log_slow=False):
                raise RuntimeError("boom")

        assert len(tracker._operation_timings[operation]) == 1

    def test_track_operation_logs_when_threshold_exceeded_and_merges_extra_context(self):
        tracker = PerformanceTracker()
        operation = "database_query"
        tracker.performance_thresholds[operation] = 0.0  # Force threshold_exceeded

        with patch("mcpgateway.services.performance_tracker.get_correlation_id", return_value="cid"), patch("mcpgateway.services.performance_tracker.time.time", side_effect=[0.0, 1.0]), patch(
            "mcpgateway.services.performance_tracker.logger.warning"
        ) as warn:
            with tracker.track_operation(operation, component="svc", extra_context={"foo": "bar"}):
                pass

        warn.assert_called()
        extra = warn.call_args.kwargs.get("extra", {})
        assert extra.get("foo") == "bar"
        assert extra.get("error_occurred") is False

    def test_record_timing_logs_and_merges_extra_context(self):
        tracker = PerformanceTracker()
        tracker.performance_thresholds["op"] = 0.0

        with patch("mcpgateway.services.performance_tracker.get_correlation_id", return_value="cid"), patch("mcpgateway.services.performance_tracker.logger.warning") as warn:
            tracker.record_timing("op", 1.0, component="svc", extra_context={"foo": "bar"})

        warn.assert_called()
        extra = warn.call_args.kwargs.get("extra", {})
        assert extra.get("foo") == "bar"

    def test_get_performance_summary_cache_eviction_handles_popitem_errors(self):
        tracker = PerformanceTracker()
        tracker._MAX_CACHE_ENTRIES = 0
        tracker.get_performance_summary()
        assert tracker._summary_cache

    def test_get_operation_stats_returns_none_for_unknown_or_empty(self):
        tracker = PerformanceTracker()
        assert tracker.get_operation_stats("missing") is None
        tracker._operation_timings["empty_op"]  # create empty deque
        assert tracker.get_operation_stats("empty_op") is None

    def test_check_performance_degradation_no_data_and_insufficient_samples(self):
        tracker = PerformanceTracker()
        assert tracker.check_performance_degradation("missing") == {"degraded": False, "reason": "no_data"}

        for _ in range(9):
            tracker.record_timing("op", 0.1)

        assert tracker.check_performance_degradation("op") == {"degraded": False, "reason": "insufficient_samples"}

    def test_check_performance_degradation_insufficient_historical_data(self):
        tracker = PerformanceTracker()
        for _ in range(10):
            tracker.record_timing("op", 0.1)

        assert tracker.check_performance_degradation("op") == {"degraded": False, "reason": "insufficient_historical_data"}
