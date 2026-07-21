# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_otel_plugin_metadata_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
from typing import Optional
from unittest.mock import AsyncMock

# Third-Party
import yaml

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
from cpex.framework import PluginError, PluginViolationError, ResourceHookType, ToolHookType  # noqa: E402
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
from mcpgateway.config import settings  # noqa: E402
import mcpgateway.db as db_mod  # noqa: E402
from mcpgateway.db import Base  # noqa: E402
import mcpgateway.main as main_mod  # noqa: E402
from mcpgateway.main import (  # noqa: E402
    database_exception_handler,
    get_db,
    plugin_exception_handler,
    plugin_violation_exception_handler,
    request_validation_exception_handler,
    resource_router,
    tool_router,
    unhandled_exception_handler,
    utility_router,
    validation_exception_handler,
)
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware  # noqa: E402
from mcpgateway.middleware.path_filter import clear_all_caches as clear_path_filter_caches  # noqa: E402
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

# Synthetic "secret" -- this is AWS's own long-published documentation placeholder access key
# ID (used throughout AWS SDK/CLI examples, e.g. https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html),
# never a real credential. Realistic enough in shape (``AKIA`` + 16 upper-alnum chars) to trip
# the secrets_detection plugin's aws_access_key_id detector; the whole point of this test is to
# prove this value (or any raw secret) never reaches /observability.
RAW_SECRET_VALUE = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret

SECRETS_TOOL_NAME = "secrets_probe_echo_tool"
SECRETS_UPSTREAM_TOOL_URL = "https://internal.e2e-fixture.invalid/secrets-echo"

# Synthetic base64-encoded payload -- decodes to an obviously-fake internal-looking string,
# never real exfiltrated data. Long/high-entropy/printable enough (>= min_encoded_length=24,
# min_decoded_length=12, min_entropy=3.3, min_printable_ratio=0.70 -- the shipped
# EncodedExfilDetector defaults) to trip the plugin's base64 detector; the point of this test
# is to prove this raw encoded value never reaches /observability once redaction is enabled.
RAW_ENCODED_PAYLOAD = base64.b64encode(b"e2e-synthetic-internal-exfil-fixture-payload-not-real-data").decode()

ENCODED_EXFIL_TOOL_NAME = "encoded_exfil_probe_echo_tool"
ENCODED_EXFIL_UPSTREAM_TOOL_URL = "https://internal.e2e-fixture.invalid/encoded-echo"

RETRY_TOOL_NAME = "retry_probe_echo_tool"
RETRY_UPSTREAM_TOOL_URL = "https://internal.e2e-fixture.invalid/retry-echo"

RESOURCE_REPUTATION_URI = "https://benign.e2e-fixture.invalid/report"

RATE_LIMITER_TOOL_NAME = "rate_limiter_probe_echo_tool"
RATE_LIMITER_UPSTREAM_TOOL_URL = "https://internal.e2e-fixture.invalid/rate-limiter-echo"


def _new_traceparent() -> tuple[str, str]:
    """Build a W3C ``traceparent`` header value with a trace_id we control.

    Returns:
        (trace_id, traceparent_header_value)
    """
    trace_id = secrets.token_hex(16)  # 32 lowercase hex chars
    parent_span_id = secrets.token_hex(8)  # 16 lowercase hex chars
    return trace_id, f"00-{trace_id}-{parent_span_id}-01"


@pytest_asyncio.fixture
async def traced_app(monkeypatch, tmp_path):
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

    # --- Real plugin manager factory, pointed at a private copy of plugins/config.yaml with
    # PIIFilter forced active. The shipped config.yaml disables PIIFilter by default (like every
    # other bundled cpex-* plugin -- opt-in, not opt-out, so upgrading doesn't silently start
    # masking tool responses); this test needs it active to exercise the real G0/G1/G2 chain
    # end-to-end, so it patches a scratch copy rather than depending on (or dictating) the
    # shipped default. ---
    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == "PIIFilter":
            plugin_entry["mode"] = "sequential"
    patched_config_path = tmp_path / "plugins_config_pii_filter_enabled.yaml"
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


