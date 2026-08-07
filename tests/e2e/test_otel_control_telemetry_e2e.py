# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_otel_control_telemetry_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E test — CPEX control-execution telemetry (issue #5785).

Proves, against a REAL gateway request pipeline (real FastAPI app, real
ObservabilityMiddleware, real ToolService, real PluginManager, real
ObservabilityService backed by a real temp SQLite database), that a genuinely
traced HTTP ``tools/call`` request causes ``cpex.control.summary`` and
``cpex.control.result`` DB spans to appear in
``GET /observability/traces/{trace_id}``.

Key insight: ``ControlExecutionRecord`` objects are populated by the CPEX
**framework** (``cpex.framework.manager._make_execution_record``), not by
individual plugins.  The framework builds one record per plugin evaluated,
sourcing all identity/status/duration fields from trusted ``PluginRef`` config
— plugins cannot forge them and do not need to emit them.  This means
``PluginResult.executions`` is already non-empty whenever any plugin runs,
even with the current pii_filter / secrets_detection / rate_limiter plugins
that predate #5785.

Chain under test:
  1. Client sends ``POST /rpc`` (``tools/call``) with a W3C ``traceparent``
     header carrying a trace_id we control.
  2. ``ObservabilityMiddleware`` starts a trace using OUR trace_id and sets
     ``current_trace_id`` context var.
  3. ``ToolService.invoke_tool`` runs ``tool_pre_invoke`` / ``tool_post_invoke``
     hooks via ``plugin_manager.invoke_hook``.  The CPEX framework appends
     one ``ControlExecutionRecord`` per evaluated plugin to ``PluginResult.executions``.
  4. ``ControlTelemetryAccumulator._ctl_acc.add(result, hook=…)`` collects
     those records.
  5. ``record_control_telemetry()`` writes:
       - one ``cpex.control.summary`` DB span with aggregate attributes
       - one ``cpex.control.result`` DB span per record
     all rooted at our trace_id.
  6. ``GET /observability/traces/{trace_id}`` returns those spans — this is
     the concrete verification gate.

Only the outbound HTTP call to the (fictitious) upstream REST tool backend is
mocked.  Everything else runs real gateway code.

Can be run standalone:
    python -m pytest tests/e2e/test_otel_control_telemetry_e2e.py -v
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Third-Party
import yaml

# Enable plugins + observability BEFORE mcpgateway.main is first imported.
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PLUGINS_ENABLED", "true")
os.environ.setdefault("PLUGINS_CONFIG_FILE", str(_REPO_ROOT / "plugins" / "config.yaml"))
os.environ.setdefault("OBSERVABILITY_ENABLED", "true")
# Explicitly enable CPEX control telemetry for E2E tests (default is now false).
os.environ.setdefault("CPEX_CONTROL_TELEMETRY_ENABLED", "true")

# First-Party — clear any settings caches populated before the env vars above were set.
from mcpgateway.config import get_settings as _get_mcpgateway_settings  # noqa: E402

_get_mcpgateway_settings.cache_clear()
try:
    from cpex.framework.settings import settings as _cpex_plugin_settings  # noqa: E402

    _cpex_plugin_settings.cache_clear()
except Exception:  # noqa: BLE001
    pass

