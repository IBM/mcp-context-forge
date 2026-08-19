# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_monitoring_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Primary-worker gRPC health monitoring with production-grade features:

- Concurrent health checks (bounded by semaphore)
- Channel reuse with keepalive (lightweight pool)
- Last-success tracking and availability-rate calculation
- Standards-based Health/Check with channel-readiness fallback
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import os
import random
import stat
import threading
import time
from typing import Any, Optional

# Third-Party
try:
    import grpc

    GRPC_AVAILABLE = True
except ImportError:  # pragma: no cover - optional gRPC extra
    grpc = None  # type: ignore
    GRPC_AVAILABLE = False
from sqlalchemy import case, delete, func, select

try:
    # Third-Party
    from grpc_health.v1 import health_pb2, health_pb2_grpc

    GRPC_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency fallback
    health_pb2 = None  # type: ignore
    health_pb2_grpc = None  # type: ignore
    GRPC_HEALTH_AVAILABLE = False

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import fresh_db_session, GrpcHealthSample
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.observability import create_child_span
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics import grpc_health_checks_counter, grpc_health_status_gauge
from mcpgateway.utils.grpc_validation import _validate_grpc_target, _validate_tls_path, GrpcServiceError
from mcpgateway.utils.primary_worker import is_primary_worker

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Maximum concurrent in-flight health checks.
_DEFAULT_MAX_CONCURRENT_CHECKS = 10

# Channel pool idle TTL (seconds). Channels not used within this window are closed.
_CHANNEL_IDLE_TTL = 300

# Certificate and private-key files are deliberately bounded before reading.
# This matches the Admin UI upload limit and prevents a misconfigured health
# check from consuming unbounded memory.
_TLS_MATERIAL_MAX_BYTES = 10 * 1024 * 1024


class _HealthChannel:
    """A pooled gRPC channel with last-used tracking for idle pruning."""

    __slots__ = ("channel", "last_used")

    def __init__(self, channel: Any) -> None:
        self.channel = channel
        self.last_used = time.monotonic()

    def touch(self) -> None:
        """Mark the channel as recently used."""
        self.last_used = time.monotonic()

    def close(self) -> None:
        """Close the underlying channel."""
        if self.channel is not None:
            try:
                self.channel.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self.channel = None


