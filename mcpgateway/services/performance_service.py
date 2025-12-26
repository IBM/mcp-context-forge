# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/performance_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Performance Monitoring Service.

This module provides comprehensive system and application performance monitoring
for the MCP Gateway. It collects metrics from:
- System resources (CPU, memory, disk, network) via psutil
- Gunicorn workers and processes
- Database connection pools
- Redis cache (when available)
- HTTP request statistics from Prometheus metrics

The service supports both single-instance and distributed deployments,
with optional Redis-based metric aggregation for multi-worker environments.
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
import os
import socket
import time
from typing import Dict, List, Optional

# Third-Party
from sqlalchemy import delete, desc
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import PerformanceAggregate, PerformanceSnapshot
from mcpgateway.schemas import (
    CacheMetricsSchema,
    DatabaseMetricsSchema,
    GunicornMetricsSchema,
    PerformanceAggregateRead,
    PerformanceDashboard,
    PerformanceHistoryResponse,
    RequestMetricsSchema,
    SystemMetricsSchema,
    WorkerMetrics,
)
from mcpgateway.utils.redis_client import get_redis_client

# Cache import (lazy to avoid circular dependencies)
_ADMIN_STATS_CACHE = None


def _get_admin_stats_cache():
    """Get admin stats cache singleton lazily.

    Returns:
        AdminStatsCache instance.
    """
    global _ADMIN_STATS_CACHE  # pylint: disable=global-statement
    if _ADMIN_STATS_CACHE is None:
        # First-Party
        from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

        _ADMIN_STATS_CACHE = admin_stats_cache
    return _ADMIN_STATS_CACHE


# Optional psutil import
try:
    # Third-Party
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    PSUTIL_AVAILABLE = False

# Optional redis import
try:
    # Third-Party
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore
    REDIS_AVAILABLE = False

# Optional prometheus_client import
try:
    # Third-Party
    from prometheus_client import REGISTRY

    PROMETHEUS_AVAILABLE = True
except ImportError:
    REGISTRY = None  # type: ignore
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Track application start time
APP_START_TIME = time.time()
HOSTNAME = socket.gethostname()