# Third-Party
from cpex.framework import PluginError, PluginViolationError, ToolHookType  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
import httpx  # noqa: E402
from pydantic import ValidationError  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# First-Party
from mcpgateway.auth import get_current_user  # noqa: E402
import mcpgateway.db as db_mod  # noqa: E402
from mcpgateway.db import Base  # noqa: E402
import mcpgateway.main as main_mod  # noqa: E402
from mcpgateway.main import (  # noqa: E402
    database_exception_handler,
    get_db,
    plugin_exception_handler,
    plugin_violation_exception_handler,
    request_validation_exception_handler,
    tool_router,
    unhandled_exception_handler,
    utility_router,
    validation_exception_handler,
)
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware  # noqa: E402
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service  # noqa: E402
from mcpgateway.plugins import (  # noqa: E402
    enable_plugins,
    get_plugin_manager,
    init_plugin_manager_factory,
    shutdown_plugin_manager_factory,
)
from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES  # noqa: E402
from mcpgateway.routers.observability import router as observability_router  # noqa: E402
from mcpgateway.services.observability_service import ObservabilityService  # noqa: E402
from mcpgateway.utils.create_jwt_token import get_jwt_token  # noqa: E402
from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth  # noqa: E402

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt  # noqa: E402
from tests.utils.rbac_mocks import MockPermissionService, create_mock_email_user, create_mock_user_context  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin@example.com"
CONTROL_TOOL_NAME = "control_telemetry_probe_tool"
CONTROL_UPSTREAM_URL = "https://internal.e2e-fixture.invalid/control-echo"


def _new_traceparent() -> tuple[str, str]:
    """Build a W3C ``traceparent`` header with a trace_id we control.

    Returns:
        (trace_id, traceparent_header_value)
    """
    trace_id = secrets.token_hex(16)
    parent_span_id = secrets.token_hex(8)
    return trace_id, f"00-{trace_id}-{parent_span_id}-01"


