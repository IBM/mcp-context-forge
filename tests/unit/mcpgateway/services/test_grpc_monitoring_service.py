# -*- coding: utf-8 -*-
"""Tests for standards-based gRPC health monitoring."""

# Standard
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from starlette.requests import Request

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import GrpcHealthSample, GrpcMetricsHourly, ToolMetric
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import Tool as DbTool
from mcpgateway.routers import grpc_schema
from mcpgateway.services import grpc_monitoring_service as module
from mcpgateway.services.grpc_monitoring_service import GrpcMonitoringService, GRPC_AVAILABLE


async def test_health_samples_apply_failure_threshold_and_recover(test_db, monkeypatch):
    service = DbGrpcService(
        name="monitored-service",
        slug="monitored-service",
        target="grpc.example.com:443",
        visibility="private",
        reachable=True,
        health_failure_threshold=3,
    )
    test_db.add(service)
    test_db.commit()

    @contextmanager
    def use_test_session():
        try:
            yield test_db
            test_db.commit()
        except Exception:
            test_db.rollback()
            raise

    outcomes = [
        (False, "health", "UNAVAILABLE", "upstream unavailable", 5.0),
        (False, "health", "UNAVAILABLE", "upstream unavailable", 6.0),
        (False, "health", "UNAVAILABLE", "upstream unavailable", 7.0),
        (True, "health", "SERVING", None, 2.0),
    ]

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(module, "fresh_db_session", use_test_session)
    monkeypatch.setattr(module.asyncio, "to_thread", run_inline)
    monkeypatch.setattr(GrpcMonitoringService, "_check_blocking", staticmethod(lambda _channel, _service: outcomes.pop(0)))

    assert (await GrpcMonitoringService.check_service(service.id))["status"] == "degraded"
    assert (await GrpcMonitoringService.check_service(service.id))["status"] == "degraded"
    assert (await GrpcMonitoringService.check_service(service.id))["status"] == "unhealthy"
    test_db.refresh(service)
    assert service.consecutive_failures == 3
    assert service.reachable is False

    assert (await GrpcMonitoringService.check_service(service.id))["status"] == "healthy"
    test_db.refresh(service)
    assert service.consecutive_failures == 0
    assert service.reachable is True
    assert len(list(test_db.execute(select(GrpcHealthSample).where(GrpcHealthSample.grpc_service_id == service.id)).scalars())) == 4


def test_unimplemented_health_service_falls_back_to_channel_readiness(monkeypatch):
    unimplemented = SimpleNamespace(name="UNIMPLEMENTED")
    readiness_calls = []

    class FakeRpcError(Exception):
        def code(self):
            return unimplemented

        def details(self):
            return "not implemented"

    class FakeChannel:
        def close(self):
            return None

    class FakeHealthStub:
        def __init__(self, _channel):
            return None

        def Check(self, _request, **_kwargs):
            raise FakeRpcError()

    class FakeReadyFuture:
        def result(self, timeout):
            readiness_calls.append(timeout)

    fake_grpc = SimpleNamespace(
        RpcError=FakeRpcError,
        StatusCode=SimpleNamespace(UNIMPLEMENTED=unimplemented),
        channel_ready_future=lambda _channel: FakeReadyFuture(),
    )
    fake_health_pb2 = SimpleNamespace(
        HealthCheckRequest=lambda service: SimpleNamespace(service=service),
        HealthCheckResponse=SimpleNamespace(SERVING=1, ServingStatus=SimpleNamespace(Name=str)),
    )
    monkeypatch.setattr(module, "grpc", fake_grpc)
    monkeypatch.setattr(module, "health_pb2", fake_health_pb2)
    monkeypatch.setattr(module, "health_pb2_grpc", SimpleNamespace(HealthStub=FakeHealthStub))
    monkeypatch.setattr(module, "GRPC_HEALTH_AVAILABLE", True)
    monkeypatch.setattr(GrpcMonitoringService, "_build_channel", classmethod(lambda cls, _service: FakeChannel()))
    # Provide a pooled channel via _get_channel (instance method)
    fake_channel = FakeChannel()
    monkeypatch.setattr(GrpcMonitoringService, "_get_channel", lambda self, _service: fake_channel)
    service = SimpleNamespace(target="grpc.example.com:443", health_check_timeout=5, grpc_metadata={})

    healthy, check_type, status_code, error, _latency = GrpcMonitoringService._check_blocking(fake_channel, service)

    assert healthy is True
    assert check_type == "readiness"
    assert status_code == "READY"
    assert error is None
    assert readiness_calls == [5]