@pytest_asyncio.fixture
async def traced_app_secrets_detection(monkeypatch, tmp_path):
    """Task 7 parity check: same real-temp-DB/dedicated-FastAPI-app pattern as ``traced_app``
    above, but forces the ``SecretsDetection`` plugin active instead of ``PIIFilter``.

    ``secrets_detection`` is Rust-core like ``pii_filter`` (both ship as separate
    ``cpex-*`` packages installed from the sibling ``../cpex-plugins`` checkout), so this
    fixture is structurally the same kind of test as ``traced_app`` -- it is kept as its own
    fixture (rather than parametrizing ``traced_app``) so the already-passing/well-documented
    ``pii_filter`` fixture is not touched at all by this addition.

    Two deltas from the shipped ``plugins/config.yaml`` ``SecretsDetection`` entry, beyond
    flipping ``mode`` to ``"sequential"`` (mirroring how ``traced_app`` flips ``PIIFilter``'s
    mode -- see that fixture's docstring):

      * ``block_on_detection: False`` -- the shipped default is ``True`` (see the config.yaml
        comment on the ``SecretsDetection`` entry: unlike ``PIIFilter``, this plugin blocks by
        default). Left at its default, ``tool_post_invoke``'s ``invoke_hook(...,
        violations_as_exceptions=True, ...)`` call in ``ToolService`` would raise
        ``PluginViolationError`` *before* ``record_plugin_metrics()`` is ever reached, so no
        ``plugin.metrics.secrets_detection`` span would exist to assert on. Disabling blocking
        here is the direct analogue of ``PIIFilter``'s own default (``block_on_detection:
        false``, redact-not-block) that the ``traced_app`` docstring/tests already rely on.
      * ``redact: True`` -- the shipped default is ``False``. Without redaction, a non-blocking
        detection would still return the raw secret value in the tool result (no masking
        pass), which would fail this test's S1 (no-raw-secret-leak) assertion the same way an
        unmasked PII value would fail the ``pii_filter`` test. Mirrors ``PIIFilter``'s masking
        behavior (``block_on_detection=false`` there also implies "redact instead").
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

    # --- Real plugin manager factory, pointed at a private copy of plugins/config.yaml with
    # SecretsDetection forced active (see the docstring above for why block_on_detection/redact
    # are also overridden here, not just mode). ---
    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == "SecretsDetection":
            plugin_entry["mode"] = "sequential"
            plugin_entry.setdefault("config", {})
            plugin_entry["config"]["block_on_detection"] = False
            plugin_entry["config"]["redact"] = True
    patched_config_path = tmp_path / "plugins_config_secrets_detection_enabled.yaml"
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
    assert plugin_manager is not None, "Plugin manager factory failed to initialize -- check plugins/config.yaml and that cpex-secrets-detection is installed"
    assert plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE), "secrets_detection plugin not registered for tool_post_invoke -- check plugins/config.yaml"

    # --- Dedicated FastAPI app instance (NOT mcpgateway.main.app) ---
    observability_service = ObservabilityService()
    test_app = FastAPI(title="otel-secrets-detection-metadata-e2e")
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

    # --- Auth: dependency-override pattern (mirrors traced_app / test_admin_apis.py) ---
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
            "content": [{"type": "text", "text": f"Rotate this credential immediately: {RAW_SECRET_VALUE}"}],
            "isError": False,
        },
        request=httpx.Request("POST", SECRETS_UPSTREAM_TOOL_URL),
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


@asynccontextmanager
async def _build_traced_app(monkeypatch, tmp_path, *, app_title: str, plugin_name: str, config_overrides: Optional[dict] = None, mock_upstream_url: str, mock_upstream_response: dict):
    """Shared boilerplate for the ``traced_app_<plugin>`` fixtures added alongside
    ``traced_app``/``traced_app_secrets_detection`` above (real-e2e coverage for the
    remaining plugins whose metrics wiring this branch adds: ``encoded_exfil_detection``,
    ``retry_with_backoff``, ``rate_limiter``).

    Identical real-temp-DB/dedicated-FastAPI-app/dependency-override-auth pattern as those two
    fixtures -- factored out here (rather than duplicated a 3rd/4th/5th time) because it is now
    used by 3+ new fixtures with only the target plugin name, its config overrides, and the
    mocked upstream tool response actually varying. ``traced_app``/``traced_app_secrets_detection``
    themselves are deliberately left untouched (not rewired onto this helper) per their own
    docstrings' stated reasoning for staying self-contained.

    ``url_reputation`` (hooks ``resource_pre_fetch``, not ``tool_post_invoke``) does not fit this
    tool-registration/``tools/call`` shape at all and gets its own dedicated fixture instead.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: pytest tmp_path fixture, for the scratch patched plugin config file.
        app_title: FastAPI app title (cosmetic, shows up in e.g. OpenAPI docs).
        plugin_name: The ``name`` of the plugin entry in ``plugins/config.yaml`` to flip to
            ``"sequential"`` mode (and merge ``config_overrides`` into).
        config_overrides: Optional dict merged into the target plugin's ``config`` block, on
            top of the shipped defaults (e.g. ``{"block_on_detection": False, "redact": True}``).
        mock_upstream_url: URL the registered REST probe tool points at.
        mock_upstream_response: JSON body the mocked upstream HTTP response returns.

    Yields:
        An ``httpx.AsyncClient`` wired to the dedicated app, real DB, and real plugin manager.
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
    monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", TestSessionLocal, raising=False)
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

    # --- Real plugin manager factory, pointed at a private copy of plugins/config.yaml with
    # the target plugin forced active (mode: "sequential") plus any config_overrides. ---
    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == plugin_name:
            plugin_entry["mode"] = "sequential"
            if config_overrides:
                plugin_entry.setdefault("config", {})
                plugin_entry["config"].update(config_overrides)
    patched_config_path = tmp_path / f"plugins_config_{plugin_name}_enabled.yaml"
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
    assert plugin_manager is not None, f"Plugin manager factory failed to initialize -- check plugins/config.yaml and that the package for {plugin_name!r} is installed"

    # --- Dedicated FastAPI app instance (NOT mcpgateway.main.app) ---
    observability_service = ObservabilityService()
    test_app = FastAPI(title=app_title)
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

    # --- Auth: dependency-override pattern (mirrors traced_app / test_admin_apis.py) ---
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
        json=mock_upstream_response,
        request=httpx.Request("POST", mock_upstream_url),
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


