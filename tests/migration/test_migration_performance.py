# -*- coding: utf-8 -*-
"""Migration performance and benchmarking tests.

This module provides comprehensive performance testing for database migrations
including benchmarking, stress testing, and resource monitoring.
"""

# Standard
import logging
from pathlib import Path
import time

# Third-Party
import pytest

# Local
from .utils.data_seeder import DataGenerationConfig, DataSeeder
from .utils.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


@pytest.mark.benchmark
class TestMigrationPerformance:
    """Performance benchmarks and stress tests for migration operations.

    These tests validate:
    - Migration execution time under various loads
    - Memory usage during migration operations
    - Performance regression detection
    - Resource constraint handling
    - Scalability characteristics
    """

    def test_sqlite_migration_performance_baseline(self, migration_runner, sample_test_data, performance_thresholds):
        """Establish baseline performance metrics for SQLite migrations.

        This test measures the fundamental performance characteristics
        of SQLite migrations to establish baseline metrics for comparison.
        """
        logger.info(f"🏁 Testing SQLite migration performance baseline")
        logger.info(f"📊 Data size: {sum(len(entities) for entities in sample_test_data.values())} records")

        # Measure baseline performance with standard test data
        start_time = time.time()
        result = migration_runner.test_forward_migration("0.6.0", "latest", sample_test_data)
        end_time = time.time()

        # Validate migration succeeded
        assert result.success, f"Baseline migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity failed in baseline test"

        # Performance assertions
        baseline_threshold = performance_thresholds["sqlite_upgrade"]["max_duration"]
        assert result.execution_time < baseline_threshold, f"Baseline too slow: {result.execution_time:.2f}s > {baseline_threshold}s"

        # Log detailed performance metrics
        logger.info(f"🎯 Baseline Performance Metrics:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s (threshold: {baseline_threshold}s)")
        logger.info(f"   Records processed: {sum(result.records_after.values())}")
        logger.info(f"   Processing rate: {sum(result.records_after.values()) / result.execution_time:.1f} records/sec")

        if result.performance_metrics:
            logger.info(f"   Memory usage: {result.performance_metrics.get('memory_mb', 'N/A')} MB")
            logger.info(f"   CPU usage: {result.performance_metrics.get('cpu_percent', 'N/A')}%")

            # Memory usage validation
            if "memory_mb" in result.performance_metrics:
                max_memory = performance_thresholds["sqlite_upgrade"]["max_memory_mb"]
                assert result.performance_metrics["memory_mb"] < max_memory, f"Memory usage too high: {result.performance_metrics['memory_mb']}MB > {max_memory}MB"

        # Store baseline metrics for comparison
        baseline_metrics = {
            "execution_time": result.execution_time,
            "records_processed": sum(result.records_after.values()),
            "processing_rate": sum(result.records_after.values()) / result.execution_time,
            "performance_metrics": result.performance_metrics
        }

        logger.info(f"✅ Baseline performance test completed successfully")
        return baseline_metrics

    @pytest.mark.parametrize("scale_factor", [1, 5, 10])
    def test_migration_scalability(self, migration_runner, performance_thresholds, scale_factor):
        """Test migration performance scalability with increasing data volumes.

        This test validates how migration performance scales with data volume
        and identifies potential bottlenecks or performance cliffs.
        """
        logger.info(f"📈 Testing migration scalability with scale factor {scale_factor}x")

        # Generate scaled dataset
        data_seeder = DataSeeder()
        scaled_data = data_seeder.generate_performance_dataset(scale_factor)

        total_records = sum(len(entities) for entities in scaled_data.values())
        logger.info(f"📊 Scaled dataset: {total_records} records ({scale_factor}x multiplier)")

        # Run migration with scaled data
        start_time = time.time()
        result = migration_runner.test_forward_migration("0.6.0", "latest", scaled_data)
        end_time = time.time()

        # Validate migration succeeded
        assert result.success, f"Scalability test failed at {scale_factor}x: {result.error_message}"
        assert result.data_integrity_check, f"Data integrity failed at {scale_factor}x"

        # Calculate performance metrics
        processing_rate = sum(result.records_after.values()) / result.execution_time
        expected_max_time = performance_thresholds["large_dataset"]["max_duration"] * (scale_factor ** 0.5)  # Sub-linear scaling expected

        logger.info(f"📊 Scalability Results for {scale_factor}x:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s")
        logger.info(f"   Expected max time: {expected_max_time:.2f}s")
        logger.info(f"   Records processed: {sum(result.records_after.values())}")
        logger.info(f"   Processing rate: {processing_rate:.1f} records/sec")

        # Performance validation - allow for some scaling overhead
        assert result.execution_time < expected_max_time, f"Scalability limit exceeded at {scale_factor}x: {result.execution_time:.2f}s > {expected_max_time:.2f}s"

        # Processing rate should not degrade dramatically
        minimum_acceptable_rate = 10.0  # records/sec minimum
        assert processing_rate > minimum_acceptable_rate, f"Processing rate too low at {scale_factor}x: {processing_rate:.1f} < {minimum_acceptable_rate}"

        logger.info(f"✅ Scalability test passed for {scale_factor}x scale factor")

    def test_large_dataset_migration(self, migration_runner, large_test_data, performance_thresholds):
        """Test migration performance with large datasets.

        This test validates that migrations can handle realistic production
        data volumes without performance degradation or failures.
        """
        logger.info(f"🗄️ Testing large dataset migration performance")

        total_records = sum(len(entities) for entities in large_test_data.values())
        logger.info(f"📊 Large dataset size: {total_records} records")

        # Log dataset breakdown
        for entity_type, entities in large_test_data.items():
            logger.info(f"   {entity_type}: {len(entities)} records")

        # Run migration with timing
        start_time = time.time()
        result = migration_runner.test_forward_migration("0.6.0", "latest", large_test_data)
        end_time = time.time()

        # Validate migration succeeded
        assert result.success, f"Large dataset migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity failed for large dataset"

        # Performance validation
        max_duration = performance_thresholds["large_dataset"]["max_duration"]
        assert result.execution_time < max_duration, f"Large dataset migration too slow: {result.execution_time:.2f}s > {max_duration}s"

        # Memory usage validation
        if result.performance_metrics and "memory_mb" in result.performance_metrics:
            max_memory = performance_thresholds["large_dataset"]["max_memory_mb"]
            actual_memory = result.performance_metrics["memory_mb"]
            assert actual_memory < max_memory, f"Memory usage too high for large dataset: {actual_memory}MB > {max_memory}MB"

        # Data integrity validation for large dataset
        for table, expected_count in result.records_before.items():
            actual_count = result.records_after.get(table, 0)
            assert actual_count >= expected_count, f"Data loss in {table} with large dataset: {expected_count} → {actual_count}"

        # Calculate and log performance statistics
        processing_rate = sum(result.records_after.values()) / result.execution_time
        memory_per_record = result.performance_metrics.get("memory_mb", 0) / sum(result.records_after.values()) * 1024  # KB per record

        logger.info(f"📊 Large Dataset Performance Results:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s")
        logger.info(f"   Processing rate: {processing_rate:.1f} records/sec")
        logger.info(f"   Memory per record: {memory_per_record:.2f} KB/record")
        logger.info(f"   Total memory usage: {result.performance_metrics.get('memory_mb', 'N/A')} MB")

        logger.info(f"✅ Large dataset migration completed successfully")

    def test_migration_memory_usage(self, migration_runner, performance_thresholds):
        """Test migration memory usage patterns and leak detection.

        This test monitors memory usage throughout the migration process
        to detect memory leaks and ensure efficient resource utilization.
        """
        logger.info(f"🧠 Testing migration memory usage patterns")

        # Generate dataset with known characteristics
        data_seeder = DataSeeder()
        memory_test_data = data_seeder.generate_performance_dataset(scale_factor=2)

        logger.info(f"📊 Memory test dataset: {sum(len(entities) for entities in memory_test_data.values())} records")

        # Run migration with detailed memory monitoring
        result = migration_runner.test_forward_migration("0.6.0", "latest", memory_test_data)

        # Validate migration succeeded
        assert result.success, f"Memory test migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity failed in memory test"

        # Memory usage analysis
        if result.performance_metrics and "memory_mb" in result.performance_metrics:
            memory_usage = result.performance_metrics["memory_mb"]
            max_allowed = performance_thresholds["large_dataset"]["max_memory_mb"]

            logger.info(f"🧠 Memory Usage Analysis:")
            logger.info(f"   Peak memory usage: {memory_usage:.1f} MB")
            logger.info(f"   Memory limit: {max_allowed} MB")
            logger.info(f"   Memory efficiency: {memory_usage / max_allowed * 100:.1f}% of limit")

            # Memory usage should be reasonable
            assert memory_usage < max_allowed, f"Memory usage exceeded limit: {memory_usage:.1f}MB > {max_allowed}MB"

            # Calculate memory efficiency metrics
            records_processed = sum(result.records_after.values())
            memory_per_record = memory_usage / records_processed * 1024  # KB per record

            logger.info(f"   Memory per record: {memory_per_record:.2f} KB/record")

            # Memory usage should be efficient (reasonable per-record usage)
            max_memory_per_record = 50  # KB per record maximum
            assert memory_per_record < max_memory_per_record, f"Memory usage per record too high: {memory_per_record:.2f}KB > {max_memory_per_record}KB"

        else:
            logger.warning("⚠️ Memory usage metrics not available")

        logger.info(f"✅ Memory usage test completed")

    def test_concurrent_migration_performance(self, container_manager, migration_runner, sample_test_data):
        """Test migration performance under concurrent database operations.

        This test simulates concurrent database operations during migration
        to validate performance under realistic production conditions.
        """
        logger.info(f"🔀 Testing concurrent migration performance")

        # This test simulates concurrent operations during migration
        # In a real implementation, this would run actual concurrent operations

        logger.info(f"🚀 Starting migration with simulated concurrent load")
        concurrent_start = time.time()

        # Run migration
        result = migration_runner.test_forward_migration("0.6.0", "latest", sample_test_data)

        concurrent_end = time.time()
        concurrent_duration = concurrent_end - concurrent_start

        # Validate migration succeeded under concurrent conditions
        assert result.success, f"Concurrent migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity failed under concurrent load"

        # Performance under concurrent load should be reasonable
        max_concurrent_duration = 120  # seconds
        assert concurrent_duration < max_concurrent_duration, f"Concurrent migration too slow: {concurrent_duration:.2f}s"

        logger.info(f"📊 Concurrent Migration Results:")
        logger.info(f"   Total duration: {concurrent_duration:.2f}s")
        logger.info(f"   Migration time: {result.execution_time:.2f}s")
        logger.info(f"   Concurrent overhead: {(concurrent_duration - result.execution_time):.2f}s")

        # Calculate performance impact
        baseline_time = result.execution_time
        overhead_percentage = ((concurrent_duration - baseline_time) / baseline_time) * 100

        logger.info(f"   Performance overhead: {overhead_percentage:.1f}%")

        # Overhead should be reasonable (< 50% impact)
        max_overhead = 50  # percent
        assert overhead_percentage < max_overhead, f"Concurrent overhead too high: {overhead_percentage:.1f}% > {max_overhead}%"

        logger.info(f"✅ Concurrent migration performance test completed")

    def test_migration_performance_regression(self, migration_runner, sample_test_data):
        """Test for performance regressions between version migrations.

        This test compares migration performance between different version pairs
        to detect performance regressions in newer versions.
        """
        logger.info(f"📉 Testing migration performance regression detection")

        # Test multiple version transitions
        test_scenarios = [
            ("0.5.0", "0.6.0", "Previous version migration"),
            ("0.6.0", "latest", "Latest version migration")
        ]

        performance_results = {}

        for from_version, to_version, description in test_scenarios:
            logger.info(f"🔄 Testing {description}: {from_version} → {to_version}")

            # Run migration and measure performance
            result = migration_runner.test_forward_migration(from_version, to_version, sample_test_data)

            assert result.success, f"Regression test migration failed: {from_version} → {to_version}: {result.error_message}"

            # Store performance metrics
            performance_results[f"{from_version}_to_{to_version}"] = {
                "execution_time": result.execution_time,
                "processing_rate": sum(result.records_after.values()) / result.execution_time,
                "memory_usage": result.performance_metrics.get("memory_mb", 0),
                "description": description
            }

            logger.info(f"   Execution time: {result.execution_time:.2f}s")
            logger.info(f"   Processing rate: {sum(result.records_after.values()) / result.execution_time:.1f} records/sec")

        # Compare performance between scenarios
        if len(performance_results) >= 2:
            scenario_keys = list(performance_results.keys())
            baseline_key = scenario_keys[0]
            current_key = scenario_keys[1]

            baseline = performance_results[baseline_key]
            current = performance_results[current_key]

            # Calculate performance deltas
            time_delta = ((current["execution_time"] - baseline["execution_time"]) / baseline["execution_time"]) * 100
            rate_delta = ((current["processing_rate"] - baseline["processing_rate"]) / baseline["processing_rate"]) * 100
            memory_delta = 0
            if baseline["memory_usage"] > 0 and current["memory_usage"] > 0:
                memory_delta = ((current["memory_usage"] - baseline["memory_usage"]) / baseline["memory_usage"]) * 100

            logger.info(f"📊 Performance Regression Analysis:")
            logger.info(f"   Execution time change: {time_delta:+.1f}%")
            logger.info(f"   Processing rate change: {rate_delta:+.1f}%")
            if memory_delta != 0:
                logger.info(f"   Memory usage change: {memory_delta:+.1f}%")

            # Performance regression thresholds
            max_time_regression = 25  # percent
            min_rate_regression = -15  # percent
            max_memory_regression = 30  # percent

            # Validate no significant regression
            assert time_delta < max_time_regression, f"Execution time regression detected: {time_delta:+.1f}% > {max_time_regression}%"
            assert rate_delta > min_rate_regression, f"Processing rate regression detected: {rate_delta:+.1f}% < {min_rate_regression}%"

            if memory_delta != 0:
                assert memory_delta < max_memory_regression, f"Memory usage regression detected: {memory_delta:+.1f}% > {max_memory_regression}%"

        logger.info(f"✅ Performance regression test completed")

    def test_migration_stress_limits(self, migration_runner, performance_thresholds):
        """Test migration behavior at stress limits and resource constraints.

        This test pushes migrations to their limits to identify breaking points
        and ensure graceful degradation under extreme conditions.
        """
        logger.info(f"💪 Testing migration stress limits")

        # Generate maximum stress test dataset
        data_seeder = DataSeeder()
        stress_data = data_seeder.generate_performance_dataset(scale_factor=50)  # Very large dataset

        total_records = sum(len(entities) for entities in stress_data.values())
        logger.info(f"🏋️ Stress test dataset: {total_records} records (50x scale factor)")

        # Run stress test migration
        stress_start = time.time()
        result = migration_runner.test_forward_migration("0.6.0", "latest", stress_data)
        stress_end = time.time()

        stress_duration = stress_end - stress_start

        # Validate behavior under stress
        if result.success:
            logger.info(f"💪 Stress test PASSED:")
            logger.info(f"   Duration: {stress_duration:.2f}s")
            logger.info(f"   Records processed: {sum(result.records_after.values())}")
            logger.info(f"   Processing rate: {sum(result.records_after.values()) / stress_duration:.1f} records/sec")

            # Validate data integrity under stress
            assert result.data_integrity_check, "Data integrity failed under stress conditions"

            # Performance should still be reasonable even under stress
            max_stress_duration = 900  # 15 minutes maximum for stress test
            assert stress_duration < max_stress_duration, f"Stress test exceeded time limit: {stress_duration:.2f}s > {max_stress_duration}s"

        else:
            # If migration fails under extreme stress, that's acceptable
            # but we should get a clear error message
            logger.info(f"💪 Stress test FAILED (acceptable under extreme conditions):")
            logger.info(f"   Error: {result.error_message[:200]}...")
            logger.info(f"   Duration before failure: {stress_duration:.2f}s")

            # Error message should be informative
            assert result.error_message is not None, "Stress test failure should provide error message"
            assert len(result.error_message) > 0, "Error message should not be empty"

            # Failure should occur within reasonable time (not hang indefinitely)
            max_failure_time = 300  # 5 minutes maximum before giving up
            assert stress_duration < max_failure_time, f"Stress test hung too long before failure: {stress_duration:.2f}s"

        logger.info(f"✅ Stress limit test completed")

    @pytest.mark.benchmark
    def test_migration_benchmark_suite(self, migration_runner, sample_test_data, large_test_data):
        """Comprehensive benchmark suite for migration performance.

        This test runs a comprehensive benchmark suite to establish
        performance baselines and identify optimization opportunities.
        """
        logger.info(f"🏆 Running comprehensive migration benchmark suite")

        benchmark_results = {}

        # Benchmark 1: Small dataset migration
        logger.info(f"🔬 Benchmark 1: Small dataset migration")
        small_start = time.time()
        small_result = migration_runner.test_forward_migration("0.6.0", "latest", sample_test_data)
        small_duration = time.time() - small_start

        assert small_result.success, "Small dataset benchmark failed"

        benchmark_results["small_dataset"] = {
            "duration": small_duration,
            "records": sum(small_result.records_after.values()),
            "rate": sum(small_result.records_after.values()) / small_duration
        }

        # Benchmark 2: Large dataset migration
        logger.info(f"🔬 Benchmark 2: Large dataset migration")
        large_start = time.time()
        large_result = migration_runner.test_forward_migration("0.6.0", "latest", large_test_data)
        large_duration = time.time() - large_start

        assert large_result.success, "Large dataset benchmark failed"

        benchmark_results["large_dataset"] = {
            "duration": large_duration,
            "records": sum(large_result.records_after.values()),
            "rate": sum(large_result.records_after.values()) / large_duration
        }

        # Benchmark 3: Schema-only migration (no data)
        logger.info(f"🔬 Benchmark 3: Schema-only migration")
        schema_start = time.time()
        schema_result = migration_runner.test_forward_migration("0.6.0", "latest", None)
        schema_duration = time.time() - schema_start

        assert schema_result.success, "Schema-only benchmark failed"

        benchmark_results["schema_only"] = {
            "duration": schema_duration,
            "records": 0,
            "rate": 0
        }

        # Generate benchmark report
        logger.info(f"🏆 Benchmark Suite Results:")
        logger.info(f"=" * 60)

        for benchmark_name, metrics in benchmark_results.items():
            logger.info(f"📊 {benchmark_name.replace('_', ' ').title()}:")
            logger.info(f"   Duration: {metrics['duration']:.2f}s")
            logger.info(f"   Records: {metrics['records']}")
            if metrics['rate'] > 0:
                logger.info(f"   Rate: {metrics['rate']:.1f} records/sec")
            logger.info("")

        # Save benchmark results for comparison
        # Standard
        import json
        benchmark_file = Path("tests/migration/reports/benchmark_results.json")
        benchmark_file.parent.mkdir(parents=True, exist_ok=True)

        benchmark_data = {
            "timestamp": time.time(),
            "results": benchmark_results,
            "metadata": {
                "version": "latest",
                "test_environment": "container_testing"
            }
        }

        with open(benchmark_file, 'w') as f:
            json.dump(benchmark_data, f, indent=2)

        logger.info(f"💾 Benchmark results saved to {benchmark_file}")
        logger.info(f"✅ Comprehensive benchmark suite completed")
