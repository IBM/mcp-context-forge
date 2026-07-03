# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_otel_plugin_metadata_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

E2E test — Task C1 (Refs #5458).

Proves, against a REAL gateway request pipeline (the actual ``/tools``,
``/rpc`` and ``/observability`` routers from ``mcpgateway.main`` /
``mcpgateway.routers.observability``, the real ``ObservabilityMiddleware``,
real ``ToolService``, real ``PluginManager``, real ``ObservabilityService``
backed by a real temp SQLite database), that a genuinely traced HTTP tool-invoke
request causes the ``pii_filter`` CPEX plugin's metrics to reach
``GET /observability/traces/{trace_id}`` -- and that the raw PII value the
plugin detected never appears anywhere in that response (S1).

This module covers BOTH of ``record_plugin_metrics()``'s independently-flagged export sinks
(``mcpgateway/plugins/utils.py``) with the identical traced call:

  * ``test_traced_tool_call_surfaces_pii_filter_metrics_without_leaking_pii`` -- the G1 DB
    sink, asserted via ``GET /observability/traces/{trace_id}``.
  * ``test_traced_tool_call_exports_pii_filter_metrics_to_otel_sdk`` -- the G2 OTel-SDK export
    sink, asserted via an in-memory ``TracerProvider``/``InMemorySpanExporter`` patched onto
    ``mcpgateway.observability._TRACER`` (see the ``otel_memory_exporter`` fixture). Skips
    cleanly when the optional ``observability`` extra (``opentelemetry-sdk``) is not installed.

These real routers are hosted on a dedicated, per-test ``FastAPI()`` instance
(see the ``traced_app`` fixture) rather than on the process-wide
``mcpgateway.main.app`` singleton that other ``tests/e2e/`` modules send real
requests through: Starlette freezes an app's middleware stack the first time
any request is dispatched through it, so mutating the shared ``app`` via
``add_middleware``/``include_router`` from this fixture would be order-dependent
(and would error) if another e2e test file already sent a request through
``mcpgateway.main.app`` earlier in the same pytest process/worker. Building a
fresh app and wiring the same real router objects onto it sidesteps that
entirely while still exercising the real endpoint/dependency/plugin code.

Chain under test (Phases A + B, this branch):
  1. Client sends ``POST /rpc`` (``tools/call``) with a W3C ``traceparent``
     header carrying a trace_id we chose ourselves.
  2. ``ObservabilityMiddleware`` (Task B0) parses ``traceparent``, starts a
     trace using OUR trace_id, and bridges it into
     ``mcpgateway.services.observability_service.current_trace_id`` /
     ``cpex.framework.observability.current_trace_id`` context vars.
  3. ``ToolService.invoke_tool`` (Task B1) builds
     ``Extensions(request=RequestExtension(trace_id=..., span_id=...))`` via
     ``build_request_extensions()`` and passes it into every
     ``plugin_manager.invoke_hook(..., extensions=...)`` call (tool_pre_invoke
     and tool_post_invoke).
  4. The real ``pii_filter`` plugin (installed from ../cpex-plugins, Rust-backed)
     reads ``extensions.request.trace_id``; since a trace is active, it emits
     ``result.metadata["pii_filter"] = {"total_detections": N, "total_masked": N,
     "detection_types": [...], "stage": "..."}`` -- counts/type-names only,
     never the matched PII value -- and masks the PII in the tool result it
     returns to the gateway.
  5. ``record_plugin_metrics()`` (Task B2) validates that metadata and persists
     it as attributes on a dedicated ``plugin.metrics.pii_filter`` span rooted
     at our trace_id.
  6. ``GET /observability/traces/{trace_id}`` returns that span with the
     validated attributes -- this is the concrete "issue verified locally" gate.

Only the outbound HTTP call to the (fictitious) upstream REST tool backend is
mocked (``tool_service._http_client.request``) -- there is no real 3rd-party
server for a hermetic test to call. Everything else -- auth, tool
registration, RPC dispatch, plugin execution, trace propagation, observability
persistence and the query endpoint -- runs the real gateway code.

Auth note: this file uses the same dependency-override auth pattern as
``tests/e2e/test_admin_apis.py`` and ``tests/e2e/test_main_apis.py`` (a real
JWT is minted via ``tests/helpers/auth.make_test_jwt`` and sent as a real
Authorization header for realism/documentation, and
``get_current_user_with_permissions`` / ``get_permission_service`` are
overridden with admin-bypass mocks, matching established e2e convention in
this repository) -- RBAC internals are not the subject of this test; the
trace -> plugin -> observability pipeline is.

Can be run standalone or as part of the full ``tests/e2e/`` suite (including
after other e2e modules that already sent requests through
``mcpgateway.main.app`` in the same process) since ``traced_app`` no longer
mutates that shared singleton:

    python -m pytest tests/e2e/test_otel_plugin_metadata_e2e.py -v

The module-level environment setup below (which enables the plugin subsystem
and observability feature flags before the first import of ``mcpgateway.main``)
is kept as a defensive measure -- it ensures ``PLUGINS_ENABLED``/
``OBSERVABILITY_ENABLED`` are true for any code path that still consults
``mcpgateway.config.settings`` -- even though the dedicated app built below no
longer depends on ``mcpgateway.main``'s own top-level
``if settings.observability_enabled: app.add_middleware(...)`` wiring.
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path
import secrets
from unittest.mock import AsyncMock

# Make sure the plugin subsystem and observability feature flags are on
# BEFORE mcpgateway.main is first imported below: both
# ``if settings.plugins.enabled: enable_plugins(True)`` and
# ``if settings.observability_enabled: app.add_middleware(ObservabilityMiddleware, ...)``
# /``app.include_router(observability_router)`` are top-level statements in
# mcpgateway/main.py, evaluated once at import time. The fixtures below also
# wire the plugin manager factory and the observability router/middleware
# directly (belt-and-suspenders) so this test is robust even if
# mcpgateway.main happened to be imported earlier in the same session.
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PLUGINS_ENABLED", "true")
os.environ.setdefault("PLUGINS_CONFIG_FILE", str(_REPO_ROOT / "plugins" / "config.yaml"))
os.environ.setdefault("OBSERVABILITY_ENABLED", "true")

# First-Party -- clear any settings caches populated before the env vars above were set.
from mcpgateway.config import get_settings as _get_mcpgateway_settings  # noqa: E402

_get_mcpgateway_settings.cache_clear()
try:
    # Third-Party
    from cpex.framework.settings import settings as _cpex_plugin_settings  # noqa: E402

    _cpex_plugin_settings.cache_clear()
except Exception:  # noqa: BLE001 - best-effort cache clear
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
from mcpgateway.services.tool_service import tool_service  # noqa: E402
from mcpgateway.utils.create_jwt_token import get_jwt_token  # noqa: E402
from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth  # noqa: E402

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt  # noqa: E402
from tests.utils.rbac_mocks import create_mock_email_user, create_mock_user_context, MockPermissionService  # noqa: E402

# ---------------------------------------------------------------------------
# Test fixtures / constants
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin@example.com"

# Synthetic PII -- not a real person's data. Realistic enough to trip the
# pii_filter plugin's email detector; the whole point of this test is to
# prove this value (or any raw PII) never reaches /observability.
RAW_PII_EMAIL = "e2e.synthetic.subject@pii-e2e-fixture.invalid"

TOOL_NAME = "pii_probe_echo_tool"
UPSTREAM_TOOL_URL = "https://internal.e2e-fixture.invalid/echo"


def _new_traceparent() -> tuple[str, str]:
    """Build a W3C ``traceparent`` header value with a trace_id we control.

    Returns:
        (trace_id, traceparent_header_value)
    """
    trace_id = secrets.token_hex(16)  # 32 lowercase hex chars
    parent_span_id = secrets.token_hex(8)  # 16 lowercase hex chars
    return trace_id, f"00-{trace_id}-{parent_span_id}-01"


@pytest_asyncio.fixture
async def traced_app(monkeypatch):
    """Wire a real temp-DB, dedicated FastAPI app with plugins + observability live.

    Deliberately does NOT reuse the process-wide ``mcpgateway.main.app``
    singleton -- other ``tests/e2e/`` modules (e.g. ``test_admin_apis.py``,
    ``test_main_apis.py``) send real requests through that same shared ``app``
    via ``TestClient``/``AsyncClient``, and Starlette irreversibly freezes an
    app's middleware stack the first time any request is dispatched through it.
    Once frozen, any later ``app.add_middleware(...)`` call raises
    ``RuntimeError: Cannot add middleware after an application has started`` --
    which would make this fixture order-dependent within a pytest-xdist worker.

    Instead, this fixture builds a brand-new ``FastAPI()`` instance per test and
    wires the REAL router objects from ``mcpgateway.main`` /
    ``mcpgateway.routers.observability`` onto it (the actual ``/tools``,
    ``/rpc`` and ``/observability/...`` endpoints, real dependency callables,
    real exception handlers) before any request is ever sent through it, so
    ``add_middleware``/``include_router`` never race a frozen stack. The
    ``ToolService``/``PluginManager``/``ObservabilityService`` singletons this
    exercises are still the real, process-wide ones -- only the FastAPI/ASGI
    app object hosting the routes is dedicated to this test.

    Mirrors ``tests/e2e/test_main_apis.py``'s ``temp_db`` fixture (real temp
    SQLite DB, dependency-override auth) plus
    ``tests/integration/test_cross_hook_context_sharing.py``'s pattern of
    dynamically wiring a real plugin manager, plus
    ``tests/integration/plugins/test_plugin_metrics_consumer_integration.py``'s
    use of a real ``ObservabilityService`` against a real DB.
    """
    # --- Real temp SQLite database, shared by app + plugin factory + observability ---
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
    # mcpgateway/routers/observability.py defines its own local get_db() bound to a
    # module-level `SessionLocal` name captured at import time -- patch it directly too,
    # otherwise GET /observability/traces/{trace_id} reads from the wrong (schema-less) DB.
    monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", TestSessionLocal, raising=False)
    try:
        monkeypatch.setattr("mcpgateway.middleware.auth_middleware.SessionLocal", TestSessionLocal, raising=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        monkeypatch.setattr("mcpgateway.services.security_logger.SessionLocal", TestSessionLocal, raising=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        monkeypatch.setattr("mcpgateway.services.audit_trail_service.SessionLocal", TestSessionLocal, raising=False)
    except Exception:  # noqa: BLE001
        pass

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # --- Real plugin manager factory, pointed at plugins/config.yaml (with our pii_filter entry) ---
    await shutdown_plugin_manager_factory()
    enable_plugins(True)
    init_plugin_manager_factory(
        yaml_path=str(_REPO_ROOT / "plugins" / "config.yaml"),
        timeout=30,
        hook_policies=HOOK_PAYLOAD_POLICIES,
        observability=None,
        db_factory=TestSessionLocal,
    )
    plugin_manager = await get_plugin_manager()
    assert plugin_manager is not None, "Plugin manager factory failed to initialize -- check plugins/config.yaml and that cpex-pii-filter is installed"
    assert plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE), "pii_filter plugin not registered for tool_post_invoke -- check plugins/config.yaml"

    # --- Dedicated FastAPI app instance (NOT mcpgateway.main.app) ---
    # Built fresh, once per test, before any request is ever dispatched through it, so
    # add_middleware()/include_router() below can never race a frozen middleware stack.
    # The routers are the REAL router objects imported from mcpgateway.main /
    # mcpgateway.routers.observability -- same endpoint functions, same Depends(...)
    # callables, same exception handlers as the production app; only the FastAPI/ASGI
    # instance hosting them is dedicated to this test.
    observability_service = ObservabilityService()
    test_app = FastAPI(title="otel-plugin-metadata-e2e")
    test_app.add_middleware(ObservabilityMiddleware, enabled=True, service=observability_service)
    test_app.include_router(tool_router)  # real POST /tools (tool registration)
    test_app.include_router(utility_router)  # real POST /rpc (tools/call dispatch)
    test_app.include_router(observability_router)  # real GET /observability/traces/{trace_id}
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    test_app.add_exception_handler(ValidationError, validation_exception_handler)
    test_app.add_exception_handler(IntegrityError, database_exception_handler)
    test_app.add_exception_handler(PluginViolationError, plugin_violation_exception_handler)
    test_app.add_exception_handler(PluginError, plugin_exception_handler)

    test_app.dependency_overrides[get_db] = override_get_db

    # --- Auth: dependency-override pattern (mirrors test_admin_apis.py / test_main_apis.py) ---
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

    # --- Mock only the outbound network call to the (fictitious) upstream tool backend ---
    upstream_response = httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": f"Customer contact on file: {RAW_PII_EMAIL}"}],
            "isError": False,
        },
        request=httpx.Request("POST", UPSTREAM_TOOL_URL),
    )
    mock_request = AsyncMock(return_value=upstream_response)
    monkeypatch.setattr(tool_service._http_client, "request", mock_request)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://e2e-test") as client:
        yield client

    test_app.dependency_overrides.clear()
    await shutdown_plugin_manager_factory()
    enable_plugins(False)
    engine.dispose()


