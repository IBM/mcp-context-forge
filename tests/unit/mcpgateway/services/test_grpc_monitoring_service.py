# -*- coding: utf-8 -*-
"""Tests for standards-based gRPC health monitoring."""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
from mcpgateway.services.grpc_monitoring_service import GrpcMonitoringService


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
    monkeypatch.setattr(GrpcMonitoringService, "_check_blocking", staticmethod(lambda _service: outcomes.pop(0)))

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
    monkeypatch.setattr(GrpcMonitoringService, "_channel", classmethod(lambda cls, _service: FakeChannel()))
    service = SimpleNamespace(target="grpc.example.com:443", health_check_timeout=5, grpc_metadata={})

    healthy, check_type, status_code, error, _latency = GrpcMonitoringService._check_blocking(service)

    assert healthy is True
    assert check_type == "readiness"
    assert status_code == "READY"
    assert error is None
    assert readiness_calls == [5]


async def test_grpc_metrics_combines_closed_rollup_and_live_hour(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_grpc_enabled", True)
    service = DbGrpcService(name="metrics-service", slug="metrics-service", target="grpc.example.com:443", visibility="private")
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
    assert grpc_schema._require_service_access(request, {"email": "owner@example.com"}, test_db, service.id).id == service.id  # pylint: disable=protected-access