class GrpcMonitoringService:
    """Production-grade gRPC health monitor with channel pooling and concurrent checks."""

    def __init__(self) -> None:
        """Initialize the singleton monitor lifecycle state."""
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self._health_channels: dict[tuple, _HealthChannel] = {}
        self._channel_lock = threading.Lock()
        self._max_concurrent = getattr(settings, "grpc_health_max_concurrent_checks", _DEFAULT_MAX_CONCURRENT_CHECKS)

    async def start(self) -> None:
        """Start one monitor loop per process; only the primary performs checks."""
        if not GRPC_AVAILABLE:
            return
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        """Stop the monitor loop and close all pooled channels."""
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._close_all_channels()

    def _close_all_channels(self) -> None:
        """Close every pooled health-check channel."""
        with self._channel_lock:
            for entry in self._health_channels.values():
                entry.close()
            self._health_channels.clear()

    # ------------------------------------------------------------------
    # Channel pool
    # ------------------------------------------------------------------

    @staticmethod
    def _read_tls_file(path_str: str, label: str) -> bytes:
        """Validate and read one bounded regular TLS file without following a final symlink."""
        path = _validate_tls_path(path_str, label)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: Optional[int] = None
        try:
            descriptor = os.open(path, flags)
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise GrpcServiceError(f"{label} '{path_str}' must be a regular file")
            if file_stat.st_size > _TLS_MATERIAL_MAX_BYTES:
                raise GrpcServiceError(f"{label} '{path_str}' exceeds the {_TLS_MATERIAL_MAX_BYTES}-byte limit")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None  # fdopen owns and closes the descriptor.
                content = stream.read(_TLS_MATERIAL_MAX_BYTES + 1)
        except GrpcServiceError:
            raise
        except OSError as exc:
            raise GrpcServiceError(f"Unable to read {label.lower()} '{path_str}': {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(content) > _TLS_MATERIAL_MAX_BYTES:
            raise GrpcServiceError(f"{label} '{path_str}' exceeds the {_TLS_MATERIAL_MAX_BYTES}-byte limit")
        return content

    @classmethod
    def _load_tls_material(cls, service: DbGrpcService) -> tuple[Optional[bytes], Optional[bytes]]:
        """Return validated certificate/key bytes for one service."""
        if not service.tls_enabled:
            return None, None
        if service.tls_key_path and not service.tls_cert_path:
            raise ValueError("TLS key path requires a TLS certificate path")
        if not service.tls_cert_path:
            return None, None
        cert = cls._read_tls_file(service.tls_cert_path, "TLS cert path")
        key = cls._read_tls_file(service.tls_key_path, "TLS key path") if service.tls_key_path else None
        return cert, key

    @staticmethod
    def _channel_key(service: DbGrpcService, tls_material: tuple[Optional[bytes], Optional[bytes]]) -> tuple:
        """Derive a deterministic pool key from validated connection material."""
        cert, key = tls_material
        return (
            service.target,
            service.tls_enabled,
            service.tls_cert_path or "",
            service.tls_key_path or "",
            hashlib.sha256(cert).hexdigest() if cert is not None else "",
            hashlib.sha256(key).hexdigest() if key is not None else "",
        )

    @classmethod
    def _build_channel(
        cls,
        service: DbGrpcService,
        tls_material: Optional[tuple[Optional[bytes], Optional[bytes]]] = None,
        *,
        target_validated: bool = False,
    ) -> Any:
        """Create a validated gRPC channel with keepalive for health checks."""
        if not target_validated:
            _validate_grpc_target(service.target)
        keepalive_opts = [
            ("grpc.keepalive_time_ms", 30_000),
            ("grpc.keepalive_timeout_ms", 20_000),
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.http2.max_pings_without_data", 0),
            ("grpc.max_receive_message_length", int(getattr(settings, "mcpgateway_grpc_max_message_size", 4 * 1024 * 1024))),
        ]
        if not service.tls_enabled:
            return grpc.insecure_channel(service.target, options=keepalive_opts)

        cert, key = tls_material if tls_material is not None else cls._load_tls_material(service)
        if cert is not None:
            if key is None:
                credentials = grpc.ssl_channel_credentials(root_certificates=cert)
                return grpc.secure_channel(service.target, credentials, options=keepalive_opts)
            credentials = grpc.ssl_channel_credentials(private_key=key, certificate_chain=cert)
            return grpc.secure_channel(service.target, credentials, options=keepalive_opts)

        credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(service.target, credentials, options=keepalive_opts)

    def _get_channel(self, service: DbGrpcService) -> Any:
        """Return a warm channel from the pool or create one."""
        _validate_grpc_target(service.target)
        tls_material = self._load_tls_material(service)
        key = self._channel_key(service, tls_material)
        with self._channel_lock:
            entry = self._health_channels.get(key)
            if entry is not None:
                entry.touch()
                return entry.channel
            channel = self._build_channel(service, tls_material, target_validated=True)
            self._health_channels[key] = _HealthChannel(channel)
            return channel

    def _prune_channels(self) -> None:
        """Close channels idle longer than ``_CHANNEL_IDLE_TTL``."""
        now = time.monotonic()
        with self._channel_lock:
            stale = [k for k, e in self._health_channels.items() if now - e.last_used > _CHANNEL_IDLE_TTL]
            for key in stale:
                entry = self._health_channels.pop(key)
                entry.close()
            if stale:
                logger.info("Pruned %d idle health-check channel(s)", len(stale))

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata(values: dict[str, str]) -> list[tuple[str, str]]:
        """Decrypt persisted metadata only at the outbound gRPC boundary."""
        encryption = get_encryption_service(settings.auth_encryption_secret)
        result: list[tuple[str, str]] = []
        for key, value in values.items():
            plaintext = encryption.decrypt_secret_or_plaintext(value)
            if plaintext is not None:
                result.append((key, plaintext))
        return result

    # ------------------------------------------------------------------
    # Core check logic
    # ------------------------------------------------------------------

    @classmethod
    def _check_blocking(cls, channel: Any, service: DbGrpcService) -> tuple[bool, str, str, Optional[str], float]:
        """Run Health/Check on a pre-built channel, falling back to readiness.

        Args:
            channel: A gRPC channel (pooled, not closed by this method).
            service: The service snapshot with timeout and metadata config.

        Returns:
            Tuple of (healthy, check_type, status_code, error, latency_ms).
        """
        started = time.monotonic()
        check_type = "health"
        status_code = "UNKNOWN"
        error: Optional[str] = None
        healthy = False
        try:
            if GRPC_HEALTH_AVAILABLE:
                stub = health_pb2_grpc.HealthStub(channel)
                try:
                    response = stub.Check(
                        health_pb2.HealthCheckRequest(service=""),
                        timeout=service.health_check_timeout,
                        metadata=cls._metadata(service.grpc_metadata or {}),
                    )
                    healthy = response.status == health_pb2.HealthCheckResponse.SERVING
                    status_code = health_pb2.HealthCheckResponse.ServingStatus.Name(response.status)
                except grpc.RpcError as exc:
                    rpc_code = getattr(exc, "code", lambda: None)()
                    if rpc_code != grpc.StatusCode.UNIMPLEMENTED:
                        raise
                    check_type = "readiness"
                    grpc.channel_ready_future(channel).result(timeout=service.health_check_timeout)
                    healthy = True
                    status_code = "READY"
            else:
                check_type = "readiness"
                grpc.channel_ready_future(channel).result(timeout=service.health_check_timeout)
                healthy = True
                status_code = "READY"
        except grpc.RpcError as exc:
            rpc_code = getattr(exc, "code", lambda: None)()
            rpc_details = getattr(exc, "details", lambda: None)()
            status_code = rpc_code.name if rpc_code else "UNKNOWN"
            error = f"{status_code}: {rpc_details}" if rpc_details else status_code
        except Exception as exc:  # pylint: disable=broad-except
            status_code = "UNAVAILABLE"
            error = f"UNAVAILABLE: {exc}"
        return healthy, check_type, status_code, error, (time.monotonic() - started) * 1000

    @classmethod
    async def check_service(cls, service_id: str) -> dict[str, Any]:
        """Check one service using a pooled channel and persist the sample.

        Updates ``last_health_success`` on a healthy outcome and calculates
        24-hour availability from the sample table.
        """
        if not GRPC_AVAILABLE:
            return {"status": "unavailable", "error": "gRPC dependencies are not installed"}
        with fresh_db_session() as read_db:
            service = read_db.get(DbGrpcService, service_id)
            if service is None:
                return {"status": "missing"}
            snapshot = DbGrpcService(
                id=service.id,
                name=service.name,
                slug=service.slug,
                target=service.target,
                tls_enabled=service.tls_enabled,
                tls_cert_path=service.tls_cert_path,
                tls_key_path=service.tls_key_path,
                grpc_metadata=dict(service.grpc_metadata or {}),
                health_check_timeout=service.health_check_timeout,
            )
        monitor = get_grpc_monitoring_service()
        channel = await asyncio.to_thread(monitor._get_channel, snapshot)  # pylint: disable=protected-access
        with create_child_span("grpc.health.check", {"rpc.system": "grpc", "server.address": snapshot.target, "grpc.service.id": snapshot.id}):
            healthy, check_type, status_code, error, latency_ms = await asyncio.to_thread(cls._check_blocking, channel, snapshot)
        with fresh_db_session() as write_db:
            service = write_db.get(DbGrpcService, service_id)
            if service is None:
                return {"status": "missing"}
            now_utc = datetime.now(timezone.utc)
            service.last_health_check = now_utc
            if healthy:
                service.consecutive_failures = 0
                service.health_status = "healthy"
                service.last_health_error = None
                service.last_health_success = now_utc
                service.reachable = True
            else:
                service.consecutive_failures += 1
                service.health_status = "unhealthy" if service.consecutive_failures >= service.health_failure_threshold else "degraded"
                service.last_health_error = (error or status_code)[:1000]
                if service.health_status == "unhealthy":
                    service.reachable = False
            write_db.add(
                GrpcHealthSample(
                    grpc_service_id=service.id,
                    healthy=healthy,
                    check_type=check_type,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error_message=(error or "")[:1000] or None,
                )
            )
            # Prune old samples (30-day retention)
            write_db.execute(delete(GrpcHealthSample).where(GrpcHealthSample.timestamp < now_utc - timedelta(days=30)))
            write_db.flush()  # ensure new sample is visible to availability query
            # Calculate 24h availability from samples
            availability = cls._availability_rate(write_db, service_id)
            status = service.health_status
            service_slug = service.slug
        grpc_health_checks_counter.labels(service=service_slug, check_type=check_type, outcome="success" if healthy else "failure").inc()
        grpc_health_status_gauge.labels(service=service_slug).set(1 if healthy else 0)
        return {
            "status": status,
            "healthy": healthy,
            "check_type": check_type,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "error": error,
            "last_health_success": service.last_health_success.isoformat() if service.last_health_success else None,
            "availability_24h": availability,
        }

    # ------------------------------------------------------------------
    # Availability rate
    # ------------------------------------------------------------------

    @staticmethod
    def _availability_rate(db: Any, service_id: str, window_hours: int = 24) -> Optional[float]:
        """Calculate availability rate from ``GrpcHealthSample`` over a window.

        Args:
            db: Database session.
            service_id: The gRPC service ID.
            window_hours: Lookback window in hours (default 24).

        Returns:
            Float 0.0–1.0, or None when there are no samples in the window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        row = db.execute(
            select(
                func.count().label("total"),
                func.sum(case((GrpcHealthSample.healthy.is_(True), 1), else_=0)).label("success"),
            ).where(
                GrpcHealthSample.grpc_service_id == service_id,
                GrpcHealthSample.timestamp >= cutoff,
            )
        ).one()
        if not row.total:
            return None
        return round(row.success / row.total, 4)

    # ------------------------------------------------------------------
    # Background loop (concurrent)
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Schedule jittered, concurrent checks from the primary worker.

        Services due for a check are gathered in parallel, bounded by
        ``_max_concurrent`` to avoid overwhelming the process or upstreams.
        """
        while not self._stopping.is_set():
            try:
                if is_primary_worker():
                    now = datetime.now(timezone.utc)
                    with fresh_db_session() as db:
                        services = list(
                            db.execute(
                                select(DbGrpcService.id, DbGrpcService.health_check_interval, DbGrpcService.last_health_check).where(
                                    DbGrpcService.enabled.is_(True), DbGrpcService.health_check_enabled.is_(True)
                                )
                            ).all()
                        )
                    due: list[str] = []
                    for service_id, interval, last_check in services:
                        last_check_utc = last_check.replace(tzinfo=timezone.utc) if last_check and last_check.tzinfo is None else last_check
                        jittered = max(10, int(interval * random.uniform(0.9, 1.1)))  # nosec B311
                        if last_check_utc is None or (now - last_check_utc).total_seconds() >= jittered:
                            due.append(service_id)
                    if due:
                        sem = asyncio.Semaphore(max(1, self._max_concurrent))

                        async def _check_one(sid: str) -> None:
                            async with sem:
                                try:
                                    await self.check_service(sid)
                                except Exception:  # pylint: disable=broad-except
                                    logger.exception("Health check failed for service %s", sid)

                        await asyncio.gather(*(_check_one(sid) for sid in due), return_exceptions=True)
                    # Prune idle channels periodically
                    self._prune_channels()
                await asyncio.wait_for(self._stopping.wait(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except Exception:  # pylint: disable=broad-except
                logger.exception("Health monitor loop error")
                await asyncio.sleep(5)


_monitor = GrpcMonitoringService()


def get_grpc_monitoring_service() -> GrpcMonitoringService:
    """Return the process singleton monitor."""
    return _monitor