def _auth_headers() -> dict:
    """Mint a real admin JWT and build an Authorization Bearer header.

    Returns:
        Dict with Authorization header.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
    return make_auth_headers(token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_outbound_rest_request(monkeypatch, mock_request: AsyncMock) -> None:
    """Patch ``_build_pinned_rest_http_client`` so the SSRF-pinning path returns a stub.

    TEMPORARY WORKAROUND — reduces CI execution time while a proper solution is designed.

    Ideally these tests would exercise a real upstream backend (a local stub HTTP server)
    rather than mocking the transport layer.  Mocking the outbound HTTP client is
    architecturally wrong for an E2E suite whose purpose is to validate the full gateway
    request pipeline; the correct fix is to stand up a lightweight test server that the
    fixture tool URL points at.  That work is tracked separately.

    Why this patch is needed in the interim: ``ToolService.invoke_tool``'s SSRF
    connection-pinning path calls ``_build_pinned_rest_http_client()`` to build a *fresh*
    ``ResilientHttpClient``, completely bypassing any direct patch to
    ``tool_service._http_client``.  Without patching the factory, the ``_deterministic_dns``
    conftest stub resolves ``*.invalid`` to a real public IP, the pinning branch is entered,
    and the real ``asyncio.wait_for(..., timeout=60)`` fires — burning 60 seconds per test.

    Mirrors the identical helper already present in ``test_otel_plugin_metadata_e2e.py``.
    """

    def build_client():
        return SimpleNamespace(request=mock_request, get=AsyncMock(), aclose=AsyncMock())

    monkeypatch.setattr("mcpgateway.services.tool_service._build_pinned_rest_http_client", build_client)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def control_telemetry_app(monkeypatch, tmp_path):
    """Wire a real temp-DB, dedicated FastAPI app with PIIFilter active.

    Mirrors the ``traced_app`` fixture in ``test_otel_plugin_metadata_e2e.py``
    exactly — real ObservabilityMiddleware, real ToolService, real PluginManager,
    real ObservabilityService, in-memory SQLite DB, only the outbound HTTP call
    mocked.

    PIIFilter is used because:
    - It hooks ``tool_post_invoke`` (so post-invoke records flow through the accumulator)
    - It is always installed in the dev venv (``cpex-pii-filter``)
    - Its ``block_on_detection=false`` shipped default means it never raises
      ``PluginViolationError``, so both pre- and post-invoke complete normally

    The CPEX framework itself creates one ``ControlExecutionRecord`` per plugin
    evaluated — no plugin-side changes are needed.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    monkeypatch.setattr(db_mod, "engine", engine, raising=False)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr("mcpgateway.services.observability_service.SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", TestSessionLocal, raising=False)
    # Patch control_telemetry's SessionLocal so _emit_db_spans writes to the same DB
    monkeypatch.setattr("mcpgateway.plugins.control_telemetry.SessionLocal", TestSessionLocal, raising=False)
    for patch_target in (
        "mcpgateway.middleware.auth_middleware.SessionLocal",
        "mcpgateway.services.security_logger.SessionLocal",
        "mcpgateway.services.audit_trail_service.SessionLocal",
    ):
        try:
            monkeypatch.setattr(patch_target, TestSessionLocal, raising=False)
        except Exception:  # noqa: BLE001
            pass

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Force PIIFilter active (mode: sequential) — shipped default disables it.
    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == "PIIFilter":
            plugin_entry["mode"] = "sequential"
    patched_config_path = tmp_path / "plugins_config_control_telemetry_e2e.yaml"
    patched_config_path.write_text(yaml.safe_dump(real_config, sort_keys=False))

    await shutdown_plugin_manager_factory()
    enable_plugins(True)
    init_plugin_manager_factory(
        yaml_path=str(patched_config_path),
        timeout=30,
        hook_policies=HOOK_PAYLOAD_POLICIES,
        observability=None,
        db_factory=TestSessionLocal,
    )
    plugin_manager = await get_plugin_manager()
    assert plugin_manager is not None, "Plugin manager failed to initialize"
    assert plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE), "PIIFilter not registered for tool_post_invoke"

    observability_service = ObservabilityService()
    test_app = FastAPI(title="control-telemetry-e2e")
    test_app.add_middleware(ObservabilityMiddleware, enabled=True, service=observability_service)
    test_app.include_router(tool_router)
    test_app.include_router(utility_router)
    test_app.include_router(observability_router)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    test_app.add_exception_handler(ValidationError, validation_exception_handler)
    test_app.add_exception_handler(IntegrityError, database_exception_handler)
    test_app.add_exception_handler(PluginViolationError, plugin_violation_exception_handler)
    test_app.add_exception_handler(PluginError, plugin_exception_handler)

    test_app.dependency_overrides[get_db] = override_get_db

    mock_email_user = create_mock_email_user(email=ADMIN_EMAIL, full_name="E2E Admin", is_admin=True, is_active=True)
    admin_user_context = create_mock_user_context(email=ADMIN_EMAIL, full_name="E2E Admin", is_admin=True)

    async def mock_get_current_user_with_permissions():
        return admin_user_context

    async def mock_require_admin_auth():
        return ADMIN_EMAIL

    async def mock_get_jwt_token():
        return make_test_jwt(ADMIN_EMAIL, is_admin=True)

    async def mock_require_auth():
        return ADMIN_EMAIL

    def mock_get_permission_service(*args, **kwargs):
        return MockPermissionService(always_grant=True)

    test_app.dependency_overrides[get_current_user] = lambda: mock_email_user
    test_app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions
    test_app.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    test_app.dependency_overrides[require_auth] = mock_require_auth
    test_app.dependency_overrides[get_jwt_token] = mock_get_jwt_token
    test_app.dependency_overrides[get_permission_service] = mock_get_permission_service

    # TEMPORARY WORKAROUND: mock the outbound HTTP call to avoid 60-second timeouts.
    # See _mock_outbound_rest_request() docstring for rationale and the proper long-term fix.
    upstream_response = httpx.Response(
        200,
        json={"content": [{"type": "text", "text": "hello from upstream"}], "isError": False},
        request=httpx.Request("POST", CONTROL_UPSTREAM_URL),
    )
    _mock_outbound_rest_request(monkeypatch, AsyncMock(return_value=upstream_response))

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://e2e-test") as client:
        yield client

    test_app.dependency_overrides.clear()
    await shutdown_plugin_manager_factory()
    enable_plugins(False)
    engine.dispose()


