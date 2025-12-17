# -*- coding: utf-8 -*-
"""Tests for Performance Monitoring Schemas.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    WorkerMetrics,
    SystemMetricsSchema,
    RequestMetricsSchema,
    DatabaseMetricsSchema,
    CacheMetricsSchema,
    GunicornMetricsSchema,
    PerformanceSnapshotCreate,
    PerformanceSnapshotRead,
    PerformanceAggregateBase,
    PerformanceAggregateCreate,
    PerformanceAggregateRead,
    PerformanceDashboard,
    PerformanceHistoryParams,
    PerformanceHistoryResponse,
)


class TestWorkerMetrics:
    """Tests for WorkerMetrics schema."""

    def test_create_worker_metrics_minimal(self):
        """Test creating WorkerMetrics with minimal data."""
        metrics = WorkerMetrics(
            pid=1234,
            cpu_percent=10.5,
            memory_rss_mb=256.0,
            memory_vms_mb=512.0,
            threads=4,
        )
        assert metrics.pid == 1234
        assert metrics.cpu_percent == 10.5
        assert metrics.memory_rss_mb == 256.0
        assert metrics.threads == 4
        assert metrics.connections == 0
        assert metrics.status == "running"

    def test_create_worker_metrics_full(self):
        """Test creating WorkerMetrics with all fields."""
        now = datetime.now(timezone.utc)
        metrics = WorkerMetrics(
            pid=1234,
            cpu_percent=25.5,
            memory_rss_mb=512.0,
            memory_vms_mb=1024.0,
            threads=8,
            connections=10,
            open_fds=50,
            status="sleeping",
            create_time=now,
            uptime_seconds=3600,
        )
        assert metrics.pid == 1234
        assert metrics.open_fds == 50
        assert metrics.status == "sleeping"
        assert metrics.uptime_seconds == 3600

    def test_worker_metrics_model_dump(self):
        """Test model_dump for WorkerMetrics."""
        metrics = WorkerMetrics(
            pid=1234,
            cpu_percent=10.5,
            memory_rss_mb=256.0,
            memory_vms_mb=512.0,
            threads=4,
        )
        data = metrics.model_dump()
        assert isinstance(data, dict)
        assert data["pid"] == 1234
        assert data["cpu_percent"] == 10.5


class TestSystemMetricsSchema:
    """Tests for SystemMetricsSchema."""

    def test_create_system_metrics_minimal(self):
        """Test creating SystemMetricsSchema with minimal data."""
        metrics = SystemMetricsSchema(
            cpu_percent=50.0,
            cpu_count=8,
            memory_total_mb=16384,
            memory_used_mb=8192,
            memory_available_mb=8192,
            memory_percent=50.0,
            disk_total_gb=500.0,
            disk_used_gb=250.0,
            disk_percent=50.0,
        )
        assert metrics.cpu_percent == 50.0
        assert metrics.cpu_count == 8
        assert metrics.memory_total_mb == 16384
        assert metrics.disk_total_gb == 500.0

    def test_create_system_metrics_with_optional_fields(self):
        """Test creating SystemMetricsSchema with optional fields."""
        boot_time = datetime.now(timezone.utc)
        metrics = SystemMetricsSchema(
            cpu_percent=50.0,
            cpu_count=8,
            cpu_freq_mhz=3200.0,
            load_avg_1m=1.5,
            load_avg_5m=2.0,
            load_avg_15m=1.8,
            memory_total_mb=16384,
            memory_used_mb=8192,
            memory_available_mb=8192,
            memory_percent=50.0,
            swap_total_mb=8192,
            swap_used_mb=1024,
            disk_total_gb=500.0,
            disk_used_gb=250.0,
            disk_percent=50.0,
            network_bytes_sent=1000000,
            network_bytes_recv=2000000,
            network_connections=100,
            boot_time=boot_time,
        )
        assert metrics.cpu_freq_mhz == 3200.0
        assert metrics.load_avg_1m == 1.5
        assert metrics.swap_total_mb == 8192
        assert metrics.network_bytes_sent == 1000000
        assert metrics.boot_time == boot_time


class TestRequestMetricsSchema:
    """Tests for RequestMetricsSchema."""

    def test_create_request_metrics_defaults(self):
        """Test creating RequestMetricsSchema with defaults."""
        metrics = RequestMetricsSchema()
        assert metrics.requests_total == 0
        assert metrics.requests_per_second == 0
        assert metrics.error_rate == 0

    def test_create_request_metrics_with_values(self):
        """Test creating RequestMetricsSchema with values."""
        metrics = RequestMetricsSchema(
            requests_total=10000,
            requests_per_second=100.5,
            requests_1xx=10,
            requests_2xx=9500,
            requests_3xx=100,
            requests_4xx=300,
            requests_5xx=90,
            response_time_avg_ms=50.5,
            response_time_p50_ms=45.0,
            response_time_p95_ms=150.0,
            response_time_p99_ms=500.0,
            error_rate=3.9,
            active_requests=5,
        )
        assert metrics.requests_total == 10000
        assert metrics.requests_2xx == 9500
        assert metrics.error_rate == 3.9


class TestDatabaseMetricsSchema:
    """Tests for DatabaseMetricsSchema."""

    def test_create_database_metrics_defaults(self):
        """Test creating DatabaseMetricsSchema with defaults."""
        metrics = DatabaseMetricsSchema()
        assert metrics.pool_size == 0
        assert metrics.connections_in_use == 0
        assert metrics.query_count == 0

    def test_create_database_metrics_with_values(self):
        """Test creating DatabaseMetricsSchema with values."""
        metrics = DatabaseMetricsSchema(
            pool_size=20,
            connections_in_use=5,
            connections_available=15,
            overflow=2,
            query_count=1000,
            query_avg_time_ms=5.5,
        )
        assert metrics.pool_size == 20
        assert metrics.connections_in_use == 5
        assert metrics.query_avg_time_ms == 5.5


class TestCacheMetricsSchema:
    """Tests for CacheMetricsSchema."""

    def test_create_cache_metrics_defaults(self):
        """Test creating CacheMetricsSchema with defaults."""
        metrics = CacheMetricsSchema()
        assert metrics.connected is False
        assert metrics.version is None
        assert metrics.hit_rate == 0

    def test_create_cache_metrics_connected(self):
        """Test creating CacheMetricsSchema for connected Redis."""
        metrics = CacheMetricsSchema(
            connected=True,
            version="7.0.0",
            used_memory_mb=128.5,
            connected_clients=10,
            ops_per_second=500,
            hit_rate=95.5,
            keyspace_hits=10000,
            keyspace_misses=500,
        )
        assert metrics.connected is True
        assert metrics.version == "7.0.0"
        assert metrics.hit_rate == 95.5


class TestGunicornMetricsSchema:
    """Tests for GunicornMetricsSchema."""

    def test_create_gunicorn_metrics_defaults(self):
        """Test creating GunicornMetricsSchema with defaults."""
        metrics = GunicornMetricsSchema()
        assert metrics.master_pid is None
        assert metrics.workers_total == 0

    def test_create_gunicorn_metrics_with_values(self):
        """Test creating GunicornMetricsSchema with values."""
        metrics = GunicornMetricsSchema(
            master_pid=1000,
            workers_total=4,
            workers_active=3,
            workers_idle=1,
            max_requests=10000,
        )
        assert metrics.master_pid == 1000
        assert metrics.workers_total == 4


class TestPerformanceSnapshotSchemas:
    """Tests for PerformanceSnapshot schemas."""

    def test_create_snapshot_create(self):
        """Test creating PerformanceSnapshotCreate."""
        snapshot = PerformanceSnapshotCreate(
            host="test-host",
            worker_id="1234",
            metrics_json={"cpu_percent": 50.0},
        )
        assert snapshot.host == "test-host"
        assert snapshot.worker_id == "1234"
        assert "cpu_percent" in snapshot.metrics_json

    def test_create_snapshot_read(self):
        """Test creating PerformanceSnapshotRead."""
        now = datetime.now(timezone.utc)
        snapshot = PerformanceSnapshotRead(
            id=1,
            timestamp=now,
            host="test-host",
            worker_id="1234",
            metrics_json={"cpu_percent": 50.0},
            created_at=now,
        )
        assert snapshot.id == 1
        assert snapshot.host == "test-host"


class TestPerformanceAggregateSchemas:
    """Tests for PerformanceAggregate schemas."""

    def test_create_aggregate_base(self):
        """Test creating PerformanceAggregateBase."""
        now = datetime.now(timezone.utc)
        aggregate = PerformanceAggregateBase(
            period_start=now,
            period_end=now,
            period_type="hourly",
        )
        assert aggregate.period_type == "hourly"
        assert aggregate.requests_total == 0

    def test_create_aggregate_with_metrics(self):
        """Test creating PerformanceAggregateCreate with metrics."""
        now = datetime.now(timezone.utc)
        aggregate = PerformanceAggregateCreate(
            period_start=now,
            period_end=now,
            period_type="hourly",
            host="test-host",
            requests_total=1000,
            requests_2xx=950,
            requests_4xx=30,
            requests_5xx=20,
            avg_response_time_ms=50.0,
            p95_response_time_ms=150.0,
            peak_requests_per_second=100.0,
            avg_cpu_percent=30.0,
            avg_memory_percent=40.0,
            peak_cpu_percent=75.0,
            peak_memory_percent=60.0,
        )
        assert aggregate.requests_total == 1000
        assert aggregate.avg_cpu_percent == 30.0

    def test_create_aggregate_read(self):
        """Test creating PerformanceAggregateRead."""
        now = datetime.now(timezone.utc)
        aggregate = PerformanceAggregateRead(
            id=1,
            period_start=now,
            period_end=now,
            period_type="hourly",
            created_at=now,
        )
        assert aggregate.id == 1
        assert aggregate.period_type == "hourly"


class TestPerformanceDashboard:
    """Tests for PerformanceDashboard schema."""

    def test_create_dashboard(self):
        """Test creating PerformanceDashboard."""
        now = datetime.now(timezone.utc)
        dashboard = PerformanceDashboard(
            timestamp=now,
            uptime_seconds=3600,
            host="test-host",
            system=SystemMetricsSchema(
                cpu_percent=50.0,
                cpu_count=8,
                memory_total_mb=16384,
                memory_used_mb=8192,
                memory_available_mb=8192,
                memory_percent=50.0,
                disk_total_gb=500.0,
                disk_used_gb=250.0,
                disk_percent=50.0,
            ),
            requests=RequestMetricsSchema(),
            database=DatabaseMetricsSchema(),
            cache=CacheMetricsSchema(),
            gunicorn=GunicornMetricsSchema(),
        )
        assert dashboard.host == "test-host"
        assert dashboard.uptime_seconds == 3600
        assert dashboard.system.cpu_percent == 50.0

    def test_dashboard_with_workers(self):
        """Test PerformanceDashboard with workers."""
        now = datetime.now(timezone.utc)
        workers = [
            WorkerMetrics(pid=1001, cpu_percent=10.0, memory_rss_mb=256.0, memory_vms_mb=512.0, threads=4),
            WorkerMetrics(pid=1002, cpu_percent=15.0, memory_rss_mb=512.0, memory_vms_mb=1024.0, threads=8),
        ]
        dashboard = PerformanceDashboard(
            timestamp=now,
            uptime_seconds=3600,
            host="test-host",
            system=SystemMetricsSchema(
                cpu_percent=50.0,
                cpu_count=8,
                memory_total_mb=16384,
                memory_used_mb=8192,
                memory_available_mb=8192,
                memory_percent=50.0,
                disk_total_gb=500.0,
                disk_used_gb=250.0,
                disk_percent=50.0,
            ),
            requests=RequestMetricsSchema(),
            database=DatabaseMetricsSchema(),
            cache=CacheMetricsSchema(),
            gunicorn=GunicornMetricsSchema(),
            workers=workers,
            cluster_hosts=["host1", "host2"],
            is_distributed=True,
        )
        assert len(dashboard.workers) == 2
        assert dashboard.is_distributed is True


class TestPerformanceHistorySchemas:
    """Tests for PerformanceHistory schemas."""

    def test_history_params_defaults(self):
        """Test PerformanceHistoryParams with defaults."""
        params = PerformanceHistoryParams()
        assert params.period_type == "hourly"
        assert params.limit == 168
        assert params.start_time is None

    def test_history_params_custom(self):
        """Test PerformanceHistoryParams with custom values."""
        now = datetime.now(timezone.utc)
        params = PerformanceHistoryParams(
            start_time=now,
            end_time=now,
            period_type="daily",
            host="test-host",
            limit=100,
        )
        assert params.period_type == "daily"
        assert params.limit == 100
        assert params.host == "test-host"

    def test_history_response_empty(self):
        """Test PerformanceHistoryResponse with no data."""
        response = PerformanceHistoryResponse(
            aggregates=[],
            period_type="hourly",
            total_count=0,
        )
        assert len(response.aggregates) == 0
        assert response.total_count == 0

    def test_history_response_with_data(self):
        """Test PerformanceHistoryResponse with aggregates."""
        now = datetime.now(timezone.utc)
        aggregates = [
            PerformanceAggregateRead(
                id=1,
                period_start=now,
                period_end=now,
                period_type="hourly",
                created_at=now,
            ),
            PerformanceAggregateRead(
                id=2,
                period_start=now,
                period_end=now,
                period_type="hourly",
                created_at=now,
            ),
        ]
        response = PerformanceHistoryResponse(
            aggregates=aggregates,
            period_type="hourly",
            total_count=100,
        )
        assert len(response.aggregates) == 2
        assert response.total_count == 100