@pytest_asyncio.fixture
async def traced_app_encoded_exfil_detection(monkeypatch, tmp_path):
    """Real-e2e parity check for ``EncodedExfilDetector`` (Rust-core, like ``pii_filter``/
    ``secrets_detection``), via ``_build_traced_app`` above.

    Two config deltas from the shipped default (same reasoning as
    ``traced_app_secrets_detection``'s docstring): ``block_on_detection: False`` (shipped
    default is ``True`` -- left at default, the detection would raise ``PluginViolationError``
    before ``record_plugin_metrics()`` ever runs) and ``redact: True`` (shipped default is
    ``False`` -- without it the raw encoded value would survive in the tool result, failing
    this test's no-raw-value-leak assertion).
    """
    async with _build_traced_app(
        monkeypatch,
        tmp_path,
        app_title="otel-encoded-exfil-detection-metadata-e2e",
        plugin_name="EncodedExfilDetector",
        config_overrides={"block_on_detection": False, "redact": True},
        mock_upstream_url=ENCODED_EXFIL_UPSTREAM_TOOL_URL,
        mock_upstream_response={"content": [{"type": "text", "text": f"internal debug dump: {RAW_ENCODED_PAYLOAD}"}], "isError": False},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def traced_app_retry_with_backoff(monkeypatch, tmp_path):
    """Real-e2e parity check for ``RetryWithBackoffPlugin`` (Rust-core), via
    ``_build_traced_app`` above.

    One config delta from the shipped default: ``jitter: False``. With jitter on (the shipped
    default), the per-attempt delay is sampled uniformly from ``0..=ceiling`` -- legitimately
    (if rarely, ~1/(ceiling_ms+1) per attempt) landing on exactly ``0``, which the gateway reads
    as "don't retry" (``retry_delay_ms > 0``), collapsing this test's real-retries assertion
    into a rare flake. Disabling jitter makes the delay deterministic (``backoff_base_ms *
    2**attempt``, capped at ``max_backoff_ms``) without touching whether metrics are emitted or
    what fields they carry. This plugin never blocks (there is no ``block_on_detection``-style
    knob in its config schema -- see ``plugins/config.yaml``), so the other shipped defaults
    (``max_retries: 2``, ``backoff_base_ms: 200``, ...) are used as-is.

    The mocked upstream REST tool always returns ``isError: true``, so the real plugin's
    ``is_failure`` check is deterministically retryable on every attempt -- the gateway will
    genuinely re-invoke the (mocked) upstream up to ``max_retries`` times before giving up,
    each attempt producing its own ``plugin.metrics.retry_with_backoff`` span (this is the
    exact bug IBM/cpex-plugins#124 broke: with that regression, none of these retries would
    have fired and there would be exactly one span with ``retry_count: 0``). No PII/secret is
    involved here, so there is no raw-value-leak assertion for this fixture's tests -- the
    metrics themselves (``retry_count``, ``retry_delay_ms``) are the entire point.
    """
    async with _build_traced_app(
        monkeypatch,
        tmp_path,
        app_title="otel-retry-with-backoff-metadata-e2e",
        plugin_name="RetryWithBackoffPlugin",
        config_overrides={"jitter": False},
        mock_upstream_url=RETRY_UPSTREAM_TOOL_URL,
        mock_upstream_response={"content": [{"type": "text", "text": "upstream transient failure"}], "isError": True},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def traced_app_url_reputation(monkeypatch, tmp_path):
    """Real-e2e coverage for ``url_reputation``, driving the real ``URLReputationPlugin``
    CPEX plugin (installed from ../cpex-plugins, Rust-backed).

    Structurally different from every fixture above: ``URLReputationPlugin`` hooks
    ``resource_pre_fetch`` (see ``plugins/config.yaml``), not ``tool_post_invoke`` -- there is
    no tool call, no mocked upstream HTTP tool backend, and no ``tools/call``/``/rpc`` involved
    at all. Instead this registers a real resource (``POST /resources``, real DB row) and reads
    it back (``GET /resources/{resource_id}``, real ``ResourceService.read_resource``), which
    is where ``resource_pre_fetch`` actually runs (see
    ``mcpgateway/services/resource_service.py``'s ``record_plugin_metrics(current_trace_id.get(),
    pre_result.metadata)`` call). Does not reuse ``_build_traced_app`` above for this reason --
    it wires ``resource_router`` instead of ``tool_router``/``utility_router`` and skips the
    upstream-tool-mock section entirely.

    No config overrides: verified directly against the real plugin (see this branch's git
    history) that a plain, non-blocked ``https://`` URI (not in ``blocked_domains``, not
    matching ``blocked_patterns``, not using the insecure ``http://`` scheme -- which the
    shipped default *does* hard-block, unlike the detector plugins' block_on_detection=false
    "redact instead" pattern) reaches ``continue_processing=True`` and still emits
    ``result.metadata["url_reputation"]`` with ``total_checked: 1``. Unlike the detector
    fixtures above, there is no raw-value-leak concern here -- a URL is not sensitive content.
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

    # ``/resources/...`` is not in the shipped ``settings.observability_include_paths``
    # allowlist (mcpgateway/config.py -- it only covers /rpc, /sse, /message, /mcp,
    # /servers/{id}/..., /a2a by default), so a GET /resources/{id} request would never be
    # traced under the shipped defaults and this test's whole premise (a genuinely traced
    # request causing resource_pre_fetch metrics to reach /observability) would be
    # unreachable. Patch the include list to add resource-read paths for this fixture only,
    # and clear the module's lru_cache'd compiled-regex/skip-decision caches (path_filter.py)
    # so the patched list actually takes effect -- and clear them again on teardown so the
    # patched value doesn't leak into other tests once monkeypatch reverts the setting.
    monkeypatch.setattr(settings, "observability_include_paths", settings.observability_include_paths + [r"^/resources(?:/|$)"])
    clear_path_filter_caches()

    real_config = yaml.safe_load((_REPO_ROOT / "plugins" / "config.yaml").read_text())
    for plugin_entry in real_config.get("plugins", []):
        if plugin_entry.get("name") == "URLReputationPlugin":
            plugin_entry["mode"] = "sequential"
    patched_config_path = tmp_path / "plugins_config_url_reputation_enabled.yaml"
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
    assert plugin_manager is not None, "Plugin manager factory failed to initialize -- check plugins/config.yaml and that cpex-url-reputation is installed"
    assert plugin_manager.has_hooks_for(ResourceHookType.RESOURCE_PRE_FETCH), "url_reputation plugin not registered for resource_pre_fetch -- check plugins/config.yaml"

    observability_service = ObservabilityService()
    test_app = FastAPI(title="otel-url-reputation-metadata-e2e")
    test_app.add_middleware(ObservabilityMiddleware, enabled=True, service=observability_service)
    test_app.include_router(resource_router)  # real POST /resources, GET /resources/{resource_id}
    test_app.include_router(observability_router)  # real GET /observability/traces/{trace_id}
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

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://e2e-test") as client:
        yield client

    test_app.dependency_overrides.clear()
    await shutdown_plugin_manager_factory()
    enable_plugins(False)
    engine.dispose()
    # monkeypatch has now reverted settings.observability_include_paths to the shipped
    # default; clear the caches again so path_filter functions recompute against it instead
    # of continuing to serve the patched-in "/resources" pattern to other tests.
    clear_path_filter_caches()


def _auth_headers() -> dict:
    """Mint a real admin JWT via tests/helpers/auth.make_test_jwt and build a Bearer header."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
    return make_auth_headers(token)


async def _register_probe_tool(
    client: AsyncClient,
    tool_name: str = TOOL_NAME,
    upstream_url: str = UPSTREAM_TOOL_URL,
    description: str = "E2E fixture tool: echoes upstream content so tool_post_invoke has PII to detect.",
) -> str:
    """Register a REST tool whose (mocked) upstream response echoes sensitive content, via a
    real POST /tools call.

    Defaults preserve the original ``pii_probe_echo_tool``/``UPSTREAM_TOOL_URL`` behavior;
    ``tool_name``/``upstream_url``/``description`` let other fixtures (e.g. the
    secrets_detection parity check below) register an analogous probe tool against a
    different mocked upstream without duplicating this whole helper.

    Returns:
        The gateway-assigned (slugified) tool ``name`` to use for ``tools/call`` lookups --
        registration accepts the human-readable ``tool_name`` but the RPC dispatcher resolves
        tools by their normalized ``name`` (dashes), not the original ``customName``.
    """
    tool_payload = {
        "tool": {
            "name": tool_name,
            "description": description,
            "integrationType": "REST",
            "url": upstream_url,
            "requestType": "POST",
            "visibility": "public",
        },
        "team_id": None,
    }
    response = await client.post("/tools", json=tool_payload, headers=_auth_headers())
    assert response.status_code == 200, f"Tool registration failed: {response.status_code} {response.text}"
    return response.json()["name"]


async def _register_probe_resource(
    client: AsyncClient,
    uri: str,
    name: str = "url_reputation_probe_resource",
    content: str = "Quarterly report placeholder content.",
) -> str:
    """Register a resource (real ``POST /resources`` call, real DB row) so a subsequent
    ``GET /resources/{resource_id}`` can trigger ``resource_pre_fetch`` against its ``uri``.

    Mirrors ``_register_probe_tool``'s multi-``Body(...)``-param request shape
    (``{"resource": {...}, "team_id": None, "visibility": "public"}``) for ``create_resource``.

    Returns:
        The gateway-assigned resource ``id`` to use for the ``GET /resources/{resource_id}`` call.
    """
    resource_payload = {
        "resource": {
            "uri": uri,
            "name": name,
            "description": "E2E fixture resource: exercises resource_pre_fetch against a real uri.",
            "mimeType": "text/plain",
            "content": content,
        },
        "team_id": None,
        "visibility": "public",
    }
    response = await client.post("/resources", json=resource_payload, headers=_auth_headers())
    assert response.status_code == 200, f"Resource registration failed: {response.status_code} {response.text}"
    return response.json()["id"]


@pytest_asyncio.fixture
async def reachable_redis_url() -> str:
    """Resolve a real, reachable Redis URL for the ``rate_limiter`` real-e2e test below, or skip
    that test cleanly (not the whole module) when none is available.

    ``RateLimiterPlugin`` (Rust-core, per ``plugins/config.yaml``) fails OPEN and emits no
    metadata at all when its configured Redis backend is unreachable (verified directly against
    the real plugin: ``fail_mode`` defaults such that an unreachable backend logs a warning and
    allows the call through with ``result.metadata == {}``) -- there is no way to prove real
    metrics reach ``/observability`` without a real, reachable Redis. ``tests/e2e/`` (via
    ``.github/workflows/pytest.yml``'s ``pytest`` job) has no Redis service container, unlike
    ``.github/workflows/plugin-integration.yml``'s dedicated rate-limiter E2E legs -- so this
    fixture is real when Redis happens to be reachable (locally, or in an environment that
    does provision one) and skips cleanly otherwise, mirroring ``otel_memory_exporter``'s
    graceful-skip-when-the-optional-dependency-is-absent pattern above.

    Returns:
        A Redis URL confirmed reachable via a real ``PING``.
    """
    # Third-Party -- deferred so the module always imports even without redis-py, though it is
    # already a hard gateway dependency (mcpgateway.utils.redis_client) so this should never
    # actually be missing.
    import redis.asyncio as redis_asyncio  # pylint: disable=import-outside-toplevel

    url = os.environ.get("RATELIMITER_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    client = redis_asyncio.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip", not "fail"
        pytest.skip(f"No reachable Redis at {url!r} for the rate_limiter real-e2e test: {exc}")
    finally:
        await client.aclose()
    return url


@pytest_asyncio.fixture
async def traced_app_rate_limiter(monkeypatch, tmp_path, reachable_redis_url: str):
    """Real-e2e parity check for ``RateLimiterPlugin`` (Rust-core), via ``_build_traced_app``
    above.

    Unlike the ``tool_post_invoke``-hooking plugins covered elsewhere in this module, this
    plugin hooks ``tool_pre_invoke`` (see ``plugins/config.yaml``) -- ``_build_traced_app`` does
    not care which hook the target plugin registers for, only that a ``tools/call`` RPC reaches
    it, so it is reused unmodified here.

    Config overrides point the plugin at ``reachable_redis_url`` (skips this fixture's
    dependent test cleanly when none is reachable -- see that fixture's docstring) with a
    per-test-run-unique ``redis_key_prefix`` so repeated test runs never share rate-limit state
    across each other. The shipped ``by_user: "30/m"`` limit is left as-is -- a single probe
    call in this test is trivially under budget, so the call is allowed (not throttled) and the
    plugin still emits its per-call ``allowed``/``throttled``/``backend`` metadata either way.
    """
    async with _build_traced_app(
        monkeypatch,
        tmp_path,
        app_title="otel-rate-limiter-metadata-e2e",
        plugin_name="RateLimiterPlugin",
        config_overrides={"redis_url": reachable_redis_url, "redis_key_prefix": f"rl-e2e-{secrets.token_hex(6)}"},
        mock_upstream_url=RATE_LIMITER_UPSTREAM_TOOL_URL,
        mock_upstream_response={"content": [{"type": "text", "text": "ok"}], "isError": False},
    ) as client:
        yield client


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

    Note: ``pytest.importorskip("opentelemetry.sdk.trace")`` alone is not a reliable guard
    here -- in some environments ``opentelemetry-api`` (a hard dependency, always present)
    leaves behind an empty PEP 420 namespace package at ``opentelemetry.sdk.trace`` even
    when the real ``opentelemetry-sdk`` distribution (the 'observability' extra) is absent,
    so the module path resolves but has no actual symbols. Guard on the concrete import
    instead and convert failure into a skip.
    """
    # Third-Party -- deferred so the module itself always imports even without the extra;
    # only tests that request this fixture pay the (skippable) cost.
    try:
        from opentelemetry.sdk.trace import TracerProvider  # pylint: disable=import-outside-toplevel
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # pylint: disable=import-outside-toplevel
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        pytest.skip(f"opentelemetry-sdk (the 'observability' extra) is not installed: {exc}")

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


class TestOtelSecretsDetectionMetadataE2E:
    """Task 7: ``secrets_detection`` parity check for the C1 chain above.

    Mirrors ``TestOtelPluginMetadataE2E.test_traced_tool_call_surfaces_pii_filter_metrics_without_leaking_pii``
    exactly (same traceparent -> tools/call -> /observability/traces/{trace_id} chain, same
    G1 DB-sink assertion shape, same S1 no-raw-secret-leak assertion) but drives the real
    ``secrets_detection`` CPEX plugin (installed from ../cpex-plugins, Rust-backed, like
    ``pii_filter``) via the ``traced_app_secrets_detection`` fixture instead of ``pii_filter``
    via ``traced_app``.

    NOTE: this file's ``pii_filter`` tests above cannot run to a real pass/fail result in a
    fresh checkout of this environment -- they fail at fixture setup with an AssertionError
    from the ``assert plugin_manager.has_hooks_for(...)`` line (chained from
    ``ModuleNotFoundError: No module named 'cpex_pii_filter'``), because ``cpex-pii-filter``
    has never been installed into this gateway's ``.venv`` by default. This test hits the
    identical failure mode for ``cpex-secrets-detection`` when that package is likewise not
    installed -- see Task 7's report for the exact captured error.

    Unlike ``cpex-pii-filter``, ``cpex-secrets-detection`` (Rust/maturin-built, from the
    sibling ``../cpex-plugins`` checkout's ``plugins/rust/python-package/secrets_detection``)
    WAS successfully dev-installed into this gateway's ``.venv`` during Task 7's verification
    (``pip install -e <path> --no-deps``; cargo/rustc/maturin were all present in this
    sandbox), and with it installed this test passes end-to-end for real -- not just up to
    the same install boundary. That install is local to this sandbox's ``.venv`` (which is
    git-ignored) and is not committed as part of this change; a fresh checkout/CI run without
    that package installed will still hit the ModuleNotFoundError-derived AssertionError
    above, same as the ``pii_filter`` tests.
    """

    @pytest.mark.asyncio
    async def test_traced_tool_call_surfaces_secrets_detection_metrics_without_leaking_secret(self, traced_app_secrets_detection: AsyncClient):
        """Full chain: traceparent -> tools/call -> secrets_detection -> /observability/traces/{trace_id}."""
        client = traced_app_secrets_detection
        registered_tool_name = await _register_probe_tool(
            client,
            tool_name=SECRETS_TOOL_NAME,
            upstream_url=SECRETS_UPSTREAM_TOOL_URL,
            description="E2E fixture tool: echoes upstream content so tool_post_invoke has a secret-shaped value to detect.",
        )

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-secrets-1",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {"note": "please rotate the credential on file"}},
        }
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"

        # S1 (part 1): the raw secret value must not leak back to the RPC caller either --
        # the plugin's redaction (block_on_detection=false, redact=true per the fixture's
        # config overrides, so it redacts rather than blocks) should have replaced it before
        # the result was returned.
        assert RAW_SECRET_VALUE not in rpc_response.text, "Raw secret leaked into the tools/call RPC response body"

        # Now query the real observability endpoint for the trace we chose via traceparent.
        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        secrets_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.secrets_detection"]
        assert secrets_metric_spans, f"No 'plugin.metrics.secrets_detection' span found; span names present: {[s.get('name') for s in spans]}"

        # Unlike pii_filter, the real cpex-secrets-detection plugin (verified against
        # v0.3.7) does not emit a "stage" field in its tool_post_invoke metadata, so --
        # unlike the pii_filter test above -- there is nothing to filter spans by here;
        # this tool only triggers one post-invoke detection pass, so the single span is it.
        attrs = secrets_metric_spans[0]["attributes"]
        assert attrs.get("total_detections", 0) >= 1, f"Expected at least 1 secret detection, got attributes: {attrs}"
        assert attrs.get("total_masked", 0) >= 1, f"Expected at least 1 masked value, got attributes: {attrs}"
        assert attrs.get("total_blocked", 0) == 0, f"Expected no blocked detections (block_on_detection=false), got attributes: {attrs}"
        # "secret_types" is the allowlisted string field for this plugin (see
        # mcpgateway/plugins/utils.py::_SAFE_STRING_FIELD_NAMES). Verified against the real
        # plugin: RAW_SECRET_VALUE (defined above) is classified as "aws_access_key_id".
        assert "aws_access_key_id" in str(attrs.get("secret_types", "")), f"Expected 'aws_access_key_id' in secret_types, got: {attrs.get('secret_types')}"
        assert secrets_metric_spans[0].get("resource_type") == "plugin"
        assert secrets_metric_spans[0].get("resource_name") == "secrets_detection"

        # S1 (part 2, the security-critical assertion): the RAW matched secret value must
        # never appear anywhere in the observability response -- not in span attributes, not
        # in event messages, not anywhere in the serialized body. Only counts/type-names
        # allowed.
        full_response_text = trace_response.text
        assert RAW_SECRET_VALUE not in full_response_text, "SECURITY: raw secret value leaked into /observability/traces/{trace_id} response"

        # Belt-and-suspenders: no span attribute value anywhere in the trace contains the raw secret.
        for span in spans:
            for key, value in (span.get("attributes") or {}).items():
                assert RAW_SECRET_VALUE not in str(value), f"SECURITY: raw secret found in span '{span.get('name')}' attribute '{key}'"


class TestOtelEncodedExfilDetectionMetadataE2E:
    """Real-e2e parity check for ``encoded_exfil_detection``, mirroring
    ``TestOtelSecretsDetectionMetadataE2E`` above but driving the real
    ``EncodedExfilDetector`` CPEX plugin via ``traced_app_encoded_exfil_detection``.
    """

    @pytest.mark.asyncio
    async def test_traced_tool_call_surfaces_encoded_exfil_detection_metrics_without_leaking_payload(self, traced_app_encoded_exfil_detection: AsyncClient):
        """Full chain: traceparent -> tools/call -> encoded_exfil_detection -> /observability/traces/{trace_id}."""
        client = traced_app_encoded_exfil_detection
        registered_tool_name = await _register_probe_tool(
            client,
            tool_name=ENCODED_EXFIL_TOOL_NAME,
            upstream_url=ENCODED_EXFIL_UPSTREAM_TOOL_URL,
            description="E2E fixture tool: echoes upstream content so tool_post_invoke has an encoded payload to detect.",
        )

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-encoded-exfil-1",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {"note": "please review the debug dump"}},
        }
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"

        # S1 (part 1): the raw encoded value must not leak back to the RPC caller either --
        # block_on_detection=false + redact=true (this fixture's config overrides) means the
        # plugin redacts rather than blocks.
        assert RAW_ENCODED_PAYLOAD not in rpc_response.text, "Raw encoded payload leaked into the tools/call RPC response body"

        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        exfil_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.encoded_exfil_detection"]
        assert exfil_metric_spans, f"No 'plugin.metrics.encoded_exfil_detection' span found; span names present: {[s.get('name') for s in spans]}"

        # Verified against the real cpex-encoded-exfil-detection plugin (v0.3.6): this plugin
        # only ever registers one tool_post_invoke detection pass for this tool, so the single
        # span is it.
        attrs = exfil_metric_spans[0]["attributes"]
        assert attrs.get("total_detections", 0) >= 1, f"Expected at least 1 encoded-payload detection, got attributes: {attrs}"
        assert "base64" in str(attrs.get("encoding_types", "")), f"Expected 'base64' in encoding_types, got: {attrs.get('encoding_types')}"
        assert exfil_metric_spans[0].get("resource_type") == "plugin"
        assert exfil_metric_spans[0].get("resource_name") == "encoded_exfil_detection"

        # S1 (part 2, the security-critical assertion): the RAW matched encoded value must
        # never appear anywhere in the observability response.
        full_response_text = trace_response.text
        assert RAW_ENCODED_PAYLOAD not in full_response_text, "SECURITY: raw encoded payload leaked into /observability/traces/{trace_id} response"

        for span in spans:
            for key, value in (span.get("attributes") or {}).items():
                assert RAW_ENCODED_PAYLOAD not in str(value), f"SECURITY: raw encoded payload found in span '{span.get('name')}' attribute '{key}'"


class TestOtelRetryWithBackoffMetadataE2E:
    """Real-e2e coverage for ``retry_with_backoff``, driving the real ``RetryWithBackoffPlugin``
    CPEX plugin via ``traced_app_retry_with_backoff``.

    Unlike the detector plugins above, there is no sensitive raw value to avoid leaking here --
    this test's whole point is that a genuinely traced, genuinely retried tool call produces
    ``plugin.metrics.retry_with_backoff`` spans reflecting the real retry attempts. This is
    the exact regression IBM/cpex-plugins#124 introduced (fixed in #137, released as 0.3.7,
    consumed by this branch's ``pyproject.toml``/``uv.lock`` bump): the plugin's ``is_failure``
    read the ``tool_post_invoke`` result via ``PyDict::get_item`` (C-level dict storage), which
    silently misses every key on the gateway's ``CopyOnWriteDict`` payload-isolation wrapper --
    every retryable failure looked like a success and the plugin never signalled a retry, so
    this test would see exactly one span with ``retry_count: 0`` against the buggy 0.3.6.
    """

    @pytest.mark.asyncio
    async def test_traced_tool_call_surfaces_retry_with_backoff_metrics_across_real_retries(self, traced_app_retry_with_backoff: AsyncClient):
        """Full chain: traceparent -> tools/call (persistently failing upstream) -> real gateway
        re-invocation -> retry_with_backoff -> /observability/traces/{trace_id}."""
        client = traced_app_retry_with_backoff
        registered_tool_name = await _register_probe_tool(
            client,
            tool_name=RETRY_TOOL_NAME,
            upstream_url=RETRY_UPSTREAM_TOOL_URL,
            description="E2E fixture tool: a mocked upstream that always errors, so tool_post_invoke has a retryable failure on every attempt.",
        )

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-retry-1",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {"note": "trigger a transient upstream failure"}},
        }
        # The mocked upstream always errors, so the gateway genuinely retries (real
        # asyncio.sleep backoff delays, real recursive ToolService.invoke_tool re-invocation)
        # up to the shipped max_retries=2 before giving up and returning the last failure.
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"
        # The tool result itself surfaces the final (still-failing) upstream error -- this
        # test is not about the RPC-level outcome, only that retries genuinely happened and
        # were recorded as metrics.
        assert rpc_body["result"]["isError"] is True, f"Expected the exhausted-retry-budget result to still report isError=true, got: {rpc_body}"

        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        retry_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.retry_with_backoff"]
        assert retry_metric_spans, f"No 'plugin.metrics.retry_with_backoff' span found; span names present: {[s.get('name') for s in spans]}"

        # THE regression proof: with a persistently-failing upstream and max_retries=2, a
        # working plugin produces one span per attempt (the original call plus up to 2
        # retries), with retry_count strictly increasing across them. Against the
        # IBM/cpex-plugins#124 bug, is_failure never detected the failure at all, so exactly
        # one span would exist here with retry_count=0 and retry_delay_ms=0 -- this assertion
        # is what would have caught that regression.
        retry_counts = sorted(s["attributes"].get("retry_count", 0) for s in retry_metric_spans)
        assert len(retry_metric_spans) >= 2, f"Expected multiple retry attempts recorded (real retries happened), got spans with retry_counts={retry_counts}"
        assert retry_counts[0] >= 1, f"Expected the first recorded attempt to already show retry_count >= 1 (a real failure was detected), got retry_counts={retry_counts}"
        assert retry_counts == sorted(set(retry_counts)), f"Expected strictly distinct, increasing retry_count values across attempts, got {retry_counts}"

        for span in retry_metric_spans:
            assert span.get("resource_type") == "plugin"
            assert span.get("resource_name") == "retry_with_backoff"
            assert "retry_delay_ms" in span["attributes"], f"Expected retry_delay_ms in every retry_with_backoff span, got: {span['attributes']}"


class TestOtelUrlReputationMetadataE2E:
    """Real-e2e coverage for ``url_reputation``, driving the real ``URLReputationPlugin`` CPEX
    plugin via ``traced_app_url_reputation``.

    Structurally different from every other test class in this module: this triggers
    ``resource_pre_fetch`` via ``POST /resources`` + ``GET /resources/{resource_id}``, not
    ``tool_post_invoke`` via ``tools/call``. No sensitive raw value is involved (a URL is not a
    secret), so there is no raw-value-leak assertion here -- the point is simply proving a real
    resource_pre_fetch check reaches ``/observability`` with the expected counters.
    """

    @pytest.mark.asyncio
    async def test_traced_resource_read_surfaces_url_reputation_metrics(self, traced_app_url_reputation: AsyncClient):
        """Full chain: traceparent -> GET /resources/{id} -> url_reputation -> /observability/traces/{trace_id}."""
        client = traced_app_url_reputation
        resource_id = await _register_probe_resource(client, uri=RESOURCE_REPUTATION_URI)

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        read_response = await client.get(f"/resources/{resource_id}", headers=headers)
        assert read_response.status_code == 200, f"GET /resources/{{resource_id}} failed: {read_response.status_code} {read_response.text}"

        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        reputation_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.url_reputation"]
        assert reputation_metric_spans, f"No 'plugin.metrics.url_reputation' span found; span names present: {[s.get('name') for s in spans]}"

        attrs = reputation_metric_spans[0]["attributes"]
        assert attrs.get("total_checked", 0) >= 1, f"Expected at least 1 URL checked, got attributes: {attrs}"
        assert attrs.get("total_blocked", 0) == 0, f"Expected no blocked checks for a benign https:// URI, got attributes: {attrs}"
        assert reputation_metric_spans[0].get("resource_type") == "plugin"
        assert reputation_metric_spans[0].get("resource_name") == "url_reputation"


class TestOtelRateLimiterMetadataE2E:
    """Real-e2e coverage for ``rate_limiter``, driving the real ``RateLimiterPlugin`` CPEX
    plugin (backed by a real, reachable Redis -- see ``reachable_redis_url``'s docstring for
    why this is the one plugin in this module that needs a live external dependency, and skips
    cleanly rather than failing when one isn't available) via ``traced_app_rate_limiter``.
    """

    @pytest.mark.asyncio
    async def test_traced_tool_call_surfaces_rate_limiter_metrics(self, traced_app_rate_limiter: AsyncClient):
        """Full chain: traceparent -> tools/call -> rate_limiter (tool_pre_invoke) ->
        /observability/traces/{trace_id}."""
        client = traced_app_rate_limiter
        registered_tool_name = await _register_probe_tool(
            client,
            tool_name=RATE_LIMITER_TOOL_NAME,
            upstream_url=RATE_LIMITER_UPSTREAM_TOOL_URL,
            description="E2E fixture tool: a trivial echo, only used to drive tool_pre_invoke.",
        )

        trace_id, traceparent = _new_traceparent()
        headers = {**_auth_headers(), "traceparent": traceparent}

        rpc_request = {
            "jsonrpc": "2.0",
            "id": "e2e-rate-limiter-1",
            "method": "tools/call",
            "params": {"name": registered_tool_name, "arguments": {}},
        }
        rpc_response = await client.post("/rpc", json=rpc_request, headers=headers)
        assert rpc_response.status_code == 200, f"tools/call failed: {rpc_response.status_code} {rpc_response.text}"
        rpc_body = rpc_response.json()
        assert "error" not in rpc_body, f"tools/call returned a JSON-RPC error: {rpc_body}"

        trace_response = await client.get(f"/observability/traces/{trace_id}", headers=_auth_headers())
        assert trace_response.status_code == 200, f"GET /observability/traces/{{trace_id}} failed: {trace_response.status_code} {trace_response.text}"
        trace_body = trace_response.json()

        assert trace_body["trace_id"] == trace_id
        spans = trace_body.get("spans", [])
        assert spans, "No spans recorded for the traced request"

        rate_limiter_metric_spans = [s for s in spans if s.get("name") == "plugin.metrics.rate_limiter"]
        assert rate_limiter_metric_spans, f"No 'plugin.metrics.rate_limiter' span found; span names present: {[s.get('name') for s in spans]}"

        # Verified against the real cpex-rate-limiter plugin backed by a real Redis: a single
        # probe call, trivially under the shipped by_user="30/m" budget, is allowed and reports
        # backend="redis" (as opposed to metadata={} when the backend is unreachable -- see
        # reachable_redis_url's docstring; this assertion is what would catch that regression
        # if it were ever hit despite the fixture's own reachability check).
        attrs = rate_limiter_metric_spans[0]["attributes"]
        assert attrs.get("allowed", 0) >= 1, f"Expected the call to be allowed (under budget), got attributes: {attrs}"
        assert attrs.get("throttled", 0) == 0, f"Expected no throttling for a single under-budget call, got attributes: {attrs}"
        assert attrs.get("backend") == "redis", f"Expected backend='redis' (a reachable real Redis was used), got attributes: {attrs}"
        assert rate_limiter_metric_spans[0].get("resource_type") == "plugin"
        assert rate_limiter_metric_spans[0].get("resource_name") == "rate_limiter"
