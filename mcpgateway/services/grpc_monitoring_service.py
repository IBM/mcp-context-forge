# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/grpc_monitoring_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Primary-worker gRPC health monitoring using the standard Health service.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import random
import time
from typing import Any, Optional

# Third-Party
try:
    import grpc

    GRPC_AVAILABLE = True
except ImportError:  # pragma: no cover - optional gRPC extra
    grpc = None  # type: ignore
    GRPC_AVAILABLE = False
from sqlalchemy import delete, select

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
from mcpgateway.services.metrics import grpc_health_checks_counter, grpc_health_status_gauge
from mcpgateway.utils.grpc_validation import _validate_grpc_target, _validate_tls_path
from mcpgateway.utils.primary_worker import is_primary_worker


class GrpcMonitoringService:
    """Periodically persist health samples without using reflection as a probe."""

    def __init__(self) -> None:
        """Initialize the singleton monitor lifecycle state."""
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        """Start one monitor loop per process; only the primary performs checks."""
        if not GRPC_AVAILABLE:
            return
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        """Stop the monitor loop."""
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

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

    @classmethod
    def _channel(cls, service: DbGrpcService):
        """Create a validated bounded gRPC channel for one health probe."""
        _validate_grpc_target(service.target)
        options = [("grpc.max_receive_message_length", settings.mcpgateway_grpc_max_message_size)]
        if not service.tls_enabled:
            return grpc.insecure_channel(service.target, options=options)
        root_certificates = None
        private_key = None
        certificate_chain = None
        if service.tls_cert_path:
            cert_path = _validate_tls_path(service.tls_cert_path, "TLS cert path")
            root_certificates = cert_path.read_bytes()
            certificate_chain = root_certificates if service.tls_key_path else None
        if service.tls_key_path:
            key_path = _validate_tls_path(service.tls_key_path, "TLS key path")
            private_key = key_path.read_bytes()
        credentials = grpc.ssl_channel_credentials(root_certificates=root_certificates, private_key=private_key, certificate_chain=certificate_chain)
        return grpc.secure_channel(service.target, credentials, options=options)

    @classmethod
    def _check_blocking(cls, service: DbGrpcService) -> tuple[bool, str, str, Optional[str], float]:
        """Run Health/Check, falling back to channel readiness on UNIMPLEMENTED."""
        started = time.monotonic()
        channel = cls._channel(service)
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
                    if exc.code() != grpc.StatusCode.UNIMPLEMENTED:
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
            status_code = exc.code().name if exc.code() else "UNKNOWN"
            error = exc.details() or status_code
        except Exception as exc:  # pylint: disable=broad-except
            status_code = "UNAVAILABLE"
            error = str(exc)
        finally:
            channel.close()
        return healthy, check_type, status_code, error, (time.monotonic() - started) * 1000

    @classmethod
    async def check_service(cls, service_id: str) -> dict[str, Any]:
        """Check one service and persist the sample in an independent session."""
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
        with create_child_span("grpc.health.check", {"rpc.system": "grpc", "server.address": snapshot.target, "grpc.service.id": snapshot.id}):
            healthy, check_type, status_code, error, latency_ms = await asyncio.to_thread(cls._check_blocking, snapshot)
        with fresh_db_session() as write_db:
            service = write_db.get(DbGrpcService, service_id)
            if service is None:
                return {"status": "missing"}
            service.last_health_check = datetime.now(timezone.utc)
            if healthy:
                service.consecutive_failures = 0
                service.health_status = "healthy"
                service.last_health_error = None
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
            write_db.execute(delete(GrpcHealthSample).where(GrpcHealthSample.timestamp < datetime.now(timezone.utc) - timedelta(days=30)))
            status = service.health_status
            service_slug = service.slug
        grpc_health_checks_counter.labels(service=service_slug, check_type=check_type, outcome="success" if healthy else "failure").inc()
        grpc_health_status_gauge.labels(service=service_slug).set(1 if healthy else 0)
        return {"status": status, "healthy": healthy, "check_type": check_type, "status_code": status_code, "latency_ms": latency_ms, "error": error}

    async def _run(self) -> None:
        """Schedule jittered checks from the primary worker until shutdown."""
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
                    for service_id, interval, last_check in services:
                        last_check_utc = last_check.replace(tzinfo=timezone.utc) if last_check and last_check.tzinfo is None else last_check
                        jittered = max(10, int(interval * random.uniform(0.9, 1.1)))  # nosec B311 - operational jitter, not cryptographic
                        if last_check_utc is None or (now - last_check_utc).total_seconds() >= jittered:
                            await self.check_service(service_id)
                await asyncio.wait_for(self._stopping.wait(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(5)


_monitor = GrpcMonitoringService()


def get_grpc_monitoring_service() -> GrpcMonitoringService:
    """Return the process singleton monitor."""
    return _monitor
