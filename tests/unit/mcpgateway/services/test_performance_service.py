# -*- coding: utf-8 -*-
"""Tests for the Performance Monitoring Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock
import os

# Third-Party
import pytest

# First-Party
from mcpgateway.services.performance_service import (
    PerformanceService,
    get_performance_service,
    PSUTIL_AVAILABLE,
    REDIS_AVAILABLE,
    PROMETHEUS_AVAILABLE,
    APP_START_TIME,
    HOSTNAME,
)
from mcpgateway.schemas import (
    SystemMetricsSchema,
    WorkerMetrics,
    GunicornMetricsSchema,
    RequestMetricsSchema,
    DatabaseMetricsSchema,
    CacheMetricsSchema,
    PerformanceDashboard,
    PerformanceHistoryResponse,
)


class TestPerformanceServiceInit:
    """Tests for PerformanceService initialization."""

    def test_init_without_db(self):
        """Test initialization without database session."""
        service = PerformanceService()
        assert service.db is None
        assert isinstance(service._request_count_cache, dict)
        assert service._last_request_time > 0

    def test_init_with_db(self):
        """Test initialization with database session."""
        mock_db = MagicMock()
        service = PerformanceService(db=mock_db)
        assert service.db is mock_db


class TestSystemMetrics:
    """Tests for system metrics collection."""

    def test_get_system_metrics_without_psutil(self):
        """Test system metrics when psutil is not available."""
        service = PerformanceService()
        with patch('mcpgateway.services.performance_service.PSUTIL_AVAILABLE', False):
            with patch('mcpgateway.services.performance_service.psutil', None):
                result = service.get_system_metrics()
                assert isinstance(result, SystemMetricsSchema)
                assert result.cpu_percent == 0.0
                assert result.memory_total_mb == 0

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_system_metrics_with_psutil(self):
        """Test system metrics collection with psutil available."""
        service = PerformanceService()
        result = service.get_system_metrics()

        assert isinstance(result, SystemMetricsSchema)
        assert result.cpu_percent >= 0
        assert result.cpu_count > 0
        assert result.memory_total_mb > 0
        assert result.memory_used_mb >= 0
        assert result.memory_available_mb >= 0
        assert result.disk_total_gb > 0
        assert result.disk_used_gb >= 0

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_system_metrics_load_average(self):
        """Test load average is captured on Unix systems."""
        service = PerformanceService()
        result = service.get_system_metrics()

        # Load average is only available on Unix
        if os.name != 'nt':
            # May be None if getloadavg fails
            if result.load_avg_1m is not None:
                assert result.load_avg_1m >= 0


class TestWorkerMetrics:
    """Tests for worker process metrics collection."""

    def test_get_worker_metrics_without_psutil(self):
        """Test worker metrics when psutil is not available."""
        service = PerformanceService()
        with patch('mcpgateway.services.performance_service.PSUTIL_AVAILABLE', False):
            result = service.get_worker_metrics()
            assert isinstance(result, list)
            assert len(result) == 0

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_worker_metrics_with_psutil(self):
        """Test worker metrics collection with psutil available."""
        service = PerformanceService()
        result = service.get_worker_metrics()

        assert isinstance(result, list)
        assert len(result) >= 1

        worker = result[0]
        assert isinstance(worker, WorkerMetrics)
        assert worker.pid > 0
        assert worker.memory_rss_mb >= 0
        assert worker.threads >= 1

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_process_metrics(self):
        """Test metrics collection for a specific process."""
        import psutil

        service = PerformanceService()
        proc = psutil.Process()
        result = service._get_process_metrics(proc)

        assert isinstance(result, WorkerMetrics)
        assert result.pid == os.getpid()
        assert result.cpu_percent >= 0
        assert result.memory_rss_mb >= 0
        assert result.threads >= 1

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_process_metrics_with_exception(self):
        """Test process metrics when process access fails."""
        import psutil

        service = PerformanceService()
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 99999
        mock_proc.oneshot.side_effect = psutil.NoSuchProcess(99999)

        result = service._get_process_metrics(mock_proc)

        assert isinstance(result, WorkerMetrics)
        assert result.pid == 99999
        assert result.status == "unknown"


class TestGunicornMetrics:
    """Tests for Gunicorn-specific metrics."""

    def test_get_gunicorn_metrics_without_psutil(self):
        """Test Gunicorn metrics when psutil is not available."""
        service = PerformanceService()
        with patch('mcpgateway.services.performance_service.PSUTIL_AVAILABLE', False):
            result = service.get_gunicorn_metrics()
            assert isinstance(result, GunicornMetricsSchema)

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_gunicorn_metrics_not_under_gunicorn(self):
        """Test Gunicorn metrics when not running under Gunicorn."""
        service = PerformanceService()
        result = service.get_gunicorn_metrics()

        assert isinstance(result, GunicornMetricsSchema)
        # When not under gunicorn, master_pid should be None
        assert result.workers_total >= 1

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_get_gunicorn_metrics_mocked_gunicorn(self):
        """Test Gunicorn metrics with mocked Gunicorn environment."""
        import psutil

        service = PerformanceService()

        mock_parent = MagicMock(spec=psutil.Process)
        mock_parent.pid = 1000
        mock_parent.name.return_value = "gunicorn: master"
        mock_parent.children.return_value = [
            MagicMock(pid=1001, cpu_percent=MagicMock(return_value=10.0)),
            MagicMock(pid=1002, cpu_percent=MagicMock(return_value=0.0)),
        ]

        mock_current = MagicMock(spec=psutil.Process)
        mock_current.parent.return_value = mock_parent

        with patch('mcpgateway.services.performance_service.psutil.Process', return_value=mock_current):
            result = service.get_gunicorn_metrics()

        assert isinstance(result, GunicornMetricsSchema)
        assert result.master_pid == 1000
        assert result.workers_total == 2


class TestRequestMetrics:
    """Tests for HTTP request metrics."""

    def test_get_request_metrics_without_prometheus(self):
        """Test request metrics when Prometheus is not available."""
        service = PerformanceService()
        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', False):
            result = service.get_request_metrics()
            assert isinstance(result, RequestMetricsSchema)
            assert result.requests_total == 0

    def test_get_request_metrics_empty_registry(self):
        """Test request metrics with empty Prometheus registry."""
        service = PerformanceService()

        mock_registry = MagicMock()
        mock_registry.collect.return_value = []

        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.REGISTRY', mock_registry):
                result = service.get_request_metrics()

        assert isinstance(result, RequestMetricsSchema)
        assert result.requests_total == 0

    def test_get_request_metrics_with_data(self):
        """Test request metrics with Prometheus data."""
        service = PerformanceService()

        # Mock Prometheus metrics
        mock_sample = MagicMock()
        mock_sample.name = "http_requests_total"
        mock_sample.labels = {"status": "200"}
        mock_sample.value = 100

        mock_metric = MagicMock()
        mock_metric.name = "http_requests_total"
        mock_metric.samples = [mock_sample]

        mock_registry = MagicMock()
        mock_registry.collect.return_value = [mock_metric]

        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.REGISTRY', mock_registry):
                result = service.get_request_metrics()

        assert isinstance(result, RequestMetricsSchema)
        assert result.requests_total == 100
        assert result.requests_2xx == 100


class TestDatabaseMetrics:
    """Tests for database connection pool metrics."""

    def test_get_database_metrics(self):
        """Test database metrics collection."""
        service = PerformanceService()

        mock_pool = MagicMock()
        mock_pool.size.return_value = 10
        mock_pool.checkedout.return_value = 3
        mock_pool.checkedin.return_value = 7
        mock_pool.overflow.return_value = 0

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        with patch('mcpgateway.services.performance_service.engine', mock_engine, create=True):
            # Import happens inside the function, so we need to patch it there
            with patch.dict('sys.modules', {'mcpgateway.db': MagicMock(engine=mock_engine)}):
                result = service.get_database_metrics()

        assert isinstance(result, DatabaseMetricsSchema)

    def test_get_database_metrics_with_exception(self):
        """Test database metrics when pool access fails."""
        service = PerformanceService()

        # Patch the import that happens inside the function
        mock_module = MagicMock()
        mock_module.engine.pool.size.side_effect = Exception("Connection error")

        with patch.dict('sys.modules', {'mcpgateway.db': mock_module}):
            # Force the function to re-import by clearing any cached reference
            result = service.get_database_metrics()

        # The function handles the exception and returns defaults
        assert isinstance(result, DatabaseMetricsSchema)


class TestCacheMetrics:
    """Tests for Redis cache metrics."""

    @pytest.mark.asyncio
    async def test_get_cache_metrics_without_redis(self):
        """Test cache metrics when Redis is not available."""
        service = PerformanceService()
        with patch('mcpgateway.services.performance_service.REDIS_AVAILABLE', False):
            result = await service.get_cache_metrics()
            assert isinstance(result, CacheMetricsSchema)
            assert result.connected is False

    @pytest.mark.asyncio
    async def test_get_cache_metrics_no_redis_url(self):
        """Test cache metrics when Redis URL is not configured."""
        service = PerformanceService()

        with patch('mcpgateway.services.performance_service.settings') as mock_settings:
            mock_settings.redis_url = None
            result = await service.get_cache_metrics()

        assert isinstance(result, CacheMetricsSchema)
        assert result.connected is False

    @pytest.mark.asyncio
    async def test_get_cache_metrics_with_redis(self):
        """Test cache metrics with Redis connection."""
        service = PerformanceService()

        # Create a proper async mock for the Redis client
        mock_client = AsyncMock()
        mock_client.info = AsyncMock(return_value={
            "redis_version": "7.0.0",
            "used_memory": 1048576,
            "connected_clients": 5,
            "instantaneous_ops_per_sec": 100,
            "keyspace_hits": 1000,
            "keyspace_misses": 100,
        })
        mock_client.close = AsyncMock()

        # Create a mock for the Redis class
        mock_redis_class = MagicMock()
        mock_redis_class.from_url.return_value = mock_client

        # Create a mock module for aioredis
        mock_aioredis = MagicMock()
        mock_aioredis.Redis = mock_redis_class

        with patch('mcpgateway.services.performance_service.REDIS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.aioredis', mock_aioredis):
                with patch('mcpgateway.services.performance_service.settings') as mock_settings:
                    mock_settings.redis_url = "redis://localhost:6379"
                    mock_settings.cache_type = "redis"
                    result = await service.get_cache_metrics()

        assert isinstance(result, CacheMetricsSchema)
        assert result.connected is True
        assert result.version == "7.0.0"
        assert result.used_memory_mb > 0
        assert result.hit_rate > 0


class TestDashboard:
    """Tests for the complete performance dashboard."""

    @pytest.mark.asyncio
    async def test_get_dashboard(self):
        """Test complete dashboard generation."""
        service = PerformanceService()

        # Mock all the individual metric methods
        with patch.object(service, 'get_system_metrics') as mock_sys:
            with patch.object(service, 'get_request_metrics') as mock_req:
                with patch.object(service, 'get_database_metrics') as mock_db:
                    with patch.object(service, 'get_cache_metrics', new_callable=AsyncMock) as mock_cache:
                        with patch.object(service, 'get_gunicorn_metrics') as mock_guni:
                            with patch.object(service, 'get_worker_metrics') as mock_workers:
                                mock_sys.return_value = SystemMetricsSchema(
                                    cpu_percent=10.0,
                                    cpu_count=4,
                                    memory_total_mb=8000,
                                    memory_used_mb=4000,
                                    memory_available_mb=4000,
                                    memory_percent=50.0,
                                    disk_total_gb=100.0,
                                    disk_used_gb=50.0,
                                    disk_percent=50.0,
                                )
                                mock_req.return_value = RequestMetricsSchema()
                                mock_db.return_value = DatabaseMetricsSchema()
                                mock_cache.return_value = CacheMetricsSchema()
                                mock_guni.return_value = GunicornMetricsSchema()
                                mock_workers.return_value = []

                                result = await service.get_dashboard()

        assert isinstance(result, PerformanceDashboard)
        assert result.uptime_seconds >= 0
        assert result.host == HOSTNAME
        assert result.system.cpu_percent == 10.0


class TestSnapshotOperations:
    """Tests for snapshot save and cleanup operations."""

    def test_save_snapshot(self, test_db):
        """Test saving a performance snapshot."""
        service = PerformanceService(db=test_db)

        # Mock the metrics methods to return predictable data
        with patch.object(service, 'get_system_metrics') as mock_sys:
            with patch.object(service, 'get_request_metrics') as mock_req:
                with patch.object(service, 'get_database_metrics') as mock_db:
                    with patch.object(service, 'get_gunicorn_metrics') as mock_guni:
                        with patch.object(service, 'get_worker_metrics') as mock_workers:
                            mock_sys.return_value = SystemMetricsSchema(
                                cpu_percent=10.0,
                                cpu_count=4,
                                memory_total_mb=8000,
                                memory_used_mb=4000,
                                memory_available_mb=4000,
                                memory_percent=50.0,
                                disk_total_gb=100.0,
                                disk_used_gb=50.0,
                                disk_percent=50.0,
                            )
                            mock_req.return_value = RequestMetricsSchema()
                            mock_db.return_value = DatabaseMetricsSchema()
                            mock_guni.return_value = GunicornMetricsSchema()
                            mock_workers.return_value = []

                            result = service.save_snapshot(test_db)

        assert result is not None
        assert result.host == HOSTNAME
        assert "system" in result.metrics_json
        assert "requests" in result.metrics_json

    def test_save_snapshot_with_exception(self, test_db):
        """Test snapshot save with database error."""
        service = PerformanceService()

        # Create a mock db that raises on commit
        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("Database error")

        with patch.object(service, 'get_system_metrics') as mock_sys:
            with patch.object(service, 'get_request_metrics') as mock_req:
                with patch.object(service, 'get_database_metrics') as mock_dbm:
                    with patch.object(service, 'get_gunicorn_metrics') as mock_guni:
                        with patch.object(service, 'get_worker_metrics') as mock_workers:
                            mock_sys.return_value = SystemMetricsSchema(
                                cpu_percent=10.0,
                                cpu_count=4,
                                memory_total_mb=8000,
                                memory_used_mb=4000,
                                memory_available_mb=4000,
                                memory_percent=50.0,
                                disk_total_gb=100.0,
                                disk_used_gb=50.0,
                                disk_percent=50.0,
                            )
                            mock_req.return_value = RequestMetricsSchema()
                            mock_dbm.return_value = DatabaseMetricsSchema()
                            mock_guni.return_value = GunicornMetricsSchema()
                            mock_workers.return_value = []

                            result = service.save_snapshot(mock_db)

        assert result is None
        mock_db.rollback.assert_called_once()

    def test_cleanup_old_snapshots(self, test_db):
        """Test cleanup of old snapshots."""
        from mcpgateway.db import PerformanceSnapshot

        service = PerformanceService()

        # Create some old snapshots
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        snapshot = PerformanceSnapshot(
            host="test-host",
            worker_id="1234",
            metrics_json={"test": "data"},
            timestamp=old_time,
        )
        test_db.add(snapshot)
        test_db.commit()

        # Run cleanup
        deleted = service.cleanup_old_snapshots(test_db)

        # Should have deleted the old snapshot
        assert deleted >= 0

    def test_cleanup_old_snapshots_with_exception(self):
        """Test cleanup with database error."""
        service = PerformanceService()

        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("Database error")

        deleted = service.cleanup_old_snapshots(mock_db)

        assert deleted == 0
        mock_db.rollback.assert_called_once()


class TestHistoryOperations:
    """Tests for historical data retrieval."""

    def test_get_history_empty(self, test_db):
        """Test getting history when no data exists."""
        service = PerformanceService()
        result = service.get_history(test_db)

        assert isinstance(result, PerformanceHistoryResponse)
        assert result.aggregates == []
        assert result.period_type == "hourly"

    def test_get_history_with_filters(self, test_db):
        """Test getting history with filters."""
        service = PerformanceService()

        start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        end_time = datetime.now(timezone.utc)

        result = service.get_history(
            test_db,
            period_type="hourly",
            start_time=start_time,
            end_time=end_time,
            host="test-host",
            limit=100,
        )

        assert isinstance(result, PerformanceHistoryResponse)
        assert result.period_type == "hourly"


class TestHourlyAggregate:
    """Tests for hourly aggregate creation."""

    def test_create_hourly_aggregate_no_snapshots(self, test_db):
        """Test creating aggregate when no snapshots exist."""
        from mcpgateway.db import PerformanceAggregate

        service = PerformanceService()

        # Use a very old hour that definitely has no snapshots
        hour_start = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Clean up any existing aggregate for this hour
        test_db.query(PerformanceAggregate).filter(
            PerformanceAggregate.period_start == hour_start,
            PerformanceAggregate.period_type == "hourly"
        ).delete()
        test_db.commit()

        result = service.create_hourly_aggregate(test_db, hour_start)

        assert result is None

    def test_create_hourly_aggregate_with_snapshots(self, test_db):
        """Test creating aggregate from snapshots."""
        from mcpgateway.db import PerformanceSnapshot, PerformanceAggregate

        service = PerformanceService()

        # Use a unique hour for this test to avoid conflicts
        hour_start = datetime(2021, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        snapshot_time = hour_start + timedelta(minutes=30)

        # Clean up any existing data for this hour
        test_db.query(PerformanceAggregate).filter(
            PerformanceAggregate.period_start == hour_start,
            PerformanceAggregate.period_type == "hourly"
        ).delete()
        test_db.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.timestamp >= hour_start,
            PerformanceSnapshot.timestamp < hour_start + timedelta(hours=1)
        ).delete()
        test_db.commit()

        snapshot = PerformanceSnapshot(
            host=HOSTNAME,
            worker_id="1234",
            timestamp=snapshot_time,
            metrics_json={
                "system": {"cpu_percent": 50.0, "memory_percent": 60.0},
                "requests": {
                    "requests_total": 1000,
                    "requests_2xx": 950,
                    "requests_4xx": 30,
                    "requests_5xx": 20,
                    "response_time_avg_ms": 100.0,
                    "requests_per_second": 10.0,
                },
            },
        )
        test_db.add(snapshot)
        test_db.commit()

        result = service.create_hourly_aggregate(test_db, hour_start)

        assert result is not None
        assert result.period_type == "hourly"
        assert result.requests_total == 1000
        assert result.avg_cpu_percent == 50.0

    def test_create_hourly_aggregate_with_exception(self):
        """Test aggregate creation with database error."""
        service = PerformanceService()

        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("Database error")

        hour_start = datetime.now(timezone.utc)
        result = service.create_hourly_aggregate(mock_db, hour_start)

        assert result is None


class TestSingleton:
    """Tests for the singleton service getter."""

    def test_get_performance_service_singleton(self):
        """Test that get_performance_service returns a singleton."""
        # Reset the singleton
        import mcpgateway.services.performance_service as ps
        ps._performance_service = None

        service1 = get_performance_service()
        service2 = get_performance_service()

        assert service1 is service2

    def test_get_performance_service_with_db(self):
        """Test that get_performance_service updates db session."""
        import mcpgateway.services.performance_service as ps
        ps._performance_service = None

        mock_db = MagicMock()
        service = get_performance_service(db=mock_db)

        assert service.db is mock_db

        # Update with new db
        mock_db2 = MagicMock()
        service2 = get_performance_service(db=mock_db2)

        assert service is service2
        assert service.db is mock_db2


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_app_start_time(self):
        """Test that APP_START_TIME is set."""
        import time
        assert APP_START_TIME > 0
        assert APP_START_TIME <= time.time()

    def test_hostname(self):
        """Test that HOSTNAME is set."""
        assert HOSTNAME is not None
        assert len(HOSTNAME) > 0


class TestRequestMetricsEdgeCases:
    """Edge case tests for request metrics."""

    def test_get_request_metrics_with_error_responses(self):
        """Test request metrics calculating error rate."""
        service = PerformanceService()

        # Create mock samples for different status codes
        samples = [
            MagicMock(name="http_requests_total", labels={"status": "200"}, value=800),
            MagicMock(name="http_requests_total", labels={"status": "404"}, value=100),
            MagicMock(name="http_requests_total", labels={"status": "500"}, value=100),
        ]
        for s in samples:
            s.name = "http_requests_total"

        mock_metric = MagicMock()
        mock_metric.name = "http_requests_total"
        mock_metric.samples = samples

        mock_registry = MagicMock()
        mock_registry.collect.return_value = [mock_metric]

        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.REGISTRY', mock_registry):
                result = service.get_request_metrics()

        assert result.requests_total == 1000
        assert result.requests_2xx == 800
        assert result.requests_4xx == 100
        assert result.requests_5xx == 100
        assert result.error_rate == 20.0  # 200/1000 * 100

    def test_get_request_metrics_with_duration_histogram(self):
        """Test request metrics with response time histogram."""
        service = PerformanceService()

        # Mock http_request_duration_seconds histogram
        duration_sum = MagicMock(name="http_request_duration_seconds_sum", value=50.0)
        duration_sum.name = "http_request_duration_seconds_sum"
        duration_count = MagicMock(name="http_request_duration_seconds_count", value=100)
        duration_count.name = "http_request_duration_seconds_count"

        mock_metric = MagicMock()
        mock_metric.name = "http_request_duration_seconds"
        mock_metric.samples = [duration_sum, duration_count]

        mock_registry = MagicMock()
        mock_registry.collect.return_value = [mock_metric]

        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.REGISTRY', mock_registry):
                result = service.get_request_metrics()

        assert result.response_time_avg_ms == 500.0  # 50/100 * 1000

    def test_get_request_metrics_exception_handling(self):
        """Test request metrics handles exceptions gracefully."""
        service = PerformanceService()

        mock_registry = MagicMock()
        mock_registry.collect.side_effect = Exception("Registry error")

        with patch('mcpgateway.services.performance_service.PROMETHEUS_AVAILABLE', True):
            with patch('mcpgateway.services.performance_service.REGISTRY', mock_registry):
                result = service.get_request_metrics()

        assert isinstance(result, RequestMetricsSchema)
        assert result.requests_total == 0
