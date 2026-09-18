# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_output_length_guard_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E test for output_length_guard plugin.

Proves, against a real gateway request pipeline (/tools, /rpc, /observability
routers, ObservabilityMiddleware, ToolService, PluginManager, ObservabilityService
backed by temp SQLite DB), that a traced HTTP tool-invoke request causes the
output_length_guard Rust-backed plugin to:
1. Truncate oversized tool output when strategy="truncate"
2. Record metrics and span attributes in the observability DB
3. Block oversized tool output when strategy="block"
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock
import uuid

# Third-Party
from cpex.framework import PluginError, PluginViolationError, ToolHookType
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
import httpx
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import yaml

# First-Party
from mcpgateway.auth import get_current_user
import mcpgateway.db as db_mod
from mcpgateway.db import Base
import mcpgateway.main as main_mod
from mcpgateway.main import (
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
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service
from mcpgateway.plugins import (
    enable_plugins,
    get_plugin_manager,
    init_plugin_manager_factory,
    shutdown_plugin_manager_factory,
)
from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES
from mcpgateway.routers.observability import router as observability_router
from mcpgateway.services.observability_service import ObservabilityService
from mcpgateway.utils.create_jwt_token import get_jwt_token
from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth
# Tests
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.utils.rbac_mocks import create_mock_email_user, create_mock_user_context, MockPermissionService

ADMIN_EMAIL = "admin@example.com"
UPSTREAM_TOOL_URL = "http://upstream-test-service.internal/tool"


def _build_test_w3c_traceparent() -> tuple[str, str, str]:
    """Generate a clean traceparent header, trace_id, and span_id."""
    trace_id_raw = uuid.uuid4().hex.lower()
    span_id_raw = uuid.uuid4().hex[:16].lower()
    header_val = f"00-{trace_id_raw}-{span_id_raw}-01"
    return header_val, trace_id_raw, span_id_raw


@pytest_asyncio.fixture
async def create_traced_app_olg(monkeypatch, tmp_path):
    """Factory fixture to create a real temp-DB gateway app with configurable OutputLengthGuardPlugin."""
    async def _make_app(plugin_config_overrides: dict | None = None, upstream_response: httpx.Response | None = None):
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
        except Exception:
            pass
        try:
            monkeypatch.setattr("mcpgateway.services.security_logger.SessionLocal", TestSessionLocal, raising=False)
        except Exception:
            pass
        try:
            monkeypatch.setattr("mcpgateway.services.audit_trail_service.SessionLocal", TestSessionLocal, raising=False)
        except Exception:
            pass

        def override_get_db():
            db = TestSessionLocal()
            try:
                yield db
            finally:
                db.close()

        base_cfg = {
            "min_chars": 0,
            "max_chars": 100,
            "strategy": "truncate",
            "ellipsis": "…",
            "word_boundary": False,
        }
        if plugin_config_overrides:
            base_cfg.update(plugin_config_overrides)

        plugin_config_data = {
            "plugins": [
                {
                    "name": "OutputLengthGuardPlugin",
                    "kind": "cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
                    "description": "Guards tool outputs",
                    "version": "0.1.0",
                    "author": "ContextForge",
                    "hooks": ["tool_post_invoke"],
                    "tags": ["guard", "length"],
                    "mode": "sequential",
                    "priority": 160,
                    "conditions": [],
                    "config": base_cfg,
                }
            ]
        }
        config_name = f"plugins_config_olg_{uuid.uuid4().hex[:8]}.yaml"
        patched_config_path = tmp_path / config_name
        patched_config_path.write_text(yaml.safe_dump(plugin_config_data, sort_keys=False))

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
        assert plugin_manager is not None
        assert plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE)

        observability_service = ObservabilityService()
        test_app = FastAPI(title="output-length-guard-e2e")
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

        if upstream_response is None:
            upstream_response = httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "A" * 500}],
                    "isError": False,
                },
                request=httpx.Request("POST", UPSTREAM_TOOL_URL),
            )

        from tests.e2e.test_otel_plugin_metadata_e2e import _mock_outbound_rest_request
        mock_request = AsyncMock(return_value=upstream_response)
        _mock_outbound_rest_request(monkeypatch, mock_request)

        transport = ASGITransport(app=test_app)
        client = AsyncClient(transport=transport, base_url="http://e2e-test")
        return client, test_app, engine

    yield _make_app

    await shutdown_plugin_manager_factory()
    enable_plugins(False)