@pytest.fixture
def otel_memory_exporter(monkeypatch):
    """Install an in-memory OTel-SDK tracer (G2 sink seam).

    Mirrors the identical fixture in ``test_otel_plugin_metadata_e2e.py``.
    Skips cleanly when ``opentelemetry-sdk`` (the 'observability' extra) is absent.
    """
    try:
        from opentelemetry.sdk.trace import TracerProvider  # pylint: disable=import-outside-toplevel
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # pylint: disable=import-outside-toplevel
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        pytest.skip(f"opentelemetry-sdk not installed: {exc}")

    import mcpgateway.observability as obs  # pylint: disable=import-outside-toplevel

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-control-telemetry-e2e")

    monkeypatch.setattr(obs, "_TRACER", tracer)
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)
    return exporter


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _register_control_probe_tool(client: AsyncClient) -> str:
    """Register a REST probe tool via a real POST /tools call.

    Returns:
        The gateway-assigned tool name for use in ``tools/call``.
    """
    payload = {
        "tool": {
            "name": CONTROL_TOOL_NAME,
            "description": "E2E fixture: exercises control-execution telemetry via post_invoke.",
            "integrationType": "REST",
            "url": CONTROL_UPSTREAM_URL,
            "requestType": "POST",
            "visibility": "public",
        },
        "team_id": None,
    }
    resp = await client.post("/tools", json=payload, headers=_auth_headers())
    assert resp.status_code == 200, f"Tool registration failed: {resp.status_code} {resp.text}"
    return resp.json()["name"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestControlTelemetryE2E:
    """Full chain: traceparent -> tools/call -> CPEX records -> cpex.control.* DB spans."""

    @pytest.mark.asyncio
    async def test_control_summary_span_present_in_db(self, control_telemetry_app: AsyncClient):
        """A traced tool call with PIIFilter active produces a cpex.control.summary DB span."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 1,
        }
        rpc_resp = await client.post("/rpc", json=rpc_payload, headers=headers)
        assert rpc_resp.status_code == 200, f"RPC call failed: {rpc_resp.status_code} {rpc_resp.text}"

        # Give the best-effort DB write a moment to land (it is synchronous and inline,
        # but allow one retry for any minor scheduling delay).
        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200, f"Observability fetch failed: {obs_resp.status_code}"

        trace_data = obs_resp.json()
        spans = trace_data.get("spans", [])
        span_names = [s.get("name") for s in spans]

        assert "cpex.control.summary" in span_names, (
            f"Expected cpex.control.summary span in trace {trace_id}. "
            f"Found spans: {span_names}"
        )

    @pytest.mark.asyncio
    async def test_control_result_span_per_plugin_present_in_db(self, control_telemetry_app: AsyncClient):
        """Each evaluated plugin produces a cpex.control.result child span."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 2,
        }
        rpc_resp = await client.post("/rpc", json=rpc_payload, headers=headers)
        assert rpc_resp.status_code == 200

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200

        spans = obs_resp.json().get("spans", [])
        result_spans = [s for s in spans if s.get("name") == "cpex.control.result"]

        assert len(result_spans) >= 1, (
            f"Expected at least one cpex.control.result span in trace {trace_id}. "
            f"Found spans: {[s.get('name') for s in spans]}"
        )

    @pytest.mark.asyncio
    async def test_control_summary_attributes_trusted_fields(self, control_telemetry_app: AsyncClient):
        """cpex.control.summary span carries expected trusted aggregate attributes."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 3,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200

        spans = obs_resp.json().get("spans", [])
        summary = next((s for s in spans if s.get("name") == "cpex.control.summary"), None)
        assert summary is not None, f"cpex.control.summary span not found in trace {trace_id}"

        attrs = summary.get("attributes", {})
        # Aggregate fields must be present
        assert "cpex.control.invocation_count" in attrs, f"Missing invocation_count in {attrs}"
        assert "cpex.control.result.allowed" in attrs, f"Missing result.allowed in {attrs}"
        assert "cpex.control.type" in attrs, f"Missing type in {attrs}"
        assert attrs["cpex.control.type"] == "tool", f"Expected type='tool', got {attrs['cpex.control.type']!r}"
        assert attrs["cpex.control.invocation_count"] >= 1, f"invocation_count should be >= 1, got {attrs['cpex.control.invocation_count']}"

    @pytest.mark.asyncio
    async def test_control_result_span_has_per_control_fields(self, control_telemetry_app: AsyncClient):
        """cpex.control.result spans carry per-control fixed-schema attributes."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 4,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200

        spans = obs_resp.json().get("spans", [])
        result_spans = [s for s in spans if s.get("name") == "cpex.control.result"]
        assert result_spans, "No cpex.control.result spans found"

        for span in result_spans:
            attrs = span.get("attributes", {})
            assert "cpex.control.name" in attrs, f"Missing cpex.control.name in {attrs}"
            assert "cpex.control.status" in attrs, f"Missing cpex.control.status in {attrs}"
            assert "cpex.control.result.allowed" in attrs, f"Missing result.allowed in {attrs}"
            assert "cpex.control.enforcement_point" in attrs, f"Missing enforcement_point in {attrs}"
            assert attrs["cpex.control.enforcement_point"] in {"pre", "post", "pre+post"}, (
                f"Unexpected enforcement_point: {attrs['cpex.control.enforcement_point']!r}"
            )

    @pytest.mark.asyncio
    async def test_control_telemetry_does_not_leak_tool_arguments(self, control_telemetry_app: AsyncClient):
        """Tool arguments must never appear in any cpex.control.* span attribute."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        secret_marker = "SENTINEL_SHOULD_NOT_APPEAR_IN_TELEMETRY"
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {"sensitive_input": secret_marker}},
            "id": 5,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200

        raw_text = obs_resp.text
        assert secret_marker not in raw_text, (
            f"Tool argument sentinel {secret_marker!r} must not appear anywhere in observability output"
        )

    @pytest.mark.asyncio
    async def test_control_telemetry_otel_sdk_spans(self, control_telemetry_app: AsyncClient, otel_memory_exporter):
        """G2 sink: cpex.control.summary and cpex.control.result appear in the OTel in-memory exporter."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 6,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        finished = otel_memory_exporter.get_finished_spans()
        otel_span_names = [s.name for s in finished]

        assert "cpex.control.summary" in otel_span_names, (
            f"cpex.control.summary not in OTel spans. Found: {otel_span_names}"
        )
        assert "cpex.control.result" in otel_span_names, (
            f"cpex.control.result not in OTel spans. Found: {otel_span_names}"
        )

    @pytest.mark.asyncio
    async def test_db_and_otel_span_names_match(self, control_telemetry_app: AsyncClient, otel_memory_exporter):
        """DB and OTel sinks emit the same canonical span names — parity check."""
        client = control_telemetry_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
            "id": 7,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.05)

        # DB side
        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        db_span_names = {s.get("name") for s in obs_resp.json().get("spans", [])}

        # OTel side
        otel_span_names = {s.name for s in otel_memory_exporter.get_finished_spans()}

        for canonical in ("cpex.control.summary", "cpex.control.result"):
            assert canonical in db_span_names, f"{canonical!r} missing from DB spans: {db_span_names}"
            assert canonical in otel_span_names, f"{canonical!r} missing from OTel spans: {otel_span_names}"


