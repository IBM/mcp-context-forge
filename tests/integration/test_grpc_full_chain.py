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


def _register(test_db, host, port, name=None, **kw):
    """Register a gRPC service synchronously."""
    from mcpgateway.schemas import GrpcServiceCreate
    svc = GrpcService()
    svc_name = name or f"echo-{uuid.uuid4().hex[:6]}"
    data = GrpcServiceCreate(
        name=svc_name,
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
        assert registered.method_count == 6  # Echo, EchoStream, EchoWithMetadata, EchoSlow, EchoV1, EchoV2

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

# ══════════════════════════════════════════════════════════════════════
# Fixture: TLS server
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def grpc_server_tls():
    """Start a gRPC test server with TLS enabled."""
    port = _free_port()
    env = os.environ.copy()
    env.setdefault("GRPC_VERBOSITY", "ERROR")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(TEST_SERVER_DIR, "server.py"), "--tls", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    time.sleep(3)
    try:
        if proc.poll() is not None:
            _out, _err = proc.communicate()
            pytest.fail(f"TLS server exited early (port={port}): {_err[:300]}")
        # Copy cert to <project_root>/certs/ so _validate_tls_path accepts it
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        certs_dir = os.path.join(project_root, "certs")
        os.makedirs(certs_dir, exist_ok=True)
        src_cert = os.path.join(TEST_SERVER_DIR, "server.crt")
        dst_cert = os.path.join(certs_dir, "server.crt")
        src_key = os.path.join(TEST_SERVER_DIR, "server.key")
        dst_key = os.path.join(certs_dir, "server.key")
        if os.path.exists(src_cert):
            import shutil
            shutil.copy(src_cert, dst_cert)
            shutil.copy(src_key, dst_key)
        yield ("localhost", port, dst_cert, dst_key)
    finally:
        proc.kill()
        proc.wait(timeout=5)


# ══════════════════════════════════════════════════════════════════════
# Tests: TLS
# ══════════════════════════════════════════════════════════════════════


class TestTls:

    def test_tls_register_and_invoke(self, test_db, grpc_server_tls):
        """Register a TLS-enabled gRPC service and verify tools are created.

        Note: actual TLS invocation requires proper CA infrastructure. This test
        validates that the service registration, schema import, and tool sync
        work correctly with TLS configuration (cert and key paths stored).
        """
        host, port, cert_path, key_path = grpc_server_tls

        from mcpgateway.schemas import GrpcServiceCreate

        svc = GrpcService()
        data = GrpcServiceCreate(
            name=f"echo-tls-{uuid.uuid4().hex[:6]}",
            target=f"{host}:{port}",
            description="TLS integration test",
            reflection_enabled=False,
            tls_enabled=True,
            tls_cert_path=cert_path,
            tls_key_path=key_path,
            discovery_mode="artifact",
            health_check_enabled=True,
            health_check_interval=60,
            health_check_timeout=5,
            health_failure_threshold=3,
            tags=[],
            visibility="private",
        )
        registered = _run(svc.register_service(test_db, data, user_email="test@example.com"))
        assert registered.name is not None
        assert registered.tls_enabled is True

        # Import proto since reflection is disabled
        proto_path = os.path.join(TEST_SERVER_DIR, "echo.proto")
        with open(proto_path, "rb") as f:
            payload = f.read()
        _run(svc.import_schema(
            test_db, registered.id, payload, "echo.proto", "test@example.com", activate=True,
        ))

        tools = _tools_for(test_db, registered.id)
        names = {t.original_name for t in tools}
        assert "grpc_test.EchoService.Echo" in names, f"Got tools: {names}"
        assert len(names) == 6  # all RPCs


# ══════════════════════════════════════════════════════════════════════
# Tests: Schema Change
# ══════════════════════════════════════════════════════════════════════


class TestSchemaChange:

    def test_schema_v1_to_v2(self, test_db, grpc_server_no_reflection):
        host, port = grpc_server_no_reflection
        from mcpgateway.schemas import GrpcServiceCreate

        svc = GrpcService()
        data = GrpcServiceCreate(
            name=f"schema-v1-{uuid.uuid4().hex[:6]}",
            target=f"{host}:{port}",
            description="schema change test",
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

        # Import proto → tools created for all methods
        proto_path = os.path.join(TEST_SERVER_DIR, "echo.proto")
        with open(proto_path, "rb") as f:
            payload = f.read()

        artifact = _run(svc.import_schema(
            test_db, registered.id, payload, "echo.proto", "test@example.com", activate=True,
        ))
        assert artifact is not None

        tools = _tools_for(test_db, registered.id)
        names = {t.original_name for t in tools}
        assert "grpc_test.EchoService.EchoV1" in names, f"Got tools: {names}"
        assert "grpc_test.EchoService.EchoV2" in names, f"Got tools: {names}"

        # Invoke v1
        r1 = _invoke(test_db, registered.id, "grpc_test.EchoService.EchoV1",
                     {"name": "test", "value": 42})
        assert "v1:" in r1["result"]

        # Invoke v2 with new priority field
        r2 = _invoke(test_db, registered.id, "grpc_test.EchoService.EchoV2",
                     {"name": "test", "value": 42, "priority": 1})
        assert "v2:" in r2["result"]
        assert r2["priority"] == 1

    def test_schema_diff(self, test_db, grpc_server):
        host, port = grpc_server
        svc = GrpcService()
        registered = _register(test_db, host, port)

        proto_path = os.path.join(TEST_SERVER_DIR, "echo.proto")
        with open(proto_path, "rb") as f:
            payload = f.read()

        a1 = _run(svc.import_schema(
            test_db, registered.id, payload, "echo.proto", "test@example.com", activate=True,
        ))
        diff = _run(svc.diff_schemas(
            test_db, registered.id, left_id=a1.id, right_id=a1.id,
        ))
        assert diff is not None

# ══════════════════════════════════════════════════════════════════════
# Tests: gRPC Error Codes (via Echo value triggers)
# ══════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════
# Tests: gRPC Error Codes (via Echo value triggers)
# ══════════════════════════════════════════════════════════════════════


class TestGrpcErrorCodes:

    def test_invalid_argument(self, test_db, grpc_server):
        """value < 0 → INVALID_ARGUMENT from server."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                    {"message": "bad", "value": -1})
        assert "INVALID_ARGUMENT" in str(exc.value) or "value must be" in str(exc.value)

    def test_not_found(self, test_db, grpc_server):
        """value == 0 → NOT_FOUND from server."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                    {"message": "missing", "value": 0})
        assert "NOT_FOUND" in str(exc.value) or "zero value" in str(exc.value)

    def test_resource_exhausted(self, test_db, grpc_server):
        """value > 100 → RESOURCE_EXHAUSTED from server."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                    {"message": "big", "value": 200})
        assert "RESOURCE_EXHAUSTED" in str(exc.value) or "exceeds limit" in str(exc.value)

    def test_internal_error(self, test_db, grpc_server):
        """value == 500 → INTERNAL from server."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                    {"message": "boom", "value": 500})
        assert "INTERNAL" in str(exc.value) or "simulated internal error" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════
# Tests: Client-side and Lifecycle Errors
# ══════════════════════════════════════════════════════════════════════


class TestClientErrors:

    def test_method_not_found(self, test_db, grpc_server):
        """Calling a non-existent method raises an error."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.NoSuchMethod",
                    {"message": "x", "value": 1})
        assert "NoSuchMethod" in str(exc.value) or "UNIMPLEMENTED" in str(exc.value) or "not found" in str(exc.value).lower()

    def test_duplicate_service_name(self, test_db, grpc_server):
        """Registering the same name twice raises a conflict error."""
        host, port = grpc_server
        name = f"dup-{uuid.uuid4().hex[:6]}"
        _register(test_db, host, port, name=name)
        with pytest.raises(Exception) as exc:
            _register(test_db, host, port, name=name)
        assert "conflict" in str(exc.value).lower() or "already exists" in str(exc.value).lower()

    def test_connection_refused(self, test_db):
        """Target with a dead port raises UNAVAILABLE."""
        registered = _register(test_db, "127.0.0.1", 19999,  # unlikely to be listening
                               reflection_enabled=False, health_check_timeout=2)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.Echo",
                    {"message": "x", "value": 1}, timeout=3)
        err = str(exc.value).lower()
        assert "unavailable" in err or "refused" in err or "failed to connect" in err

    def test_invalid_target_format(self, test_db):
        """Malformed target is rejected at Pydantic validation time."""
        from mcpgateway.schemas import GrpcServiceCreate
        with pytest.raises(Exception) as exc:
            GrpcServiceCreate(
                name=f"bad-target-{uuid.uuid4().hex[:6]}",
                target="not-a-valid-target",
                description="bad target",
                reflection_enabled=False,
                discovery_mode="artifact",
                health_check_enabled=True, health_check_interval=60,
                health_check_timeout=5, health_failure_threshold=3,
                tags=[], visibility="private",
            )
        err = str(exc.value).lower()
        assert "target" in err or "host:port" in err

    def test_wrong_auth_token(self, test_db, grpc_server):
        """EchoWithMetadata with wrong auth token → UNAUTHENTICATED."""
        host, port = grpc_server
        registered = _register(test_db, host, port,
                               metadata={"authorization": "Bearer wrong-token"})
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.EchoWithMetadata",
                    {"message": "x", "value": 1})
        err = str(exc.value).lower()
        assert "unauthenticated" in err or "expected" in err

    def test_missing_auth_token(self, test_db, grpc_server):
        """EchoWithMetadata without auth metadata → UNAUTHENTICATED."""
        host, port = grpc_server
        registered = _register(test_db, host, port)
        with pytest.raises(Exception) as exc:
            _invoke(test_db, registered.id, "grpc_test.EchoService.EchoWithMetadata",
                    {"message": "x", "value": 1})
        err = str(exc.value).lower()
        assert "unauthenticated" in err or "expected" in err


# ══════════════════════════════════════════════════════════════════════
# Tests: Schema Validation Errors
# ══════════════════════════════════════════════════════════════════════


class TestSchemaErrors:

    def test_import_invalid_proto(self, test_db, grpc_server_no_reflection):
        """Importing garbage bytes as proto raises an error."""
        host, port = grpc_server_no_reflection
        svc = GrpcService()
        from mcpgateway.schemas import GrpcServiceCreate
        data = GrpcServiceCreate(
            name=f"bad-schema-{uuid.uuid4().hex[:6]}",
            target=f"{host}:{port}",
            description="bad schema",
            reflection_enabled=False,
            discovery_mode="artifact",
            health_check_enabled=True, health_check_interval=60,
            health_check_timeout=5, health_failure_threshold=3,
            tags=[], visibility="private",
        )
        registered = _run(svc.register_service(test_db, data, user_email="test@example.com"))
        with pytest.raises(Exception):
            _run(svc.import_schema(
                test_db, registered.id, b"not a valid proto file",
                "garbage.bin", "test@example.com", activate=True,
            ))

    def test_import_empty_file(self, test_db, grpc_server_no_reflection):
        """Importing an empty file raises an error."""
        host, port = grpc_server_no_reflection
        svc = GrpcService()
        from mcpgateway.schemas import GrpcServiceCreate
        data = GrpcServiceCreate(
            name=f"empty-schema-{uuid.uuid4().hex[:6]}",
            target=f"{host}:{port}",
            description="empty schema",
            reflection_enabled=False,
            discovery_mode="artifact",
            health_check_enabled=True, health_check_interval=60,
            health_check_timeout=5, health_failure_threshold=3,
            tags=[], visibility="private",
        )
        registered = _run(svc.register_service(test_db, data, user_email="test@example.com"))
        with pytest.raises(Exception):
            _run(svc.import_schema(
                test_db, registered.id, b"",
                "empty.proto", "test@example.com", activate=True,
            ))