def _auth_headers() -> dict:
    """Mint a real admin JWT via tests/helpers/auth.make_test_jwt and build a Bearer header."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
    return make_auth_headers(token)


async def _register_probe_tool(client: AsyncClient) -> str:
    """Register a REST tool whose (mocked) upstream response echoes PII, via a real POST /tools call.

    Returns:
        The gateway-assigned (slugified) tool ``name`` to use for ``tools/call`` lookups --
        registration accepts ``pii_probe_echo_tool`` but the RPC dispatcher resolves tools by
        their normalized ``name`` (dashes), not the original ``customName``.
    """
    tool_payload = {
        "tool": {
            "name": TOOL_NAME,
            "description": "E2E fixture tool: echoes upstream content so tool_post_invoke has PII to detect.",
            "integrationType": "REST",
            "url": UPSTREAM_TOOL_URL,
            "requestType": "POST",
            "visibility": "public",
        },
        "team_id": None,
    }
    response = await client.post("/tools", json=tool_payload, headers=_auth_headers())
    assert response.status_code == 200, f"Tool registration failed: {response.status_code} {response.text}"
    return response.json()["name"]


@pytest.fixture
def otel_memory_exporter(monkeypatch):
    """Install an in-memory OTel-SDK tracer as the process tracer (G2 test seam).

    ``create_span()`` and ``otel_tracing_enabled()`` in ``mcpgateway.observability`` both read
    the same module-level ``_TRACER`` global (``observability.py:712,719,1281``): the former
    no-ops (returns ``nullcontext()``) when it is ``None``, and the latter reports tracing as
    "enabled" whenever it is not ``None``. Patching that one global to a real tracer -- backed
    by a ``TracerProvider`` with an ``InMemorySpanExporter`` span processor -- is therefore a
    legitimate, minimal seam for exercising the G2 OTel-SDK export sink in
    ``mcpgateway/plugins/utils.py::record_plugin_metrics()`` end-to-end, with no config/env
    vars required.

    Skips the dependent test cleanly (not the whole module -- the DB-sink test above has no
    OTel dependency and must keep running) when the optional ``observability`` extra
    (``opentelemetry-sdk``) is not installed: ``pip install '.[observability]'`` /
    ``uv pip install '.[observability]'``.
    """
    pytest.importorskip("opentelemetry.sdk.trace", reason="opentelemetry-sdk (the 'observability' extra) is not installed")

    # Third-Party -- deferred so the module itself always imports even without the extra;
    # only tests that request this fixture pay the (skippable) cost.
    from opentelemetry.sdk.trace import TracerProvider  # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # pylint: disable=import-outside-toplevel

    # First-Party
    import mcpgateway.observability as obs  # pylint: disable=import-outside-toplevel

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-otel-plugin-metadata-e2e")

    monkeypatch.setattr(obs, "_TRACER", tracer)
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)
    return exporter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOtelPluginMetadataE2E:
    """C1: traced HTTP tool call -> pii_filter metrics visible in /observability, no PII leak."""

    @pytest.mark.asyncio
    async def test_traced_tool_call_surfaces_pii_filter_metrics_without_leaking_pii(self, traced_app: AsyncClient):
        """Full chain: traceparent -> tools/call -> pii_filter -> /observability/traces/{trace_id}."""
        client = traced_app
        registered_tool_name = await _register_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-c1-1",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {"note": "please check the account on file"}},
        }
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"

        # S1 (part 1): the raw PII value must not leak back to the RPC caller either --
        # the plugin's masking (block_on_detection=false, so it redacts rather than blocks)
        # should have replaced it before the result was returned.
        assert RAW_PII_EMAIL not in rpc_response.text, "Raw PII leaked into the tools/call RPC response body"

        # Now query the real observability endpoint for the trace we chose via traceparent.
        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        pii_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.pii_filter"]
        assert pii_metric_spans, f"No 'plugin.metrics.pii_filter' span found; span names present: {[s.get('name') for s in spans]}"

        post_invoke_spans = [s for s in pii_metric_spans if s.get("attributes", {}).get("stage") == "tool_post_invoke"]
        assert post_invoke_spans, f"No tool_post_invoke pii_filter metrics span found; pii_filter spans: {pii_metric_spans}"

        attrs = post_invoke_spans[0]["attributes"]
        assert attrs.get("total_detections", 0) >= 1, f"Expected at least 1 PII detection, got attributes: {attrs}"
        assert attrs.get("total_masked", 0) >= 1, f"Expected at least 1 masked value, got attributes: {attrs}"
        assert "email" in str(attrs.get("detection_types", "")), f"Expected 'email' in detection_types, got: {attrs.get('detection_types')}"
        assert post_invoke_spans[0].get("resource_type") == "plugin"
        assert post_invoke_spans[0].get("resource_name") == "pii_filter"

        # S1 (part 2, the security-critical assertion): the RAW matched PII value must never
        # appear anywhere in the observability response -- not in span attributes, not in
        # event messages, not anywhere in the serialized body. Only counts/type-names allowed.
        full_response_text = trace_response.text
        assert RAW_PII_EMAIL not in full_response_text, "SECURITY: raw PII value leaked into /observability/traces/{trace_id} response"

        # Belt-and-suspenders: no span attribute value anywhere in the trace contains the raw PII.
        for span in spans:
            for key, value in (span.get("attributes") or {}).items():
                assert RAW_PII_EMAIL not in str(value), f"SECURITY: raw PII found in span '{span.get('name')}' attribute '{key}'"

    @pytest.mark.asyncio
    async def test_traced_tool_call_exports_pii_filter_metrics_to_otel_sdk(self, traced_app: AsyncClient, otel_memory_exporter):
        """Same chain as the DB-sink test above, but asserts on the G2 OTel-SDK export sink.

        Fires the identical traced ``tools/call`` (same PII payload, same tool, same
        traceparent-driven trace) through the same real gateway pipeline; the only thing
        that differs from
        ``test_traced_tool_call_surfaces_pii_filter_metrics_without_leaking_pii`` is where the
        assertion looks for the ``pii_filter`` metrics -- an in-memory OTel span captured by
        ``otel_memory_exporter`` instead of a DB row served via
        ``GET /observability/traces/{trace_id}``. Proves the two sinks (G1 DB, G2 OTel) are
        genuinely independent: this test never calls the ``/observability`` endpoint at all.
        """
        client = traced_app
        registered_tool_name = await _register_probe_tool(client)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-c1-2",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {"note": "please check the account on file"}},
        }
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"

        # S1 (part 1): raw PII must not leak back to the RPC caller either.
        assert RAW_PII_EMAIL not in rpc_response.text, "Raw PII leaked into the tools/call RPC response body"

        # Now inspect the in-memory OTel spans exported through the patched process tracer
        # instead of querying /observability -- this is the G2 sink, not the G1 DB sink.
        spans = otel_memory_exporter.get_finished_spans()
        metric_spans = [s for s in spans if s.name == "plugin.metrics.pii_filter"]
        assert metric_spans, f"gateway did not export a 'plugin.metrics.pii_filter' OTel span; span names present: {[s.name for s in spans]}"

        attrs = dict(metric_spans[0].attributes)
        assert attrs.get("total_detections", 0) >= 1, f"Expected at least 1 PII detection, got attributes: {attrs}"
        assert attrs.get("total_masked", 0) >= 1, f"Expected at least 1 masked value, got attributes: {attrs}"
        assert "email" in str(attrs.get("detection_types", "")), f"Expected 'email' in detection_types, got: {attrs.get('detection_types')}"

        # S1 (part 2, the security-critical assertion) end-to-end on the OTel sink: the raw
        # matched PII value must never appear on any exported span, only counts/type-names.
        assert RAW_PII_EMAIL not in str(attrs), "SECURITY: raw PII leaked into the OTel 'plugin.metrics.pii_filter' span attributes"
        for span in spans:
            for key, value in dict(span.attributes or {}).items():
                assert RAW_PII_EMAIL not in str(value), f"SECURITY: raw PII found in OTel span '{span.name}' attribute '{key}'"