# ---------------------------------------------------------------------------
# Denial-path fixture and tests (pre-invoke and post-invoke denial)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def denying_plugin_app(monkeypatch, tmp_path):
    """Wire a real gateway app with a PIIFilter configured to BLOCK on detection.

    PIIFilter with ``block_on_detection=true`` and ``enforcement_mode=pre_invoke``
    will raise ``PluginViolationError`` when PII is detected in tool arguments,
    exercising the pre-invoke denial path.  For post-invoke denial we use
    ``enforcement_mode=post_invoke`` instead.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    monkeypatch.setattr(db_mod, "engine", engine, raising=False)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr("mcpgateway.services.observability_service.SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", TestSessionLocal, raising=False)
    monkeypatch.setattr("mcpgateway.plugins.control_telemetry.SessionLocal", TestSessionLocal, raising=False)
    for patch_target in (
        "mcpgateway.middleware.auth_middleware.SessionLocal",
        "mcpgateway.services.security_logger.SessionLocal",
        "mcpgateway.services.audit_trail_service.SessionLocal",
    ):
        try:
            monkeypatch.setattr(patch_target, TestSessionLocal, raising=False)
        except Exception:  # noqa: BLE001
            pass

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Configure PIIFilter to block on detection in pre_invoke mode.
    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == "PIIFilter":
            plugin_entry["mode"] = "sequential"
            plugin_cfg = plugin_entry.setdefault("config", {})
            plugin_cfg["block_on_detection"] = True
            plugin_cfg["enforcement_mode"] = "pre_invoke"
    patched_config_path = tmp_path / "plugins_config_denying_e2e.yaml"
    patched_config_path.write_text(yaml.safe_dump(real_config, sort_keys=False))

    await shutdown_plugin_manager_factory()
    enable_plugins(True)
    init_plugin_manager_factory(
        yaml_path=str(patched_config_path),
        timeout=30,
        hook_policies=HOOK_PAYLOAD_POLICIES,
        observability=None,
        db_factory=TestSessionLocal,
    )
    plugin_manager = await get_plugin_manager()
    assert plugin_manager is not None, "Plugin manager failed to initialize"

    observability_service = ObservabilityService()
    test_app = FastAPI(title="denying-plugin-e2e")
    test_app.add_middleware(ObservabilityMiddleware, enabled=True, service=observability_service)
    test_app.include_router(tool_router)
    test_app.include_router(utility_router)
    test_app.include_router(observability_router)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    test_app.add_exception_handler(ValidationError, validation_exception_handler)
    test_app.add_exception_handler(IntegrityError, database_exception_handler)
    test_app.add_exception_handler(PluginViolationError, plugin_violation_exception_handler)
    test_app.add_exception_handler(PluginError, plugin_exception_handler)

    test_app.dependency_overrides[get_db] = override_get_db

    mock_email_user = create_mock_email_user(email=ADMIN_EMAIL, full_name="E2E Admin", is_admin=True, is_active=True)
    admin_user_context = create_mock_user_context(email=ADMIN_EMAIL, full_name="E2E Admin", is_admin=True)

    async def mock_get_current_user_with_permissions():
        return admin_user_context

    async def mock_require_admin_auth():
        return ADMIN_EMAIL

    async def mock_get_jwt_token():
        return make_test_jwt(ADMIN_EMAIL, is_admin=True)

    async def mock_require_auth():
        return ADMIN_EMAIL

    def mock_get_permission_service(*args, **kwargs):
        return MockPermissionService(always_grant=True)

    test_app.dependency_overrides[get_current_user] = lambda: mock_email_user
    test_app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions
    test_app.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    test_app.dependency_overrides[require_auth] = mock_require_auth
    test_app.dependency_overrides[get_jwt_token] = mock_get_jwt_token
    test_app.dependency_overrides[get_permission_service] = mock_get_permission_service

    # TEMPORARY WORKAROUND: mock the outbound HTTP call to avoid 60-second timeouts.
    # See _mock_outbound_rest_request() docstring for rationale and the proper long-term fix.
    upstream_response = httpx.Response(
        200,
        json={"content": [{"type": "text", "text": "hello"}], "isError": False},
        request=httpx.Request("POST", CONTROL_UPSTREAM_URL),
    )
    _mock_outbound_rest_request(monkeypatch, AsyncMock(return_value=upstream_response))

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://e2e-test") as client:
        yield client

    test_app.dependency_overrides.clear()
    await shutdown_plugin_manager_factory()
    enable_plugins(False)
    engine.dispose()


class TestDenialPathTelemetry:
    """Verify cpex.control.summary spans are emitted correctly on denial paths."""

    @pytest.mark.asyncio
    async def test_pre_invoke_denial_summary_span_allowed_false(self, denying_plugin_app: AsyncClient):
        """Pre-invoke denial: summary span has result.allowed=false and enforcement_point=pre.

        When PIIFilter with block_on_detection=true detects PII in tool arguments on
        the pre_invoke hook, it raises PluginViolationError.  ContextForge catches it,
        calls mark_denied(hook="pre"), and still emits partial telemetry.  The summary
        span must reflect the denial outcome even though the tool never executed.
        """
        import asyncio  # noqa: PLC0415

        client = denying_plugin_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        # Send an argument value that PIIFilter will detect as PII (email address).
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {"input": "user@example.com"}},
            "id": 8,
        }
        resp = await client.post("/rpc", json=rpc_payload, headers=headers)
        # A pre-invoke denial must produce a 4xx error response, never a 5xx.
        # 200 with isError is acceptable (JSON-RPC error envelope); 500 indicates
        # an unhandled exception rather than a controlled denial.
        assert resp.status_code in {200, 400, 403, 422}, (
            f"Expected a denial error response (200/400/403/422), got {resp.status_code}"
        )

        await asyncio.sleep(0.1)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert obs_resp.status_code == 200

        spans = obs_resp.json().get("spans", [])
        summary_spans = [s for s in spans if s.get("name") == "cpex.control.summary"]

        # A live pre-invoke denial MUST produce a summary span.  Absence is a regression,
        # not an environment variation — do not skip.
        assert summary_spans, (
            "Expected a cpex.control.summary span for the pre-invoke denial, but none was emitted. "
            "This indicates denial telemetry is broken."
        )

        summary = summary_spans[0]
        attrs = summary.get("attributes") or {}

        assert attrs.get("cpex.control.result.allowed") is False, (
            f"Expected result.allowed=false on denial path, got: {attrs.get('cpex.control.result.allowed')!r}"
        )
        assert attrs.get("cpex.control.enforcement_point") == "pre", (
            f"Expected enforcement_point=pre for a pre-invoke denial, got: {attrs.get('cpex.control.enforcement_point')!r}"
        )

    @pytest.mark.asyncio
    async def test_pre_invoke_denial_tool_never_executed(self, denying_plugin_app: AsyncClient):
        """Pre-invoke denial: tool execution success is distinguishable from control denial.

        The summary span's result.allowed=false must not be confused with a tool-side
        error.  The cpex.control.type=tool attribute should be present to identify
        the invocation context, but there must be no upstream tool response mixed into
        the control telemetry attributes.
        """
        import asyncio  # noqa: PLC0415

        client = denying_plugin_app
        tool_name = await _register_control_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {"input": "user@example.com"}},
            "id": 9,
        }
        await client.post("/rpc", json=rpc_payload, headers=headers)
        await asyncio.sleep(0.1)

        obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        spans = obs_resp.json().get("spans", [])
        summary_spans = [s for s in spans if s.get("name") == "cpex.control.summary"]

        assert summary_spans, (
            "Expected a cpex.control.summary span for the pre-invoke denial, but none was emitted."
        )

        summary = summary_spans[0]
        attrs = summary.get("attributes") or {}

        # Control telemetry must not contain tool argument content.
        import json  # noqa: PLC0415

        raw = json.dumps(attrs)
        assert "user@example.com" not in raw, "Tool argument value must not appear in control telemetry attributes"
        # cpex.control.type should identify this as a tool-context span.
        assert attrs.get("cpex.control.type") == "tool"
