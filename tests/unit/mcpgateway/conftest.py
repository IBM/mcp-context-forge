# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for mcpgateway unit tests."""

# Future
from __future__ import annotations

# Standard
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from sqlalchemy import select

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.utils.create_slug import slugify

try:
    import gateway_rs.a2a_service as _gateway_rs_a2a  # noqa: F401

    RUST_A2A_AVAILABLE = True
except ImportError:
    RUST_A2A_AVAILABLE = False

    async def _stub_try_submit_invoke(*_args, **_kwargs):
        raise RuntimeError("A2A invoke queue not initialized")

    def _stub_build_a2a_metrics_batch(entries, end_time_ts):
        metrics = []
        success_agent_ids = []
        for agent_id, interaction_type, status_code, body, duration_secs in entries:
            is_success = int(status_code) == 200
            error_message = None if is_success else (body or f"HTTP {status_code}")
            metrics.append((agent_id, end_time_ts, float(duration_secs), is_success, interaction_type, error_message))
            if is_success:
                success_agent_ids.append(agent_id)
        return metrics, success_agent_ids

    gateway_rs_module = types.ModuleType("gateway_rs")
    gateway_rs_a2a_module = types.ModuleType("gateway_rs.a2a_service")
    gateway_rs_a2a_module.try_submit_invoke = _stub_try_submit_invoke
    gateway_rs_a2a_module.build_a2a_metrics_batch = _stub_build_a2a_metrics_batch
    gateway_rs_a2a_module.init_invoker = lambda *_args, **_kwargs: None
    gateway_rs_a2a_module.init_queue = lambda *_args, **_kwargs: None
    gateway_rs_a2a_module.reset_metrics = lambda *_args, **_kwargs: None

    async def _stub_shutdown_queue(*_args, **_kwargs):
        return None

    gateway_rs_a2a_module.shutdown_queue = _stub_shutdown_queue
    gateway_rs_module.a2a_service = gateway_rs_a2a_module
    sys.modules.setdefault("gateway_rs", gateway_rs_module)
    sys.modules.setdefault("gateway_rs.a2a_service", gateway_rs_a2a_module)

# First-Party
# Save original RBAC decorator functions at conftest import time.
# Conftest files load before test modules, so these should be the real functions.
import mcpgateway.middleware.rbac as _rbac_mod
from mcpgateway.plugins.framework.settings import settings

_ORIG_REQUIRE_PERMISSION = _rbac_mod.require_permission
_ORIG_REQUIRE_ADMIN_PERMISSION = _rbac_mod.require_admin_permission
_ORIG_REQUIRE_ANY_PERMISSION = _rbac_mod.require_any_permission


class MockPermissionService:
    """Mock PermissionService that allows all permission checks by default."""

    # Class-level mock that can be patched by individual tests
    check_permission = AsyncMock(return_value=True)
    check_admin_permission = AsyncMock(return_value=True)

    def __init__(self, db=None):
        self.db = db


@pytest.fixture(autouse=True)
def mock_permission_service(monkeypatch):
    """Auto-mock PermissionService and restore real RBAC decorators.

    This fixture is auto-used for all tests in this directory.

    It also restores real RBAC decorator functions in case other tests
    patched them (e.g., via module-level monkeypatching) in the same worker
    process when running under xdist.

    Tests that need to verify permission denial behavior should:
    1. Set MockPermissionService.check_permission.return_value = False
    2. Or configure side_effect for more complex scenarios
    """
    # Restore real RBAC decorators (may have been replaced by noop in e2e test modules)
    monkeypatch.setattr(_rbac_mod, "require_permission", _ORIG_REQUIRE_PERMISSION)
    monkeypatch.setattr(_rbac_mod, "require_admin_permission", _ORIG_REQUIRE_ADMIN_PERMISSION)
    monkeypatch.setattr(_rbac_mod, "require_any_permission", _ORIG_REQUIRE_ANY_PERMISSION)

    # Reset the mock before each test to ensure clean state
    MockPermissionService.check_permission = AsyncMock(return_value=True)
    MockPermissionService.check_admin_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    return MockPermissionService


@pytest.fixture(autouse=True)
def clear_plugins_settings_cache():
    """Clear the settings LRU cache so env changes take effect per test."""
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture(scope="session")
def rust_available():
    """Whether the real gateway_rs A2A extension is importable in this test run."""
    return RUST_A2A_AVAILABLE