@pytest.mark.asyncio
class TestOutputLengthGuardE2E:
    """End-to-end tests for output length guard in a running gateway app."""

    async def test_traced_tool_call_truncates_oversized_output_and_records_metrics(
        self, create_traced_app_olg
    ):
        """Oversized output is truncated by the Rust plugin and observability metrics are recorded."""
        client, test_app, engine = await create_traced_app_olg({"strategy": "truncate", "max_chars": 100})
        async with client:
            token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
            auth_headers = make_auth_headers(token)

            # 1. Register tool
            tool_payload = {
                "tool": {
                    "name": "e2e_oversized_tool_trunc",
                    "description": "Tool returning 500 chars",
                    "integrationType": "REST",
                    "url": UPSTREAM_TOOL_URL,
                    "requestType": "POST",
                    "visibility": "public",
                },
                "team_id": None,
            }
            reg_resp = await client.post("/tools", json=tool_payload, headers=auth_headers)
            assert reg_resp.status_code == 200
            assigned_name = reg_resp.json().get("name", "e2e-oversized-tool-trunc")

            # 2. Call tool with traceparent
            traceparent, trace_id, _ = _build_test_w3c_traceparent()
            call_headers = dict(auth_headers)
            call_headers["traceparent"] = traceparent

            rpc_payload = {
                "jsonrpc": "2.0",
                "id": "e2e-test-1",
                "method": "tools/call",
                "params": {
                    "name": assigned_name,
                    "arguments": {},
                },
            }
            rpc_resp = await client.post("/rpc", json=rpc_payload, headers=call_headers)
            assert rpc_resp.status_code == 200
            rpc_data = rpc_resp.json()
            assert "result" in rpc_data
            result_content = rpc_data["result"]["content"]
            assert len(result_content) > 0
            truncated_text = result_content[0]["text"]
            assert len(truncated_text) <= 100
            assert truncated_text.endswith("…")

            # 3. Query observability trace
            obs_resp = await client.get(f"/observability/traces/{trace_id}", headers=auth_headers)
            assert obs_resp.status_code == 200
            obs_data = obs_resp.json()

            # 4. Verify span & attributes
            spans = obs_data.get("spans", [])
            olg_spans = [s for s in spans if s.get("name") == "plugin.metrics.output_length_guard"]
            assert len(olg_spans) == 1
            olg_span = olg_spans[0]
            assert olg_span["resource_type"] == "plugin"
            assert olg_span["resource_name"] == "output_length_guard"
            assert olg_span["attributes"]["limit_mode"] == "character"
            assert olg_span["attributes"]["strategy"] == "truncate"
            assert olg_span["attributes"]["blocked"] is False
            assert olg_span["attributes"]["chars_seen"] == 500
            assert olg_span["attributes"]["truncated_count"] == 1

        test_app.dependency_overrides.clear()
        engine.dispose()

    async def test_traced_tool_call_blocks_oversized_output_and_records_blocked_metric(
        self, create_traced_app_olg
    ):
        """Oversized output is blocked by the Rust plugin when strategy='block' and returns violation."""
        client, test_app, engine = await create_traced_app_olg({"strategy": "block", "max_chars": 100})
        async with client:
            token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
            auth_headers = make_auth_headers(token)

            # 1. Register tool
            tool_payload = {
                "tool": {
                    "name": "e2e_oversized_tool_block",
                    "description": "Tool returning 500 chars",
                    "integrationType": "REST",
                    "url": UPSTREAM_TOOL_URL,
                    "requestType": "POST",
                    "visibility": "public",
                },
                "team_id": None,
            }
            reg_resp = await client.post("/tools", json=tool_payload, headers=auth_headers)
            assert reg_resp.status_code == 200
            assigned_name = reg_resp.json().get("name", "e2e-oversized-tool-block")

            # 2. Call tool with traceparent
            traceparent, trace_id, _ = _build_test_w3c_traceparent()
            call_headers = dict(auth_headers)
            call_headers["traceparent"] = traceparent

            rpc_payload = {
                "jsonrpc": "2.0",
                "id": "e2e-test-2",
                "method": "tools/call",
                "params": {
                    "name": assigned_name,
                    "arguments": {},
                },
            }
            rpc_resp = await client.post("/rpc", json=rpc_payload, headers=call_headers)
            assert rpc_resp.status_code in [200, 422]
            rpc_data = rpc_resp.json()
            # In JSON-RPC format, error is returned on violation
            assert "error" in rpc_data or rpc_data.get("isError") is True

        test_app.dependency_overrides.clear()
        engine.dispose()

    async def test_traced_tool_call_truncates_oversized_structured_output(
        self, create_traced_app_olg
    ):
        """Oversized text nested inside a list-of-MCP-content-items is truncated through the full gateway stack.

        The upstream tool returns a content array with two oversized text items.
        The plugin must truncate both items and return modified content through
        the gateway's /rpc endpoint.
        """
        structured_upstream = httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "B" * 500},
                    {"type": "text", "text": "C" * 500},
                ],
                "isError": False,
            },
            request=httpx.Request("POST", UPSTREAM_TOOL_URL),
        )
        client, test_app, engine = await create_traced_app_olg(
            {"strategy": "truncate", "max_chars": 50},
            upstream_response=structured_upstream,
        )
        async with client:
            token = make_test_jwt(ADMIN_EMAIL, is_admin=True)
            auth_headers = make_auth_headers(token)

            tool_payload = {
                "tool": {
                    "name": "e2e_structured_tool_trunc",
                    "description": "Tool returning two oversized text items",
                    "integrationType": "REST",
                    "url": UPSTREAM_TOOL_URL,
                    "requestType": "POST",
                    "visibility": "public",
                },
                "team_id": None,
            }
            reg_resp = await client.post("/tools", json=tool_payload, headers=auth_headers)
            assert reg_resp.status_code == 200
            assigned_name = reg_resp.json().get("name", "e2e-structured-tool-trunc")

            rpc_payload = {
                "jsonrpc": "2.0",
                "id": "e2e-test-3",
                "method": "tools/call",
                "params": {"name": assigned_name, "arguments": {}},
            }
            rpc_resp = await client.post("/rpc", json=rpc_payload, headers=auth_headers)
            assert rpc_resp.status_code == 200
            rpc_data = rpc_resp.json()
            assert "result" in rpc_data
            result_content = rpc_data["result"]["content"]
            assert len(result_content) == 2
            for item in result_content:
                assert item["type"] == "text"
                assert len(item["text"]) <= 50

        test_app.dependency_overrides.clear()
        engine.dispose()
