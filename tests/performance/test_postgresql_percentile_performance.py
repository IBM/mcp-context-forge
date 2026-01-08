# -*- coding: utf-8 -*-
"""
Performance benchmark test for PostgreSQL percentile_cont optimization.

This test compares the performance of:
1. PostgreSQL native percentile_cont (optimized) - when USE_POSTGRESDB_PERCENTILES=True
2. Python-based percentile calculation (fallback for SQLite or when USE_POSTGRESDB_PERCENTILES=False)

Tests the get_tool_performance, get_prompt_performance, and get_resource_performance
endpoints with varying data volumes to measure the performance improvement.

The USE_POSTGRESDB_PERCENTILES configuration variable controls whether PostgreSQL uses
native percentile_cont functions (5-10x faster) or falls back to Python calculations.
"""

import time
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, ObservabilitySpan, ObservabilityTrace, get_db
from mcpgateway.admin import _get_span_entity_performance
from mcpgateway.config import settings


class TestPostgreSQLPercentilePerformance:
    """Test suite for PostgreSQL percentile_cont performance optimization.

    This test suite validates the USE_POSTGRESDB_PERCENTILES configuration variable
    which controls whether PostgreSQL uses native percentile_cont functions (faster)
    or falls back to Python-based percentile calculations (compatible with SQLite).

    Tests include:
    - Performance comparison between SQLite (Python) and PostgreSQL (native)
    - Verification that USE_POSTGRESDB_PERCENTILES=True uses native percentile_cont
    - Verification that USE_POSTGRESDB_PERCENTILES=False uses Python percentiles
    - Accuracy validation of percentile calculations
    - Concurrent query performance testing
    """

    @pytest.fixture(scope="function")
    def sqlite_engine(self, tmp_path):
        """Create a SQLite test database for each test."""
        db_path = tmp_path / "test_sqlite.db"
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()

    @pytest.fixture(scope="function")
    def postgresql_engine(self):
        """Create a PostgreSQL test database (requires PostgreSQL running)."""
        try:
            # Try to connect to PostgreSQL test database
            engine = create_engine(
                "postgresql://postgres:postgres@localhost:5432/mcpgateway_test",
                echo=False,
                pool_pre_ping=True,
            )
            # Test connection and clean up existing data
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()

            # Recreate tables to ensure clean state
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)

            yield engine

            # Cleanup after test
            Base.metadata.drop_all(engine)
            engine.dispose()
        except Exception as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    def generate_span_data(
        self,
        session: Session,
        entity_type: str,
        num_entities: int,
        spans_per_entity: int,
    ) -> None:
        """Generate observability span test data.

        Args:
            session: Database session
            entity_type: Type of entity (tool, prompt, resource)
            num_entities: Number of unique entities to create
            spans_per_entity: Number of spans per entity
        """
        span_name_map = {
            "tool": "tool.invoke",
            "prompt": "prompt.get",
            "resource": "resource.read",
        }
        json_key_map = {
            "tool": "tool.name",
            "prompt": "prompt.id",
            "resource": "resource.uri",
        }

        span_name = span_name_map[entity_type]
        json_key = json_key_map[entity_type]

        base_time = datetime.now(timezone.utc) - timedelta(hours=24)

        # Create traces first (required by foreign key constraint)
        traces = []
        trace_ids = set()

        for entity_idx in range(num_entities):
            for span_idx in range(spans_per_entity):
                trace_id = f"trace_{entity_idx}_{span_idx}"
                if trace_id not in trace_ids:
                    trace_ids.add(trace_id)
                    timestamp = base_time + timedelta(
                        minutes=entity_idx * spans_per_entity + span_idx
                    )
                    trace = ObservabilityTrace(
                        trace_id=trace_id,
                        name=f"test_trace_{entity_type}",
                        start_time=timestamp.replace(tzinfo=None),
                        end_time=(timestamp + timedelta(minutes=1)).replace(tzinfo=None),
                        status="ok",
                    )
                    traces.append(trace)

        # Insert traces first
        session.bulk_save_objects(traces)
        session.commit()

        # Now create spans
        spans = []
        for entity_idx in range(num_entities):
            entity_id = f"{entity_type}_{entity_idx}"

            for span_idx in range(spans_per_entity):
                # Generate realistic duration distribution
                # Most requests are fast, some are slow
                if span_idx % 10 == 0:  # 10% slow requests
                    duration_ms = 500 + (span_idx % 100) * 10
                else:
                    duration_ms = 50 + (span_idx % 50) * 2

                timestamp = base_time + timedelta(
                    minutes=entity_idx * spans_per_entity + span_idx
                )

                span = ObservabilitySpan(
                    trace_id=f"trace_{entity_idx}_{span_idx}",
                    span_id=f"span_{entity_idx}_{span_idx}",
                    parent_span_id=None,
                    name=span_name,
                    start_time=timestamp.replace(tzinfo=None),
                    end_time=(timestamp + timedelta(milliseconds=duration_ms)).replace(
                        tzinfo=None
                    ),
                    duration_ms=duration_ms,
                    attributes={json_key: entity_id},
                    status="ok",
                )
                spans.append(span)

        # Bulk insert spans
        session.bulk_save_objects(spans)
        session.commit()

    def measure_query_performance(
        self,
        session: Session,
        entity_type: str,
        iterations: int = 5,
    ) -> Tuple[float, List[dict]]:
        """Measure query performance for a given entity type.

        Args:
            session: Database session
            entity_type: Type of entity (tool, prompt, resource)
            iterations: Number of times to run the query

        Returns:
            Tuple of (average_time_ms, sample_results)
        """
        span_name_map = {
            "tool": ["tool.invoke"],
            "prompt": ["prompt.get", "prompts.get", "prompt.render"],
            "resource": ["resource.read", "resources.read", "resource.fetch"],
        }
        json_key_map = {
            "tool": "tool.name",
            "prompt": "prompt.id",
            "resource": "resource.uri",
        }
        result_key_map = {
            "tool": "tool_name",
            "prompt": "prompt_id",
            "resource": "resource_uri",
        }

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_time_naive = cutoff_time.replace(tzinfo=None)

        times = []
        results = None

        for _ in range(iterations):
            start = time.perf_counter()

            results = _get_span_entity_performance(
                db=session,
                cutoff_time=cutoff_time,
                cutoff_time_naive=cutoff_time_naive,
                span_names=span_name_map[entity_type],
                json_key=json_key_map[entity_type],
                result_key=result_key_map[entity_type],
                limit=20,
            )

            end = time.perf_counter()
            times.append((end - start) * 1000)  # Convert to milliseconds

        avg_time = statistics.mean(times)
        return avg_time, results

    @pytest.mark.parametrize(
        "num_entities,spans_per_entity",
        [
            (10, 100),  # Small dataset: 1,000 spans
            (50, 200),  # Medium dataset: 10,000 spans
            (100, 500),  # Large dataset: 50,000 spans
        ],
    )
    def test_tool_performance_comparison(
        self,
        sqlite_engine,
        postgresql_engine,
        num_entities,
        spans_per_entity,
    ):
        """Compare tool performance query between SQLite and PostgreSQL.

        This test verifies that PostgreSQL with USE_POSTGRESDB_PERCENTILES=True
        (using native percentile_cont) is faster than SQLite (using Python percentiles).

        Args:
            sqlite_engine: SQLite database engine
            postgresql_engine: PostgreSQL database engine
            num_entities: Number of tools to create
            spans_per_entity: Number of spans per tool
        """
        total_spans = num_entities * spans_per_entity
        print(f"\n{'='*80}")
        print(f"Testing with {num_entities} tools, {spans_per_entity} spans each")
        print(f"Total spans: {total_spans:,}")
        print(f"{'='*80}")

        # Test SQLite (Python percentile)
        SQLiteSession = sessionmaker(bind=sqlite_engine)
        sqlite_session = SQLiteSession()
        try:
            self.generate_span_data(
                sqlite_session, "tool", num_entities, spans_per_entity
            )
            sqlite_time, sqlite_results = self.measure_query_performance(
                sqlite_session, "tool"
            )
            print(f"\n📊 SQLite (Python percentile):")
            print(f"   Average query time: {sqlite_time:.2f} ms")
            print(f"   Results returned: {len(sqlite_results)}")
            if sqlite_results:
                print(f"   Sample result: {sqlite_results[0]}")
        finally:
            sqlite_session.close()

        # Test PostgreSQL (native percentile_cont when USE_POSTGRESDB_PERCENTILES=True)
        PostgreSQLSession = sessionmaker(bind=postgresql_engine)
        pg_session = PostgreSQLSession()
        try:
            self.generate_span_data(pg_session, "tool", num_entities, spans_per_entity)
            pg_time, pg_results = self.measure_query_performance(pg_session, "tool")
            print(f"\n🚀 PostgreSQL (percentile_cont, USE_POSTGRESDB_PERCENTILES={settings.use_postgresdb_percentiles}):")
            print(f"   Average query time: {pg_time:.2f} ms")
            print(f"   Results returned: {len(pg_results)}")
            if pg_results:
                print(f"   Sample result: {pg_results[0]}")
        finally:
            pg_session.close()

        # Calculate improvement
        if sqlite_time > 0:
            speedup = sqlite_time / pg_time
            improvement_pct = ((sqlite_time - pg_time) / sqlite_time) * 100
            print(f"\n✨ Performance Improvement:")
            print(f"   Speedup: {speedup:.2f}x faster")
            print(f"   Time saved: {improvement_pct:.1f}%")
            print(f"   Absolute difference: {sqlite_time - pg_time:.2f} ms")

        # Verify both returned results
        assert len(sqlite_results) > 0, "SQLite should return results"
        assert len(pg_results) > 0, "PostgreSQL should return results"

        # PostgreSQL applies LIMIT in SQL, SQLite returns all then limits in Python
        # So we just verify both have results and compare the first entity
        print(f"\n📊 Result counts: SQLite={len(sqlite_results)}, PostgreSQL={len(pg_results)}")

        if sqlite_results and pg_results:
            # Compare first result's metrics (both should have same first entity)
            sqlite_first = sqlite_results[0]
            pg_first = pg_results[0]

            # Count should match exactly (same data in both databases)
            assert sqlite_first["count"] == pg_first["count"], f"Count mismatch: SQLite={sqlite_first['count']}, PG={pg_first['count']}"

            # Percentiles should be close (within 5%)
            for metric in ["p50", "p90", "p95", "p99"]:
                sqlite_val = sqlite_first[metric]
                pg_val = pg_first[metric]
                if sqlite_val > 0:
                    diff_pct = abs(sqlite_val - pg_val) / sqlite_val * 100
                    assert (
                        diff_pct < 5
                    ), f"{metric} differs by {diff_pct:.1f}% (SQLite: {sqlite_val}, PG: {pg_val})"

        # PostgreSQL should be faster for larger datasets
        if total_spans >= 10000:
            assert (
                pg_time < sqlite_time
            ), f"PostgreSQL should be faster for {total_spans:,} spans"

    @pytest.mark.parametrize("entity_type", ["tool", "prompt", "resource"])
    def test_all_entity_types_performance(
        self, postgresql_engine, entity_type
    ):
        """Test performance for all entity types with PostgreSQL.

        Args:
            postgresql_engine: PostgreSQL database engine
            entity_type: Type of entity to test
        """
        num_entities = 50
        spans_per_entity = 200
        total_spans = num_entities * spans_per_entity

        print(f"\n{'='*80}")
        print(f"Testing {entity_type} performance with PostgreSQL")
        print(f"Entities: {num_entities}, Spans per entity: {spans_per_entity}")
        print(f"Total spans: {total_spans:,}")
        print(f"{'='*80}")

        PostgreSQLSession = sessionmaker(bind=postgresql_engine)
        session = PostgreSQLSession()
        try:
            self.generate_span_data(session, entity_type, num_entities, spans_per_entity)
            avg_time, results = self.measure_query_performance(session, entity_type)

            print(f"\n🚀 PostgreSQL {entity_type} performance:")
            print(f"   Average query time: {avg_time:.2f} ms")
            print(f"   Results returned: {len(results)}")
            if results:
                print(f"   Sample result: {results[0]}")

            # Performance assertions (soft thresholds - warn but don't fail on timing)
            if avg_time >= 1000:
                print(f"   ⚠️  Warning: Query took {avg_time:.2f}ms (target: <1000ms)")
            assert len(results) > 0, "Should return results"
            assert len(results) <= 20, "Should respect limit"

            # Verify result structure
            if results:
                result = results[0]
                required_keys = [
                    "count",
                    "avg_duration_ms",
                    "min_duration_ms",
                    "max_duration_ms",
                    "p50",
                    "p90",
                    "p95",
                    "p99",
                ]
                for key in required_keys:
                    assert key in result, f"Result missing {key}"
                    assert isinstance(
                        result[key], (int, float)
                    ), f"{key} should be numeric"

        finally:
            session.close()

    def test_percentile_accuracy(self, postgresql_engine):
        """Verify that PostgreSQL percentile_cont produces accurate results.

        Args:
            postgresql_engine: PostgreSQL database engine
        """
        print(f"\n{'='*80}")
        print("Testing percentile calculation accuracy")
        print(f"{'='*80}")

        PostgreSQLSession = sessionmaker(bind=postgresql_engine)
        session = PostgreSQLSession()
        try:
            # Generate controlled dataset with known percentiles
            # Create 100 spans with durations from 1 to 100
            base_time = datetime.now(timezone.utc) - timedelta(hours=1)

            # Create traces first
            traces = []
            for i in range(100):
                trace = ObservabilityTrace(
                    trace_id=f"trace_{i}",
                    name="test_trace_accuracy",
                    start_time=base_time.replace(tzinfo=None),
                    end_time=(base_time + timedelta(minutes=1)).replace(tzinfo=None),
                    status="ok",
                )
                traces.append(trace)

            session.bulk_save_objects(traces)
            session.commit()

            # Now create spans
            spans = []
            for i in range(100):
                duration_ms = i + 1  # 1, 2, 3, ..., 100
                span = ObservabilitySpan(
                    trace_id=f"trace_{i}",
                    span_id=f"span_{i}",
                    parent_span_id=None,
                    name="tool.invoke",
                    start_time=base_time.replace(tzinfo=None),
                    end_time=(base_time + timedelta(milliseconds=duration_ms)).replace(
                        tzinfo=None
                    ),
                    duration_ms=duration_ms,
                    attributes={"tool.name": "test_tool"},
                    status="ok",
                )
                spans.append(span)

            session.bulk_save_objects(spans)
            session.commit()

            # Query performance
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)
            cutoff_time_naive = cutoff_time.replace(tzinfo=None)

            results = _get_span_entity_performance(
                db=session,
                cutoff_time=cutoff_time,
                cutoff_time_naive=cutoff_time_naive,
                span_names=["tool.invoke"],
                json_key="tool.name",
                result_key="tool_name",
                limit=20,
            )

            assert len(results) == 1
            result = results[0]

            print(f"\n📊 Percentile Results:")
            print(f"   Count: {result['count']}")
            print(f"   Min: {result['min_duration_ms']}")
            print(f"   P50 (median): {result['p50']}")
            print(f"   P90: {result['p90']}")
            print(f"   P95: {result['p95']}")
            print(f"   P99: {result['p99']}")
            print(f"   Max: {result['max_duration_ms']}")

            # Verify expected values (with small tolerance for floating point)
            assert result["count"] == 100
            assert result["min_duration_ms"] == 1.0
            assert result["max_duration_ms"] == 100.0
            assert 50 <= result["p50"] <= 51  # Median should be ~50.5
            assert 90 <= result["p90"] <= 91  # P90 should be ~90.1
            assert 95 <= result["p95"] <= 96  # P95 should be ~95.05
            assert 99 <= result["p99"] <= 100  # P99 should be ~99.01

            print(f"\n✅ Percentile calculations are accurate!")

        finally:
            session.close()

    def test_concurrent_query_performance(self, postgresql_engine):
        """Test performance under concurrent load.

        Args:
            postgresql_engine: PostgreSQL database engine
        """
        import concurrent.futures

        print(f"\n{'='*80}")
        print("Testing concurrent query performance")
        print(f"{'='*80}")

        PostgreSQLSession = sessionmaker(bind=postgresql_engine)
        session = PostgreSQLSession()
        try:
            # Generate test data
            self.generate_span_data(session, "tool", 100, 500)
            session.close()

            # Run concurrent queries
            num_concurrent = 10
            times = []

            def run_query():
                session = PostgreSQLSession()
                try:
                    start = time.perf_counter()
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                    cutoff_time_naive = cutoff_time.replace(tzinfo=None)

                    _get_span_entity_performance(
                        db=session,
                        cutoff_time=cutoff_time,
                        cutoff_time_naive=cutoff_time_naive,
                        span_names=["tool.invoke"],
                        json_key="tool.name",
                        result_key="tool_name",
                        limit=20,
                    )
                    end = time.perf_counter()
                    return (end - start) * 1000
                finally:
                    session.close()

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=num_concurrent
            ) as executor:
                futures = [executor.submit(run_query) for _ in range(num_concurrent)]
                times = [f.result() for f in concurrent.futures.as_completed(futures)]

            avg_time = statistics.mean(times)
            max_time = max(times)
            min_time = min(times)

            print(f"\n🔄 Concurrent Query Results ({num_concurrent} concurrent):")
            print(f"   Average time: {avg_time:.2f} ms")
            print(f"   Min time: {min_time:.2f} ms")
            print(f"   Max time: {max_time:.2f} ms")
            print(f"   Std dev: {statistics.stdev(times):.2f} ms")

            # Performance thresholds (soft - warn but don't fail on timing variance across environments)
            if avg_time >= 2000:
                print(f"   ⚠️  Warning: Average query time {avg_time:.2f}ms exceeds target (<2000ms)")
            if max_time >= 5000:
                print(f"   ⚠️  Warning: Max query time {max_time:.2f}ms exceeds target (<5000ms)")

        finally:
            pass

    def test_use_postgresdb_percentiles_toggle(self, postgresql_engine):
        """Test that USE_POSTGRESDB_PERCENTILES configuration controls percentile calculation method.

        This test verifies:
        1. When USE_POSTGRESDB_PERCENTILES=True, PostgreSQL uses native percentile_cont
        2. When USE_POSTGRESDB_PERCENTILES=False, PostgreSQL falls back to Python percentiles
        3. Both methods produce similar results but native is faster

        Note:
            This test works because extract_json_field() now accepts dialect_name parameter,
            and _get_span_entity_performance() passes the session's actual dialect to it.

        Args:
            postgresql_engine: PostgreSQL database engine
        """
        print(f"\n{'='*80}")
        print("Testing USE_POSTGRESDB_PERCENTILES configuration toggle")
        print(f"{'='*80}")

        num_entities = 50
        spans_per_entity = 200
        total_spans = num_entities * spans_per_entity

        PostgreSQLSession = sessionmaker(bind=postgresql_engine)
        session = PostgreSQLSession()

        try:
            # Generate test data once
            self.generate_span_data(session, "tool", num_entities, spans_per_entity)

            # Store original setting
            original_setting = settings.use_postgresdb_percentiles

            # Test with USE_POSTGRESDB_PERCENTILES=True (native percentile_cont)
            settings.use_postgresdb_percentiles = True
            print(f"\n🚀 Testing with USE_POSTGRESDB_PERCENTILES=True (native percentile_cont)")
            native_time, native_results = self.measure_query_performance(session, "tool")
            print(f"   Average query time: {native_time:.2f} ms")
            print(f"   Results returned: {len(native_results)}")
            if native_results:
                print(f"   Sample result: {native_results[0]}")

            # Test with USE_POSTGRESDB_PERCENTILES=False (Python percentiles)
            settings.use_postgresdb_percentiles = False
            print(f"\n📊 Testing with USE_POSTGRESDB_PERCENTILES=False (Python percentiles)")
            python_time, python_results = self.measure_query_performance(session, "tool")
            print(f"   Average query time: {python_time:.2f} ms")
            print(f"   Results returned: {len(python_results)}")
            if python_results:
                print(f"   Sample result: {python_results[0]}")

            # Restore original setting
            settings.use_postgresdb_percentiles = original_setting

            # Calculate performance difference
            if python_time > 0:
                speedup = python_time / native_time
                improvement_pct = ((python_time - native_time) / python_time) * 100
                print(f"\n✨ Performance Comparison:")
                print(f"   Native percentile_cont speedup: {speedup:.2f}x faster")
                print(f"   Time saved: {improvement_pct:.1f}%")
                print(f"   Absolute difference: {python_time - native_time:.2f} ms")

            # Verify both methods return results
            assert len(native_results) > 0, "Native method should return results"
            assert len(python_results) > 0, "Python method should return results"

            # Verify results are similar (percentiles should be close)
            if native_results and python_results:
                native_first = native_results[0]
                python_first = python_results[0]

                # Count should match exactly
                assert native_first["count"] == python_first["count"], \
                    f"Count mismatch: Native={native_first['count']}, Python={python_first['count']}"

                # Percentiles should be close (within 5%)
                for metric in ["p50", "p90", "p95", "p99"]:
                    native_val = native_first[metric]
                    python_val = python_first[metric]
                    if native_val > 0:
                        diff_pct = abs(native_val - python_val) / native_val * 100
                        assert diff_pct < 5, \
                            f"{metric} differs by {diff_pct:.1f}% (Native: {native_val}, Python: {python_val})"

                print(f"\n✅ Both methods produce similar results (within 5% tolerance)")

            # Native should be faster for this dataset size
            assert native_time < python_time, \
                f"Native percentile_cont should be faster than Python percentiles for {total_spans:,} spans"

            print(f"\n✅ USE_POSTGRESDB_PERCENTILES configuration works correctly!")

        finally:
            session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

# Made with Bob
