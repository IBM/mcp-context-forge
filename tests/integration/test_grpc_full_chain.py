# -*- coding: utf-8 -*-
"""Integration tests for the full gRPC -> schema -> tool -> MCP chain.

Uses a real gRPC test server (``tests/grpc_test_server/server.py``) — no mocks.
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid

import grpc
import pytest
from sqlalchemy import select

from mcpgateway.config import settings
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.grpc_service import GrpcService

TEST_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "grpc_test_server")


def _free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(host, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ch = grpc.insecure_channel(f"{host}:{port}")
            grpc.channel_ready_future(ch).result(timeout=2)
            ch.close()
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _run(coro):
    """Run coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def grpc_server():
    """Start a plaintext gRPC test server with reflection enabled."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(TEST_SERVER_DIR, "server.py"), "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server("localhost", port, timeout=15):
            proc.kill()
            pytest.fail("gRPC test server did not start within timeout")
        yield ("localhost", port)
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture(scope="module")
def grpc_server_no_reflection():
    """Start a gRPC test server with reflection disabled."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(TEST_SERVER_DIR, "server.py"), "--port", str(port), "--no-reflection"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server("localhost", port, timeout=15):
            proc.kill()
            pytest.fail("gRPC test server (no reflection) did not start")
        yield ("localhost", port)
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture(autouse=True)
def _grpc_settings(monkeypatch, test_db):
    monkeypatch.setattr(settings, "mcpgateway_grpc_enabled", True)
    monkeypatch.setattr(settings, "ssrf_allow_localhost", True)
    monkeypatch.setattr(settings, "ssrf_allow_private_networks", True)
    # Make fresh_db_session and the monitoring service use test_db
    # so that in-memory SQLite data is visible across internal session boundaries.
    import mcpgateway.services.grpc_monitoring_service as mon_mod
    from contextlib import contextmanager

    @contextmanager
    def _use_test_db():
        try:
            yield test_db
            test_db.commit()
        except Exception:
            test_db.rollback()
            raise

    monkeypatch.setattr(mon_mod, "fresh_db_session", _use_test_db)


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _register(test_db, host, port, **kw):
    """Register a gRPC service synchronously."""
    from mcpgateway.schemas import GrpcServiceCreate
    svc = GrpcService()
    data = GrpcServiceCreate(
        name=f"echo-{uuid.uuid4().hex[:6]}",
        target=f"{host}:{port}",
        description="integration test",
        reflection_enabled=kw.get("reflection_enabled", True),
        tls_enabled=kw.get("tls_enabled", False),
        grpc_metadata=kw.get("metadata", {}) or {},
        discovery_mode=kw.get("discovery_mode", "auto"),
        health_check_enabled=True,
        health_check_interval=60,
        health_check_timeout=kw.get("health_check_timeout", 5),
        health_failure_threshold=3,
        tags=[],
        visibility="private",
    )
    return _run(svc.register_service(test_db, data, user_email="test@example.com"))


def _invoke(test_db, service_id, method, data, timeout=10):
    """Invoke a gRPC tool synchronously."""
    svc = GrpcService()
    return _run(svc.invoke_method(test_db, service_id, method, data, timeout=timeout))


def _health_check(service_id):
    """Run health check synchronously."""
    from mcpgateway.services.grpc_monitoring_service import GrpcMonitoringService
    return _run(GrpcMonitoringService.check_service(service_id))


def _tools_for(test_db, service_id):
    return test_db.execute(
        select(DbTool).where(DbTool.grpc_service_id == service_id)
    ).scalars().all()


# ══════════════════════════════════════════════════════════════════════
# Tests: Plaintext + Reflection
# ══════════════════════════════════════════════════════════════════════