async def test_grpc_metrics_combines_closed_rollup_and_live_hour(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_grpc_enabled", True)
    service = DbGrpcService(
        name="metrics-service",
        slug="metrics-service",
        target="grpc.example.com:443",
        visibility="private",
        owner_email="admin@example.com",
    )
    test_db.add(service)
    test_db.flush()
    tool = DbTool(
        original_name="demo.Greeter.SayHello",
        custom_name="demo.Greeter.SayHello",
        custom_name_slug="demo-greeter-sayhello",
        display_name="Say Hello",
        url=service.target,
        original_description="gRPC method",
        description="gRPC method",
        integration_type="gRPC",
        input_schema={"type": "object"},
        annotations={},
        created_by="system",
        visibility="private",
        grpc_service_id=service.id,
    )
    test_db.add(tool)
    test_db.flush()
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    test_db.add(
        GrpcMetricsHourly(
            grpc_service_id=service.id,
            service_name=service.name,
            method_name=tool.original_name,
            hour_start=current_hour - timedelta(hours=1),
            total_count=2,
            success_count=1,
            failure_count=1,
            status_counts={"OK": 1, "UNAVAILABLE": 1},
            p50_response_time=0.2,
            p95_response_time=0.3,
            p99_response_time=0.3,
            request_bytes=20,
            response_bytes=40,
        )
    )
    test_db.add(
        ToolMetric(
            tool_id=tool.id,
            timestamp=datetime.now(timezone.utc),
            response_time=0.1,
            is_success=True,
            protocol="gRPC",
            status_code="OK",
            request_bytes=10,
            response_bytes=15,
        )
    )
    test_db.commit()

    request = Request({"type": "http", "method": "GET", "path": f"/admin/grpc/{service.id}/metrics", "headers": []})
    request.state.token_teams = None
    result = await grpc_schema.grpc_metrics.__wrapped__(service.id, request, hours=24, method=None, db=test_db, user={"email": "admin@example.com", "is_admin": True})

    assert result["total_calls"] == 3
    assert result["failure_count"] == 1
    assert result["status_distribution"] == {"OK": 2, "UNAVAILABLE": 1}
    assert result["request_bytes"] == 30
    assert len(result["trend"]) == 2


def test_grpc_metrics_hides_private_service_outside_token_scope(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_grpc_enabled", True)
    service = DbGrpcService(
        name="private-metrics-service",
        slug="private-metrics-service",
        target="grpc.example.com:443",
        visibility="private",
        owner_email="owner@example.com",
    )
    test_db.add(service)
    test_db.commit()
    request = Request({"type": "http", "method": "GET", "path": f"/admin/grpc/{service.id}/metrics", "headers": []})
    request.state.token_teams = []

    with pytest.raises(HTTPException) as exc_info:
        grpc_schema._require_service_access(request, {"email": "other@example.com"}, test_db, service.id)  # pylint: disable=protected-access

    assert exc_info.value.status_code == 404

    # A public-only token suppresses private owner visibility by design.
    with pytest.raises(HTTPException) as owner_public_only:
        grpc_schema._require_service_access(request, {"email": "owner@example.com"}, test_db, service.id)  # pylint: disable=protected-access
    assert owner_public_only.value.status_code == 404

    # A team-scoped token may still owner-match a private service.
    request.state.token_teams = ["team-a"]
    assert grpc_schema._require_service_access(request, {"email": "owner@example.com"}, test_db, service.id).id == service.id  # pylint: disable=protected-access

# ============================================================================

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.db import GrpcHealthSample
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.services import grpc_monitoring_service as module
from mcpgateway.services.grpc_monitoring_service import GrpcMonitoringService, GRPC_AVAILABLE

# Channel pool, concurrency, availability, and last-health-success tests
# ============================================================================

class TestChannelReuse:
    """Tests for channel pooling."""

    def test_mtls_health_channel_uses_client_chain_pair(self, monkeypatch, tmp_path):
        cert_path = tmp_path / "client.pem"
        key_path = tmp_path / "client.key"
        cert_path.write_bytes(b"client-chain")
        key_path.write_bytes(b"private-key")
        fake_grpc = MagicMock()
        fake_grpc.ssl_channel_credentials.return_value = "credentials"
        monkeypatch.setattr(module, "grpc", fake_grpc)
        monkeypatch.setattr(module, "_validate_grpc_target", lambda _target: None)
        monkeypatch.setattr(module, "_validate_tls_path", lambda path, _label: Path(path))
        service = SimpleNamespace(target="svc:443", tls_enabled=True, tls_cert_path=str(cert_path), tls_key_path=str(key_path))

        GrpcMonitoringService._build_channel(service)  # pylint: disable=protected-access

        fake_grpc.ssl_channel_credentials.assert_called_once_with(private_key=b"private-key", certificate_chain=b"client-chain")

    def test_health_channel_rejects_key_without_certificate(self, monkeypatch, tmp_path):
        key_path = tmp_path / "client.key"
        key_path.write_bytes(b"private-key")
        monkeypatch.setattr(module, "_validate_grpc_target", lambda _target: None)
        service = SimpleNamespace(target="svc:443", tls_enabled=True, tls_cert_path=None, tls_key_path=str(key_path))

        with pytest.raises(ValueError, match="requires a TLS certificate"):
            GrpcMonitoringService._build_channel(service)  # pylint: disable=protected-access

    def test_tls_path_is_validated_before_file_open(self, monkeypatch):
        service = SimpleNamespace(target="svc:443", tls_enabled=True, tls_cert_path="/tmp/outside.pem", tls_key_path=None)
        monkeypatch.setattr(module, "_validate_grpc_target", lambda _target: None)

        def unexpected_open(*_args, **_kwargs):
            raise AssertionError("unvalidated path was opened")

        monkeypatch.setattr(module.os, "open", unexpected_open)

        with pytest.raises(module.GrpcServiceError, match="outside allowed certificate directories"):
            GrpcMonitoringService()._get_channel(service)  # pylint: disable=protected-access

    def test_tls_reader_rejects_fifo_without_blocking(self, monkeypatch, tmp_path):
        fifo_path = tmp_path / "certificate.pipe"
        os.mkfifo(fifo_path)
        monkeypatch.setattr(module, "_validate_tls_path", lambda _path, _label: fifo_path)

        with pytest.raises(module.GrpcServiceError, match="must be a regular file"):
            GrpcMonitoringService._read_tls_file(str(fifo_path), "TLS cert path")  # pylint: disable=protected-access

    def test_tls_reader_rejects_oversized_file(self, monkeypatch, tmp_path):
        cert_path = tmp_path / "oversized.pem"
        cert_path.touch()
        os.truncate(cert_path, module._TLS_MATERIAL_MAX_BYTES + 1)  # pylint: disable=protected-access
        monkeypatch.setattr(module, "_validate_tls_path", lambda _path, _label: cert_path)

        with pytest.raises(module.GrpcServiceError, match="exceeds"):
            GrpcMonitoringService._read_tls_file(str(cert_path), "TLS cert path")  # pylint: disable=protected-access
    def test_same_target_reuses_channel(self, monkeypatch):
        """_get_channel returns the same channel for identical service configs."""
        if not GRPC_AVAILABLE:
            pytest.skip("gRPC not available")

        monitor = GrpcMonitoringService()
        build_count = [0]
        monkeypatch.setattr(module, "_validate_grpc_target", lambda _target: None)

        class FakeChannel:
            def close(self):
                pass

        def fake_build(_service, _tls_material=None, *, target_validated=False):
            assert target_validated is True
            build_count[0] += 1
            return FakeChannel()

        monkeypatch.setattr(monitor, "_build_channel", fake_build)

        svc_a = SimpleNamespace(
            target="svc:50051", tls_enabled=False, tls_cert_path=None, tls_key_path=None,
            health_check_timeout=5,
        )
        svc_b = SimpleNamespace(
            target="svc:50051", tls_enabled=False, tls_cert_path=None, tls_key_path=None,
            health_check_timeout=5,
        )

        ch1 = monitor._get_channel(svc_a)  # pylint: disable=protected-access
        ch2 = monitor._get_channel(svc_b)  # pylint: disable=protected-access

        assert ch1 is ch2
        assert build_count[0] == 1  # Only built once

    def test_different_target_creates_separate_channel(self, monkeypatch):
        """_get_channel creates separate channels for different targets."""
        if not GRPC_AVAILABLE:
            pytest.skip("gRPC not available")

        monitor = GrpcMonitoringService()
        channels_built = []
        monkeypatch.setattr(module, "_validate_grpc_target", lambda _target: None)

        class FakeChannel:
            def __init__(self, label):
                self.label = label

            def close(self):
                pass

        def fake_build(service, _tls_material=None, *, target_validated=False):
            assert target_validated is True
            ch = FakeChannel(service.target)
            channels_built.append(ch)
            return ch

        monkeypatch.setattr(monitor, "_build_channel", fake_build)

        svc_a = SimpleNamespace(
            target="svc-a:50051", tls_enabled=False, tls_cert_path=None, tls_key_path=None,
            health_check_timeout=5,
        )
        svc_b = SimpleNamespace(
            target="svc-b:50051", tls_enabled=False, tls_cert_path=None, tls_key_path=None,
            health_check_timeout=5,
        )

        ch1 = monitor._get_channel(svc_a)  # pylint: disable=protected-access
        ch2 = monitor._get_channel(svc_b)  # pylint: disable=protected-access

        assert ch1 is not ch2
        assert ch1.label == "svc-a:50051"
        assert ch2.label == "svc-b:50051"

    def test_prune_removes_idle_channels(self, monkeypatch):
        """_prune_channels closes channels unused beyond TTL."""
        if not GRPC_AVAILABLE:
            pytest.skip("gRPC not available")

        monitor = GrpcMonitoringService()
        closed = []

        class FakeChannel:
            def close(self):
                closed.append(1)

        # Manually insert an old channel entry
        import time
        from mcpgateway.services.grpc_monitoring_service import _HealthChannel, _CHANNEL_IDLE_TTL

        key = ("old-target:50051", False, "", "")
        entry = _HealthChannel(FakeChannel())
        entry.last_used = time.monotonic() - _CHANNEL_IDLE_TTL - 10  # definitely stale
        with monitor._channel_lock:
            monitor._health_channels[key] = entry

        monitor._prune_channels()  # pylint: disable=protected-access

        assert len(closed) == 1
        with monitor._channel_lock:
            assert key not in monitor._health_channels


class TestLastHealthSuccess:
    """Tests for last_health_success tracking."""

    @pytest.mark.asyncio
    async def test_last_health_success_set_on_healthy(self, test_db, monkeypatch):
        """check_service sets last_health_success when the check is healthy."""
        from contextlib import contextmanager

        async def run_inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        monkeypatch.setattr(module.asyncio, "to_thread", run_inline)
        service = DbGrpcService(
            name="success-tracker",
            slug="success-tracker",
            target="grpc.example.com:443",
            visibility="private",
            health_failure_threshold=3,
        )
        test_db.add(service)
        test_db.commit()

        @contextmanager
        def use_test_session():
            try:
                yield test_db
                test_db.commit()
            except Exception:
                test_db.rollback()
                raise

        monkeypatch.setattr(module, "fresh_db_session", use_test_session)

        # Provide a mock channel
        class FakeChannel:
            def close(self):
                pass

        fake_ch = FakeChannel()
        monitor = module.get_grpc_monitoring_service()
        monkeypatch.setattr(monitor, "_get_channel", lambda _svc: fake_ch)

        # Mock the blocking check to return healthy
        monkeypatch.setattr(
            GrpcMonitoringService, "_check_blocking",
            staticmethod(lambda _channel, _service: (True, "health", "SERVING", None, 2.0)),
        )

        result = await GrpcMonitoringService.check_service(service.id)

        assert result["status"] == "healthy"
        assert result["healthy"] is True
        assert result["last_health_success"] is not None
        assert result["availability_24h"] is not None

        test_db.refresh(service)
        assert service.last_health_success is not None

    @pytest.mark.asyncio
    async def test_last_health_success_not_updated_on_failure(self, test_db, monkeypatch):
        """last_health_success is not overwritten by a failed check."""
        from contextlib import contextmanager

        async def run_inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        monkeypatch.setattr(module.asyncio, "to_thread", run_inline)
        initial_success = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        service = DbGrpcService(
            name="failure-tracker",
            slug="failure-tracker",
            target="grpc.example.com:443",
            visibility="private",
            health_failure_threshold=3,
            last_health_success=initial_success,
        )
        test_db.add(service)
        test_db.commit()

        @contextmanager
        def use_test_session():
            try:
                yield test_db
                test_db.commit()
            except Exception:
                test_db.rollback()
                raise

        monkeypatch.setattr(module, "fresh_db_session", use_test_session)

        class FakeChannel:
            def close(self):
                pass

        fake_ch = FakeChannel()
        monitor = module.get_grpc_monitoring_service()
        monkeypatch.setattr(monitor, "_get_channel", lambda _svc: fake_ch)

        monkeypatch.setattr(
            GrpcMonitoringService, "_check_blocking",
            staticmethod(lambda _channel, _service: (False, "health", "UNAVAILABLE", "UNAVAILABLE: upstream down", 5.0)),
        )

        result = await GrpcMonitoringService.check_service(service.id)

        assert result["healthy"] is False
        test_db.refresh(service)
        # last_health_success should still be the initial value, not overwritten
        # SQLite strips timezone info on round-trip; compare by replacing tzinfo
        actual = service.last_health_success
        assert actual is not None
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        assert actual == initial_success


class TestAvailabilityRate:
    """Tests for _availability_rate calculation."""

    def test_availability_rate_returns_none_when_no_samples(self, test_db):
        """Returns None when there are no samples in the window."""
        service = DbGrpcService(
            name="no-samples-svc",
            slug="no-samples-svc",
            target="grpc.example.com:443",
            visibility="private",
        )
        test_db.add(service)
        test_db.commit()

        rate = GrpcMonitoringService._availability_rate(test_db, service.id)  # pylint: disable=protected-access
        assert rate is None

        # Clean up to avoid polluting test_db for other tests
        test_db.delete(service)
        test_db.commit()

    def test_availability_rate_calculates_ratio(self, test_db):
        """Calculates correct healthy/total ratio from samples."""
        service = DbGrpcService(
            name="avail-svc",
            slug="avail-svc",
            target="grpc.example.com:443",
            visibility="private",
        )
        test_db.add(service)
        test_db.commit()

        now = datetime.now(timezone.utc)
        # 8 healthy + 2 unhealthy = 80%
        for i in range(8):
            test_db.add(
                GrpcHealthSample(
                    grpc_service_id=service.id,
                    timestamp=now - timedelta(minutes=i * 30),
                    healthy=True,
                    check_type="health",
                    status_code="SERVING",
                    latency_ms=2.0,
                )
            )
        for i in range(2):
            test_db.add(
                GrpcHealthSample(
                    grpc_service_id=service.id,
                    timestamp=now - timedelta(minutes=i * 30 + 15),
                    healthy=False,
                    check_type="health",
                    status_code="UNAVAILABLE",
                    latency_ms=5000.0,
                    error_message="upstream down",
                )
            )
        test_db.commit()

        rate = GrpcMonitoringService._availability_rate(test_db, service.id)  # pylint: disable=protected-access
        assert rate == 0.8

        # Clean up to avoid polluting test_db for other tests
        for sample in test_db.query(GrpcHealthSample).filter(GrpcHealthSample.grpc_service_id == service.id).all():
            test_db.delete(sample)
        test_db.delete(service)
        test_db.commit()

    def test_availability_rate_custom_window(self, test_db):
        """Respects custom window_hours parameter."""
        service = DbGrpcService(
            name="window-svc",
            slug="window-svc",
            target="grpc.example.com:443",
            visibility="private",
        )
        test_db.add(service)
        test_db.commit()

        now = datetime.now(timezone.utc)
        # Sample from 2 days ago (outside 24h window)
        test_db.add(
            GrpcHealthSample(
                grpc_service_id=service.id,
                timestamp=now - timedelta(hours=25),
                healthy=False,
                check_type="health",
                status_code="UNAVAILABLE",
                latency_ms=5000.0,
            )
        )
        # Sample from 1 hour ago (inside 24h window)
        test_db.add(
            GrpcHealthSample(
                grpc_service_id=service.id,
                timestamp=now - timedelta(hours=1),
                healthy=True,
                check_type="health",
                status_code="SERVING",
                latency_ms=2.0,
            )
        )
        test_db.commit()

        # 24h window: only the recent sample
        rate_24h = GrpcMonitoringService._availability_rate(test_db, service.id, window_hours=24)  # pylint: disable=protected-access
        assert rate_24h == 1.0

        # 48h window: both samples
        rate_48h = GrpcMonitoringService._availability_rate(test_db, service.id, window_hours=48)  # pylint: disable=protected-access
        assert rate_48h == 0.5

        # Clean up to avoid polluting test_db for other tests
        for sample in test_db.query(GrpcHealthSample).filter(GrpcHealthSample.grpc_service_id == service.id).all():
            test_db.delete(sample)
        test_db.delete(service)
        test_db.commit()


class TestConcurrentChecks:
    """Tests for concurrent health check execution."""

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrency(self, monkeypatch):
        """Verify that concurrent checks respect the semaphore limit."""
        monitor = GrpcMonitoringService()
        monitor._max_concurrent = 2  # pylint: disable=protected-access
        running = 0
        max_running = 0
        check_count = 0

        async def fake_check_service(sid):
            nonlocal running, max_running, check_count
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            check_count += 1
            running -= 1

        monkeypatch.setattr(monitor, "check_service", fake_check_service)
        monkeypatch.setattr(module, "is_primary_worker", lambda: True)

        # Simulate one iteration of _run by directly testing gather with semaphore
        due = ["a", "b", "c", "d", "e"]  # 5 services due
        sem = asyncio.Semaphore(2)

        async def _check_one(sid):
            async with sem:
                await monitor.check_service(sid)

        await asyncio.gather(*(_check_one(sid) for sid in due), return_exceptions=True)

        assert check_count == 5
        assert max_running <= 2  # never exceeded semaphore