# ---------------------------------------------------------------------------
# A2A real-stack fixtures: real HTTP stub server + DB agent (no Rust mocking)
# ---------------------------------------------------------------------------

REAL_A2A_AGENT_NAME = "real-a2a-test-agent"
REAL_A2A_STUB_DEFAULT_BODY = {"ok": True, "response": "Test response", "status": "success"}


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a separate thread."""

    daemon_threads = True


@pytest.fixture
def a2a_stub_server():
    """Start a real HTTP server that acts as the A2A agent endpoint (Rust invoker calls it).

    POST returns 200 and configurable JSON. Yields (base_url, stop_fn).
    Use this so tests do not mock Rust or the network; only the \"agent\" is faked.
    """
    body = REAL_A2A_STUB_DEFAULT_BODY

    class StubHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length:
                self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, format, *args):
            pass

    server = _ThreadedHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}/"

    yield base_url

    server.shutdown()


@pytest.fixture
def real_a2a_agent_in_db(app_with_temp_db, a2a_stub_server):
    """Ensure the A2A queue is initialized and the DB has an agent pointing at the stub server.

    Yields the agent name. Tests can POST /a2a/{agent_name}/invoke or /a2a/invoke with that
    agent; the real Rust queue and invoker will call the stub server. No Rust mocking.
    """
    from mcpgateway.db import SessionLocal

    if RUST_A2A_AVAILABLE:
        # Ensure Rust queue is ready (idempotent)
        from gateway_rs import a2a_service as rust_a2a

        rust_a2a.init_invoker(30, 3)
        try:
            sig = __import__("inspect").signature(rust_a2a.init_queue)
            if len(sig.parameters) >= 3:
                rust_a2a.init_queue(2, None, None)
            elif len(sig.parameters) >= 2:
                rust_a2a.init_queue(2, None)
            else:
                rust_a2a.init_queue(2)
        except Exception:
            rust_a2a.init_queue(2)

    db = SessionLocal()
    try:
        existing = db.execute(
            select(DbA2AAgent).where(DbA2AAgent.name == REAL_A2A_AGENT_NAME)
        ).scalars().first()
        slug = slugify(REAL_A2A_AGENT_NAME)
        if existing:
            existing.endpoint_url = a2a_stub_server
            existing.enabled = True
            db.commit()
        else:
            agent = DbA2AAgent(
                name=REAL_A2A_AGENT_NAME,
                slug=slug,
                endpoint_url=a2a_stub_server,
                agent_type="generic",
                protocol_version="1.0",
                visibility="public",
                enabled=True,
            )
            db.add(agent)
            db.commit()
        yield REAL_A2A_AGENT_NAME
    finally:
        db.close()


@pytest.fixture
def real_a2a_invoke_context(app_with_temp_db, a2a_stub_server):
    """Real DB session + agent name for testing invoke_agent with real Rust (no mocks).

    Yields (db_session, agent_name). Use for A2AAgentService.invoke_agent() tests that
    should hit the real Rust queue and stub HTTP agent.
    """
    from mcpgateway.db import SessionLocal

    if RUST_A2A_AVAILABLE:
        from gateway_rs import a2a_service as rust_a2a

        rust_a2a.init_invoker(30, 3)
        try:
            sig = __import__("inspect").signature(rust_a2a.init_queue)
            if len(sig.parameters) >= 3:
                rust_a2a.init_queue(2, None, None)
            elif len(sig.parameters) >= 2:
                rust_a2a.init_queue(2, None)
            else:
                rust_a2a.init_queue(2)
        except Exception:
            rust_a2a.init_queue(2)

    db = SessionLocal()
    try:
        existing = db.execute(
            select(DbA2AAgent).where(DbA2AAgent.name == REAL_A2A_AGENT_NAME)
        ).scalars().first()
        slug = slugify(REAL_A2A_AGENT_NAME)
        if existing:
            existing.endpoint_url = a2a_stub_server
            existing.enabled = True
            db.commit()
        else:
            agent = DbA2AAgent(
                name=REAL_A2A_AGENT_NAME,
                slug=slug,
                endpoint_url=a2a_stub_server,
                agent_type="generic",
                protocol_version="1.0",
                visibility="public",
                enabled=True,
            )
            db.add(agent)
            db.commit()
        yield db, REAL_A2A_AGENT_NAME
    finally:
        db.close()