class TestPlaintextReflectionFullChain:

    def test_register_and_reflect(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)
        assert registered.name is not None
        assert registered.method_count == 4  # Echo, EchoStream, EchoWithMetadata, EchoSlow

        tools = _tools_for(test_db, registered.id)
        names = {t.original_name for t in tools}
        assert "grpc_test.EchoService.Echo" in names
        assert "grpc_test.EchoService.EchoStream" in names

    def test_invoke_echo(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)
        result = _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                         {"message": "hello", "value": 42})
        assert result["message"] == "echo: hello"
        assert result["value"] == 84

    def test_invoke_echo_stream(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)
        result = _invoke(test_db, registered.id, "grpc_test.EchoService.EchoStream",
                         {"message": "stream", "value": 1})
        # Streaming results are wrapped: {"items": [...], "truncated": bool}
        items = result.get("items", [result])
        assert len(items) == 5
        assert items[0]["message"] == "chunk 1: stream"
        assert items[-1]["message"] == "chunk 5: stream"


# ══════════════════════════════════════════════════════════════════════
# Tests: Metadata Auth
# ══════════════════════════════════════════════════════════════════════


class TestMetadataAuth:

    def test_auth_success(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port,
                               metadata={"authorization": "Bearer test-token"})
        result = _invoke(test_db, registered.id, "grpc_test.EchoService.EchoWithMetadata",
                         {"message": "secret", "value": 1})
        assert "authenticated" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# Tests: No Reflection → Proto Import
# ══════════════════════════════════════════════════════════════════════


class TestNoReflectionProtoImport:

    def test_import_proto_and_invoke(self, test_db, grpc_server_no_reflection):
        host, port = grpc_server_no_reflection
        from mcpgateway.schemas import GrpcServiceCreate

        svc = GrpcService()
        data = GrpcServiceCreate(
            name=f"noref-{uuid.uuid4().hex[:6]}",
            target=f"{host}:{port}",
            description="no reflection test",
            reflection_enabled=False,
            discovery_mode="artifact",
            health_check_enabled=True,
            health_check_interval=60,
            health_check_timeout=5,
            health_failure_threshold=3,
            tags=[],
            visibility="private",
        )
        registered = _run(svc.register_service(test_db, data, user_email="test@example.com"))

        db_svc = test_db.get(DbGrpcService, registered.id)
        assert db_svc.reflection_enabled is False

        # Import proto file
        proto_path = os.path.join(TEST_SERVER_DIR, "echo.proto")
        with open(proto_path, "rb") as f:
            payload = f.read()

        # Use GrpcService.import_schema which handles tool sync after activation
        svc2 = GrpcService()
        artifact = _run(svc2.import_schema(
            test_db, registered.id, payload, "echo.proto", "test@example.com", activate=True,
        ))
        assert artifact is not None

        tools = _tools_for(test_db, registered.id)
        names = {t.original_name for t in tools}
        assert "grpc_test.EchoService.Echo" in names, f"Got: {names}"

        result = _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                         {"message": "proto", "value": 10})
        assert result["message"] == "echo: proto"


# ══════════════════════════════════════════════════════════════════════
# Tests: Deadline / Timeout
# ══════════════════════════════════════════════════════════════════════


class TestDeadlineTimeout:

    def test_timeout(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)

        # EchoSlow takes 3s; 1s timeout should fail
        with pytest.raises(Exception):
            _invoke(test_db, registered.id, "grpc_test.EchoService.EchoSlow",
                    {"message": "slow", "value": 1}, timeout=1)

    def test_slow_but_within_timeout(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)

        # EchoSlow takes 3s; 10s timeout should succeed
        result = _invoke(test_db, registered.id, "grpc_test.EchoService.EchoSlow",
                         {"message": "slow-ok", "value": 1}, timeout=10)
        assert "slow" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# Tests: Health Check
# ══════════════════════════════════════════════════════════════════════


class TestHealthCheck:

    def test_health_check_healthy(self, test_db, grpc_server):
        host, port = grpc_server
        registered = _register(test_db, host, port)
        result = _health_check(registered.id)
        assert result["status"] == "healthy"
        assert result["healthy"] is True

    def test_health_check_unhealthy(self, test_db):
        """Dead port should report unhealthy."""
        registered = _register(test_db, "127.0.0.1", 1,
                               reflection_enabled=False,
                               health_check_timeout=2)
        result = _health_check(registered.id)
        assert result["healthy"] is False