class PerformanceService:
    """
    Service for collecting and managing performance metrics.

    Provides methods for:
    - Real-time metric collection from system and application
    - Historical metric storage and retrieval
    - Metric aggregation for trend analysis
    - Worker process discovery and monitoring
    """

    def __init__(self, db: Optional[Session] = None):
        """Initialize the performance service.

        Args:
            db: Optional SQLAlchemy database session.
        """
        self.db = db
        self._request_count_cache: Dict[str, int] = {}
        self._last_request_time = time.time()

    def get_system_metrics(self) -> SystemMetricsSchema:
        """Collect current system metrics using psutil.

        Returns:
            SystemMetricsSchema: Current system resource metrics.
        """
        if not PSUTIL_AVAILABLE or psutil is None:
            # Return empty metrics if psutil not available
            return SystemMetricsSchema(
                cpu_percent=0.0,
                cpu_count=os.cpu_count() or 1,
                memory_total_mb=0,
                memory_used_mb=0,
                memory_available_mb=0,
                memory_percent=0.0,
                disk_total_gb=0.0,
                disk_used_gb=0.0,
                disk_percent=0.0,
            )

        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=True) or 1
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = round(cpu_freq.current) if cpu_freq else None

        # Load average (Unix only)
        try:
            load_1, load_5, load_15 = os.getloadavg()
        except (AttributeError, OSError):
            load_1, load_5, load_15 = None, None, None

        # Memory metrics
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disk metrics
        root = os.getenv("SystemDrive", "C:\\") if os.name == "nt" else "/"
        disk = psutil.disk_usage(str(root))

        # Network metrics
        net_io = psutil.net_io_counters()
        net_connections = len(psutil.net_connections(kind="inet"))

        # Boot time
        boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)

        return SystemMetricsSchema(
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            cpu_freq_mhz=cpu_freq_mhz,
            load_avg_1m=round(load_1, 2) if load_1 is not None else None,
            load_avg_5m=round(load_5, 2) if load_5 is not None else None,
            load_avg_15m=round(load_15, 2) if load_15 is not None else None,
            memory_total_mb=round(vm.total / 1_048_576),
            memory_used_mb=round(vm.used / 1_048_576),
            memory_available_mb=round(vm.available / 1_048_576),
            memory_percent=vm.percent,
            swap_total_mb=round(swap.total / 1_048_576),
            swap_used_mb=round(swap.used / 1_048_576),
            disk_total_gb=round(disk.total / 1_073_741_824, 2),
            disk_used_gb=round(disk.used / 1_073_741_824, 2),
            disk_percent=disk.percent,
            network_bytes_sent=net_io.bytes_sent,
            network_bytes_recv=net_io.bytes_recv,
            network_connections=net_connections,
            boot_time=boot_time,
        )

    def get_worker_metrics(self) -> List[WorkerMetrics]:
        """Discover and collect metrics from Gunicorn worker processes.

        Returns:
            List[WorkerMetrics]: Metrics for each worker process.
        """
        workers: List[WorkerMetrics] = []

        if not PSUTIL_AVAILABLE or psutil is None:
            return workers

        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)

        # Try to find Gunicorn master by looking at parent
        try:
            parent = current_proc.parent()
            if parent and "gunicorn" in parent.name().lower():
                # We're in a Gunicorn worker, get all siblings
                for child in parent.children(recursive=False):
                    workers.append(self._get_process_metrics(child))
            else:
                # Not in Gunicorn, just report current process
                workers.append(self._get_process_metrics(current_proc))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Fallback to current process only
            workers.append(self._get_process_metrics(current_proc))

        return workers

    def _get_process_metrics(self, proc: "psutil.Process") -> WorkerMetrics:
        """Get metrics for a specific process.

        Args:
            proc: psutil Process object.

        Returns:
            WorkerMetrics: Metrics for the process.
        """
        try:
            with proc.oneshot():
                mem_info = proc.memory_info()
                create_time = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
                uptime = int(time.time() - proc.create_time())

                # Get file descriptors (Unix only)
                try:
                    open_fds = proc.num_fds()
                except (AttributeError, psutil.AccessDenied):
                    open_fds = None

                # Get connections
                try:
                    connections = len(proc.connections(kind="inet"))
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    connections = 0

                return WorkerMetrics(
                    pid=proc.pid,
                    cpu_percent=proc.cpu_percent(interval=0.1),
                    memory_rss_mb=round(mem_info.rss / 1_048_576, 2),
                    memory_vms_mb=round(mem_info.vms / 1_048_576, 2),
                    threads=proc.num_threads(),
                    connections=connections,
                    open_fds=open_fds,
                    status=proc.status(),
                    create_time=create_time,
                    uptime_seconds=uptime,
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Could not get metrics for process {proc.pid}: {e}")
            return WorkerMetrics(
                pid=proc.pid,
                cpu_percent=0.0,
                memory_rss_mb=0.0,
                memory_vms_mb=0.0,
                threads=0,
                status="unknown",
            )

    def get_gunicorn_metrics(self) -> GunicornMetricsSchema:
        """Collect Gunicorn-specific metrics.

        Returns:
            GunicornMetricsSchema: Gunicorn server metrics.
        """
        if not PSUTIL_AVAILABLE or psutil is None:
            return GunicornMetricsSchema()

        current_pid = os.getpid()
        current_proc = psutil.Process(current_pid)

        try:
            parent = current_proc.parent()
            if parent and "gunicorn" in parent.name().lower():
                # We're in a Gunicorn worker
                children = parent.children(recursive=False)
                workers_total = len(children)

                # Count active workers (those with connections or recent CPU activity)
                workers_active = 0
                for child in children:
                    try:
                        if child.cpu_percent(interval=0) > 0:
                            workers_active += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                return GunicornMetricsSchema(
                    master_pid=parent.pid,
                    workers_total=workers_total,
                    workers_active=workers_active,
                    workers_idle=workers_total - workers_active,
                    max_requests=10000,  # Default from gunicorn.config.py
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Not running under Gunicorn or can't determine
        return GunicornMetricsSchema(
            master_pid=None,
            workers_total=1,
            workers_active=1,
            workers_idle=0,
        )

    def get_request_metrics(self) -> RequestMetricsSchema:
        """Collect HTTP request metrics from Prometheus.

        Returns:
            RequestMetricsSchema: HTTP request performance metrics.
        """
        metrics = RequestMetricsSchema()

        if not PROMETHEUS_AVAILABLE or REGISTRY is None:
            return metrics

        try:
            # Try to get metrics from Prometheus registry
            for metric in REGISTRY.collect():
                if metric.name == "http_requests_total":
                    for sample in metric.samples:
                        if sample.name == "http_requests_total":
                            # prometheus_fastapi_instrumentator uses 'status' label, not 'status_code'
                            status = sample.labels.get("status", sample.labels.get("status_code", ""))
                            value = int(sample.value)
                            metrics.requests_total += value

                            if status.startswith("1"):
                                metrics.requests_1xx += value
                            elif status.startswith("2"):
                                metrics.requests_2xx += value
                            elif status.startswith("3"):
                                metrics.requests_3xx += value
                            elif status.startswith("4"):
                                metrics.requests_4xx += value
                            elif status.startswith("5"):
                                metrics.requests_5xx += value

                elif metric.name == "http_request_duration_seconds":
                    # Extract histogram data for percentiles
                    sum_val = 0.0
                    count_val = 0
                    for sample in metric.samples:
                        if sample.name.endswith("_sum"):
                            sum_val = sample.value
                        elif sample.name.endswith("_count"):
                            count_val = int(sample.value)

                    if count_val > 0:
                        metrics.response_time_avg_ms = round((sum_val / count_val) * 1000, 2)

            # Calculate error rate
            if metrics.requests_total > 0:
                error_count = metrics.requests_4xx + metrics.requests_5xx
                metrics.error_rate = round((error_count / metrics.requests_total) * 100, 2)

            # Calculate requests per second
            current_time = time.time()
            elapsed = current_time - self._last_request_time
            if elapsed > 0:
                prev_total = self._request_count_cache.get("total", 0)
                if prev_total > 0:
                    metrics.requests_per_second = round((metrics.requests_total - prev_total) / elapsed, 2)
                self._request_count_cache["total"] = metrics.requests_total
                self._last_request_time = current_time

        except Exception as e:
            logger.warning(f"Error collecting Prometheus metrics: {e}")

        return metrics

    def get_database_metrics(self, _db: Optional[Session] = None) -> DatabaseMetricsSchema:
        """Collect database connection pool metrics.

        Args:
            _db: Optional SQLAlchemy session (unused, engine imported directly).

        Returns:
            DatabaseMetricsSchema: Database connection pool metrics.
        """
        metrics = DatabaseMetricsSchema()

        try:
            # Import engine from db module (lazy import to avoid circular dependency)
            # First-Party
            from mcpgateway.db import engine  # pylint: disable=import-outside-toplevel

            pool = engine.pool
            if pool:
                metrics.pool_size = pool.size()
                metrics.connections_in_use = pool.checkedout()
                metrics.connections_available = pool.checkedin()
                metrics.overflow = pool.overflow()
        except Exception as e:
            logger.warning(f"Error collecting database metrics: {e}")

        return metrics

    async def get_cache_metrics(self) -> CacheMetricsSchema:
        """Collect Redis cache metrics.

        Returns:
            CacheMetricsSchema: Redis cache metrics.
        """
        metrics = CacheMetricsSchema()

        if not REDIS_AVAILABLE or aioredis is None:
            return metrics

        if not settings.redis_url or settings.cache_type.lower() != "redis":
            return metrics

        try:
            # Use shared Redis client from factory
            client = await get_redis_client()
            if not client:
                return metrics

            info = await client.info()

            metrics.connected = True
            metrics.version = info.get("redis_version")
            metrics.used_memory_mb = round(info.get("used_memory", 0) / 1_048_576, 2)
            metrics.connected_clients = info.get("connected_clients", 0)
            metrics.ops_per_second = info.get("instantaneous_ops_per_sec", 0)

            # Cache hit rate
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            metrics.keyspace_hits = hits
            metrics.keyspace_misses = misses

            total = hits + misses
            if total > 0:
                metrics.hit_rate = round((hits / total) * 100, 2)

            # Don't close the shared client
        except Exception as e:
            logger.warning(f"Error collecting Redis metrics: {e}")
            metrics.connected = False

        return metrics

    async def get_dashboard(self) -> PerformanceDashboard:
        """Collect all metrics for the performance dashboard.

        Returns:
            PerformanceDashboard: Complete dashboard data.
        """
        uptime = int(time.time() - APP_START_TIME)

        # Collect all metrics
        system = self.get_system_metrics()
        requests = self.get_request_metrics()
        database = self.get_database_metrics(self.db)
        cache = await self.get_cache_metrics()
        gunicorn = self.get_gunicorn_metrics()
        workers = self.get_worker_metrics()

        return PerformanceDashboard(
            timestamp=datetime.now(timezone.utc),
            uptime_seconds=uptime,
            host=HOSTNAME,
            system=system,
            requests=requests,
            database=database,
            cache=cache,
            gunicorn=gunicorn,
            workers=workers,
            cluster_hosts=[HOSTNAME],
            is_distributed=settings.mcpgateway_performance_distributed,
        )

    def save_snapshot(self, db: Session) -> Optional[PerformanceSnapshot]:
        """Save current metrics as a snapshot.

        Args:
            db: SQLAlchemy database session.

        Returns:
            PerformanceSnapshot: The saved snapshot, or None on error.
        """
        try:
            # Collect current metrics
            system = self.get_system_metrics()
            requests = self.get_request_metrics()
            database = self.get_database_metrics(db)
            gunicorn = self.get_gunicorn_metrics()
            workers = self.get_worker_metrics()

            # Serialize to JSON
            metrics_json = {
                "system": system.model_dump(),
                "requests": requests.model_dump(),
                "database": database.model_dump(),
                "gunicorn": gunicorn.model_dump(),
                "workers": [w.model_dump() for w in workers],
            }

            # Convert datetime to ISO format strings for JSON serialization
            if metrics_json["system"].get("boot_time"):
                metrics_json["system"]["boot_time"] = metrics_json["system"]["boot_time"].isoformat()
            for worker in metrics_json["workers"]:
                if worker.get("create_time"):
                    worker["create_time"] = worker["create_time"].isoformat()

            snapshot = PerformanceSnapshot(
                host=HOSTNAME,
                worker_id=str(os.getpid()),
                metrics_json=metrics_json,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            return snapshot
        except Exception as e:
            logger.error(f"Error saving performance snapshot: {e}")
            db.rollback()
            return None

    def cleanup_old_snapshots(self, db: Session) -> int:
        """Delete snapshots older than retention period.

        Args:
            db: SQLAlchemy database session.

        Returns:
            int: Number of deleted snapshots.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.mcpgateway_performance_retention_hours)

            result = db.execute(delete(PerformanceSnapshot).where(PerformanceSnapshot.timestamp < cutoff))
            deleted = result.rowcount
            db.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old performance snapshots")

            return deleted
        except Exception as e:
            logger.error(f"Error cleaning up snapshots: {e}")
            db.rollback()
            return 0

    async def get_history(
        self,
        db: Session,
        period_type: str = "hourly",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        host: Optional[str] = None,
        limit: int = 168,
    ) -> PerformanceHistoryResponse:
        """Get historical performance aggregates.

        Args:
            db: SQLAlchemy database session.
            period_type: Aggregation period (hourly, daily).
            start_time: Start of time range.
            end_time: End of time range.
            host: Filter by host.
            limit: Maximum results.

        Returns:
            PerformanceHistoryResponse: Historical aggregates.
        """
        # Build cache key from parameters
        start_str = start_time.isoformat() if start_time else "none"
        end_str = end_time.isoformat() if end_time else "none"
        host_str = host or "all"
        cache_key = f"{period_type}:{start_str}:{end_str}:{host_str}:{limit}"

        # Check cache first
        cache = _get_admin_stats_cache()
        cached = await cache.get_performance_history(cache_key)
        if cached is not None:
            return PerformanceHistoryResponse.model_validate(cached)

        query = db.query(PerformanceAggregate).filter(PerformanceAggregate.period_type == period_type)

        if start_time:
            query = query.filter(PerformanceAggregate.period_start >= start_time)
        if end_time:
            query = query.filter(PerformanceAggregate.period_end <= end_time)
        if host:
            query = query.filter(PerformanceAggregate.host == host)

        total_count = query.count()
        aggregates = query.order_by(desc(PerformanceAggregate.period_start)).limit(limit).all()

        result = PerformanceHistoryResponse(
            aggregates=[PerformanceAggregateRead.model_validate(a) for a in aggregates],
            period_type=period_type,
            total_count=total_count,
        )

        # Store in cache
        await cache.set_performance_history(result.model_dump(), cache_key)

        return result

    def create_hourly_aggregate(self, db: Session, hour_start: datetime) -> Optional[PerformanceAggregate]:
        """Create an hourly aggregate from snapshots.

        Args:
            db: SQLAlchemy database session.
            hour_start: Start of the hour to aggregate.

        Returns:
            PerformanceAggregate: The created aggregate, or None on error.
        """
        hour_end = hour_start + timedelta(hours=1)

        try:
            # Get snapshots for this hour
            snapshots = db.query(PerformanceSnapshot).filter(PerformanceSnapshot.timestamp >= hour_start, PerformanceSnapshot.timestamp < hour_end).all()

            if not snapshots:
                return None

            # Aggregate metrics
            total_requests = 0
            total_2xx = 0
            total_4xx = 0
            total_5xx = 0
            response_times: List[float] = []
            request_rates: List[float] = []
            cpu_percents: List[float] = []
            memory_percents: List[float] = []

            for snapshot in snapshots:
                metrics = snapshot.metrics_json
                req = metrics.get("requests", {})
                sys = metrics.get("system", {})

                total_requests += req.get("requests_total", 0)
                total_2xx += req.get("requests_2xx", 0)
                total_4xx += req.get("requests_4xx", 0)
                total_5xx += req.get("requests_5xx", 0)

                if req.get("response_time_avg_ms"):
                    response_times.append(req["response_time_avg_ms"])
                if req.get("requests_per_second"):
                    request_rates.append(req["requests_per_second"])
                if sys.get("cpu_percent"):
                    cpu_percents.append(sys["cpu_percent"])
                if sys.get("memory_percent"):
                    memory_percents.append(sys["memory_percent"])

            # Calculate averages and peaks
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0
            peak_rps = max(request_rates) if request_rates else 0.0
            avg_cpu = sum(cpu_percents) / len(cpu_percents) if cpu_percents else 0.0
            avg_memory = sum(memory_percents) / len(memory_percents) if memory_percents else 0.0
            peak_cpu = max(cpu_percents) if cpu_percents else 0.0
            peak_memory = max(memory_percents) if memory_percents else 0.0

            # Create aggregate
            aggregate = PerformanceAggregate(
                period_start=hour_start,
                period_end=hour_end,
                period_type="hourly",
                host=HOSTNAME,
                requests_total=total_requests,
                requests_2xx=total_2xx,
                requests_4xx=total_4xx,
                requests_5xx=total_5xx,
                avg_response_time_ms=round(avg_response_time, 2),
                p95_response_time_ms=0.0,  # Would need more data for percentiles
                peak_requests_per_second=round(peak_rps, 2),
                avg_cpu_percent=round(avg_cpu, 2),
                avg_memory_percent=round(avg_memory, 2),
                peak_cpu_percent=round(peak_cpu, 2),
                peak_memory_percent=round(peak_memory, 2),
            )

            db.add(aggregate)
            db.commit()
            db.refresh(aggregate)

            return aggregate
        except Exception as e:
            logger.error(f"Error creating hourly aggregate: {e}")
            db.rollback()
            return None


# Singleton service instance
_performance_service: Optional[PerformanceService] = None


def get_performance_service(db: Optional[Session] = None) -> PerformanceService:
    """Get or create the performance service singleton.

    Args:
        db: Optional database session.

    Returns:
        PerformanceService: The service instance.
    """
    global _performance_service  # pylint: disable=global-statement
    if _performance_service is None:
        _performance_service = PerformanceService(db)
    elif db is not None:
        _performance_service.db = db
    return _performance_service
