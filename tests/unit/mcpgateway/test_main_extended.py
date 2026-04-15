# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/test_main_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended tests for main.py to achieve 100% coverage.
These tests focus on uncovered code paths including conditional branches,
error handlers, and startup logic.
"""

# Standard
import asyncio
import base64
import builtins
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
from fastapi import HTTPException, Request
from fastapi import Response as FastAPIResponse
from fastapi.testclient import TestClient
import orjson
import pytest
import sqlalchemy as sa
from starlette.responses import Response as StarletteResponse

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.config import settings
import mcpgateway.db as db_mod
from mcpgateway.main import (
    _build_internal_mcp_auth_scope,
    _build_internal_mcp_forwarded_user,
    _create_jwt_identity_extractor,
    _decode_internal_mcp_auth_context,
    _enforce_internal_mcp_server_scope,
    _ensure_rpc_permission,
    _expected_internal_mcp_runtime_auth_header,
    _extract_scoped_permissions,
    _is_permission_admin_user,
    _parse_apijsonpath,
    _run_internal_mcp_authentication,
    _serialize_legacy_tool_payloads,
    _serialize_mcp_tool_definition,
    AdminAuthMiddleware,
    app,
    create_prompt,
    create_resource,
    create_tool,
    delete_prompt,
    delete_resource,
    delete_tool,
    DocsAuthMiddleware,
    export_configuration,
    export_selective_configuration,
    get_a2a_agent,
    handle_internal_mcp_authenticate,
    handle_internal_mcp_completion_complete,
    handle_internal_mcp_initialize,
    handle_internal_mcp_logging_set_level,
    handle_internal_mcp_notifications_cancelled,
    handle_internal_mcp_notifications_initialized,
    handle_internal_mcp_notifications_message,
    handle_internal_mcp_prompts_get,
    handle_internal_mcp_prompts_get_authz,
    handle_internal_mcp_prompts_list,
    handle_internal_mcp_prompts_list_authz,
    handle_internal_mcp_resource_templates_list,
    handle_internal_mcp_resource_templates_list_authz,
    handle_internal_mcp_resources_list,
    handle_internal_mcp_resources_list_authz,
    handle_internal_mcp_resources_read,
    handle_internal_mcp_resources_read_authz,
    handle_internal_mcp_resources_subscribe,
    handle_internal_mcp_resources_unsubscribe,
    handle_internal_mcp_roots_list,
    handle_internal_mcp_rpc,
    handle_internal_mcp_sampling_create_message,
    handle_internal_mcp_session_delete,
    handle_internal_mcp_tools_call,
    handle_internal_mcp_tools_call_metric,
    handle_internal_mcp_tools_call_resolve,
    handle_internal_mcp_tools_list,
    handle_internal_mcp_tools_list_authz,
    handle_rpc,
    import_configuration,
    InternalTrustedMCPTransportBridge,
    jsonpath_modifier,
    list_a2a_agents,
    list_resources,
    MCPPathRewriteMiddleware,
    MCPRuntimeHeaderTransportWrapper,
    message_endpoint,
    server_get_prompts,
    server_get_resources,
    server_get_tools,
    set_prompt_state,
    set_resource_state,
    set_tool_state,
    setup_passthrough_headers,
    sse_endpoint,
    transform_data_with_mappings,
    update_prompt,
    update_resource,
    update_tool,
    validate_security_configuration,
)
from mcpgateway.plugins.framework import PluginError, PromptHookType, ResourceHookType
from mcpgateway.schemas import PromptCreate, PromptUpdate, ResourceCreate, ResourceUpdate, ToolCreate, ToolUpdate
from mcpgateway.services.tool_service import ToolError, ToolNotFoundError
from mcpgateway.transports.streamablehttp_transport import user_context_var
from mcpgateway.validation.jsonrpc import JSONRPCError


def _make_request(
    path: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    cookies: dict | None = None,
    root_path: str = "",
    query_params: dict | None = None,
) -> MagicMock:
    request = MagicMock(spec=Request)
    request.method = method
    request.url = SimpleNamespace(path=path)
    request.scope = {"path": path, "root_path": root_path}
    request.headers = headers or {}
    request.cookies = cookies or {}
    request.query_params = query_params or {}
    return request


def _trusted_internal_mcp_headers(auth_context: dict[str, object], **extra_headers: str) -> dict[str, str]:
    """Build trusted Rust->Python internal MCP headers for unit tests."""
    headers = {
        "x-contextforge-mcp-runtime": "rust",
        "x-contextforge-mcp-runtime-auth": _expected_internal_mcp_runtime_auth_header(),
        "x-contextforge-auth-context": base64.urlsafe_b64encode(orjson.dumps(auth_context)).decode().rstrip("="),
    }
    headers.update(extra_headers)
    return headers


def _import_fresh_main_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    overrides: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
    force_import_error: set[str] | None = None,
):
    """Import mcpgateway/main.py under a unique module name for module-level branch coverage."""

    # First-Party
    from mcpgateway.config import settings as settings_mod

    if overrides:
        for key, value in overrides.items():
            monkeypatch.setattr(settings_mod, key, value, raising=False)

    if env:
        for key, value in env.items():
            monkeypatch.setenv(key, value)

    # Use in-memory session registry to avoid dependence on SQLALCHEMY_AVAILABLE
    # module-level state which can be polluted by other tests that reload session_registry.
    monkeypatch.setattr(settings_mod, "cache_type", "memory", raising=False)

    # Avoid import-time side effects (DB/Redis readiness + bootstrap).
    monkeypatch.setattr("mcpgateway.utils.db_isready.wait_for_db_ready", lambda *_a, **_k: None)

    async def _noop_async(*_a, **_k):  # noqa: ANN001, D401 - internal test helper
        return None

    monkeypatch.setattr("mcpgateway.bootstrap_db.main", _noop_async)
    monkeypatch.setattr("mcpgateway.utils.redis_isready.wait_for_redis_ready", lambda *_a, **_k: None)

    # Keep module-level router/middleware wiring lightweight.
    monkeypatch.setattr("mcpgateway.middleware.db_query_logging.setup_query_logging", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr("mcpgateway.services.metrics.setup_metrics", lambda *_a, **_k: None, raising=False)

    class _PluginService:
        def set_plugin_manager(self, _pm):  # noqa: ANN001
            return None

    monkeypatch.setattr("mcpgateway.services.plugin_service.get_plugin_service", _PluginService, raising=False)

    class _DummyPluginManager:
        def __init__(self, *_a, **_k):  # noqa: ANN001
            self.plugin_count = 0

        async def initialize(self):  # noqa: D401 - trivial
            return None

        async def shutdown(self):  # noqa: D401 - trivial
            return None

        def has_hooks_for(self, server_id):
            return False

    monkeypatch.setattr("mcpgateway.plugins.framework.TenantPluginManager", _DummyPluginManager)

    # Force selected module imports to fail to cover defensive ImportError paths.
    if force_import_error:
        original_import = builtins.__import__

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name in force_import_error:
                raise ImportError(f"Forced ImportError for {name}")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)

    module_name = f"mcpgateway._main_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, Path("mcpgateway/main.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Make module importable during exec_module and ensure it is cleaned up after the test.
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


class TestConditionalPaths:
    """Test conditional code paths to improve coverage."""

    def test_import_uses_rust_mcp_proxy_when_enabled(self, monkeypatch):
        """Module import should swap the mounted /mcp app to the Rust proxy when enabled."""
        module = _import_fresh_main_module(
            monkeypatch,
            overrides={
                "experimental_rust_mcp_runtime_enabled": True,
                "experimental_rust_mcp_session_auth_reuse_enabled": True,
                "experimental_rust_mcp_runtime_url": "http://127.0.0.1:8787",
            },
        )

        assert module.mcp_transport_app.__class__.__name__ == "RustMCPRuntimeProxy"

    def test_import_keeps_python_transport_when_rust_runtime_lacks_session_auth_reuse(self, monkeypatch):
        """Module import should keep public /mcp on Python when Rust session auth reuse is disabled."""
        module = _import_fresh_main_module(
            monkeypatch,
            overrides={
                "experimental_rust_mcp_runtime_enabled": True,
                "experimental_rust_mcp_session_auth_reuse_enabled": False,
                "experimental_rust_mcp_runtime_url": "http://127.0.0.1:8787",
            },
        )

        assert module.mcp_transport_app.__class__.__name__ == "MCPRuntimeHeaderTransportWrapper"

    def test_import_warns_when_rust_artifacts_present_but_runtime_disabled(self, monkeypatch, caplog):
        """A Rust-built image with the runtime flag disabled should warn loudly at import time."""
        caplog.set_level("WARNING")
        module = _import_fresh_main_module(
            monkeypatch,
            overrides={
                "experimental_rust_mcp_runtime_enabled": False,
            },
            env={"CONTEXTFORGE_ENABLE_RUST_BUILD": "true"},
        )

        assert module.mcp_transport_app.__class__.__name__ == "MCPRuntimeHeaderTransportWrapper"
        assert any("python-rust-built-disabled" in rec.message for rec in caplog.records)

    def test_redis_initialization_path(self, test_client, auth_headers):
        """Test Redis initialization path by mocking settings."""
        # Test that the Redis path is covered indirectly through existing functionality
        # Since reloading modules in tests is problematic, we test the path is reachable
        with patch("mcpgateway.main.settings.cache_type", "redis"):
            response = test_client.get("/health", headers=auth_headers)
            assert response.status_code == 200

    def test_event_loop_task_creation(self, test_client, auth_headers):
        """Test event loop task creation path indirectly."""
        # Test the functionality that exercises the loop path
        response = test_client.get("/health", headers=auth_headers)
        assert response.status_code == 200


class TestJwtIdentityExtractor:
    """Test _create_jwt_identity_extractor() factory and returned closure."""

    def test_extractor_returns_sub_claim(self):
        """Valid JWT with sub claim should return sub value."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"sub": "user-123", "email": "user@example.com"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result == "user-123"

    def test_extractor_returns_email_claim_when_no_sub(self):
        """Valid JWT with email but no sub should return email value."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"email": "user@example.com", "user_id": "uid-456"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result == "user@example.com"

    def test_extractor_returns_user_id_claim_when_no_sub_or_email(self):
        """Valid JWT with user_id but no sub/email should return user_id value."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"user_id": "uid-789", "iat": 1234567890}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result == "uid-789"

    def test_extractor_returns_none_for_malformed_token(self):
        """Malformed JWT should return None."""
        extractor = _create_jwt_identity_extractor()
        headers = {"Authorization": "Bearer not-a-valid-jwt"}

        result = extractor(headers)
        assert result is None

    def test_extractor_returns_none_for_non_bearer_header(self):
        """Non-Bearer auth header should return None."""
        extractor = _create_jwt_identity_extractor()
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}

        result = extractor(headers)
        assert result is None

    def test_extractor_returns_none_for_empty_authorization_header(self):
        """Empty Authorization header should return None."""
        extractor = _create_jwt_identity_extractor()
        headers = {"Authorization": ""}

        result = extractor(headers)
        assert result is None

    def test_extractor_returns_none_for_bearer_only_header(self):
        """Header containing only 'Bearer ' with no token should return None."""
        extractor = _create_jwt_identity_extractor()
        headers = {"Authorization": "Bearer "}

        result = extractor(headers)
        assert result is None

    def test_extractor_returns_none_for_missing_authorization_header(self):
        """Missing Authorization header should return None."""
        extractor = _create_jwt_identity_extractor()
        headers = {}

        result = extractor(headers)
        assert result is None

    def test_extractor_returns_none_for_token_with_no_identity_claims(self):
        """JWT with none of the three identity claims should return None."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"iat": 1234567890, "exp": 1234567890, "jti": "random-id"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result is None

    def test_extractor_handles_lowercase_bearer(self):
        """Lowercase 'bearer' prefix should be handled correctly."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"sub": "user-lowercase"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"bearer {token}"}

        result = extractor(headers)
        assert result == "user-lowercase"

    def test_extractor_handles_case_insensitive_header_lookup(self):
        """Extractor should handle both 'authorization' and 'Authorization' keys."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"sub": "user-case"}, "secret", algorithm="HS256")

        # Test lowercase key
        headers_lower = {"authorization": f"Bearer {token}"}
        assert extractor(headers_lower) == "user-case"

        # Test uppercase key
        headers_upper = {"Authorization": f"Bearer {token}"}
        assert extractor(headers_upper) == "user-case"

    def test_extractor_returns_none_on_jwt_decode_exception(self):
        """JWT decode raising an exception should return None and log debug message."""
        # Standard
        from unittest.mock import patch

        extractor = _create_jwt_identity_extractor()

        # Create a valid-looking token that will fail decode
        with patch("jwt.decode", side_effect=Exception("Decode failed")):
            headers = {"Authorization": "Bearer some-token"}
            result = extractor(headers)
            assert result is None

    def test_extractor_prefers_sub_over_email_and_user_id(self):
        """When all three claims present, sub should be preferred."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"sub": "user-sub", "email": "user@example.com", "user_id": "uid-123"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result == "user-sub"

    def test_extractor_prefers_email_over_user_id(self):
        """When email and user_id present but no sub, email should be preferred."""
        # Third-Party
        import jwt

        extractor = _create_jwt_identity_extractor()
        token = jwt.encode({"email": "user@example.com", "user_id": "uid-123"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        result = extractor(headers)
        assert result == "user@example.com"


class TestInternalTrustedMcpTransportBridge:
    """Test the trusted Rust -> Python MCP transport bridge."""

    @pytest.mark.asyncio
    async def test_python_transport_wrapper_sets_runtime_header(self):
        sent = []

        class FakeTransportApp:
            async def handle_streamable_http(self, _scope, _receive, send):
                await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        wrapper = MCPRuntimeHeaderTransportWrapper(FakeTransportApp(), runtime_name="python")

        async def _receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _send(message):
            sent.append(message)

        await wrapper.handle_streamable_http({"type": "http", "method": "POST"}, _receive, _send)

        start = next(message for message in sent if message["type"] == "http.response.start")
        assert (b"x-contextforge-mcp-runtime", b"python") in start["headers"]
        assert (b"x-contextforge-mcp-session-core", b"python") in start["headers"]
        assert (b"x-contextforge-mcp-resume-core", b"python") in start["headers"]
        assert (b"x-contextforge-mcp-live-stream-core", b"python") in start["headers"]
        assert (b"x-contextforge-mcp-affinity-core", b"python") in start["headers"]
        assert (b"x-contextforge-mcp-session-auth-reuse", b"python") in start["headers"]

    @pytest.mark.asyncio
    async def test_python_transport_wrapper_preserves_existing_runtime_headers(self):
        """Existing runtime headers should not be duplicated."""
        sent = []

        class FakeTransportApp:
            async def handle_streamable_http(self, _scope, _receive, send):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (b"x-contextforge-mcp-runtime", b"rust"),
                            (b"x-contextforge-mcp-session-core", b"rust"),
                            (b"x-contextforge-mcp-resume-core", b"rust"),
                            (b"x-contextforge-mcp-live-stream-core", b"rust"),
                            (b"x-contextforge-mcp-affinity-core", b"rust"),
                            (b"x-contextforge-mcp-session-auth-reuse", b"rust"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        wrapper = MCPRuntimeHeaderTransportWrapper(FakeTransportApp(), runtime_name="python")

        async def _receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _send(message):
            sent.append(message)

        await wrapper.handle_streamable_http({"type": "http", "method": "POST"}, _receive, _send)

        start = next(message for message in sent if message["type"] == "http.response.start")
        header_names = [name for name, _value in start["headers"]]
        assert header_names.count(b"x-contextforge-mcp-runtime") == 1
        assert header_names.count(b"x-contextforge-mcp-session-core") == 1
        assert header_names.count(b"x-contextforge-mcp-resume-core") == 1
        assert header_names.count(b"x-contextforge-mcp-live-stream-core") == 1
        assert header_names.count(b"x-contextforge-mcp-affinity-core") == 1
        assert header_names.count(b"x-contextforge-mcp-session-auth-reuse") == 1

    @pytest.mark.asyncio
    async def test_bridge_sets_scope_and_forwarded_auth_context(self):
        observed = {}

        class FakeTransportApp:
            async def handle_streamable_http(self, scope, receive, send):
                observed["path"] = scope["path"]
                observed["modified_path"] = scope["modified_path"]
                observed["user_context"] = user_context_var.get()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 204,
                        "headers": [(b"x-contextforge-mcp-runtime", b"python")],
                    }
                )
                await send({"type": "http.response.body", "body": b"", "more_body": False})

        bridge = InternalTrustedMCPTransportBridge(FakeTransportApp())
        encoded_auth = (
            base64.urlsafe_b64encode(
                orjson.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "auth_method": "jwt",
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "token_use": "session",
                    }
                )
            )
            .decode("ascii")
            .rstrip("=")
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/_internal/mcp/transport",
            "query_string": b"session_id=abc123",
            "headers": [
                (b"x-contextforge-mcp-runtime", b"rust"),
                (b"x-contextforge-mcp-runtime-auth", _expected_internal_mcp_runtime_auth_header().encode("ascii")),
                (b"x-contextforge-auth-context", encoded_auth.encode("ascii")),
                (b"x-contextforge-server-id", b"server-1"),
            ],
            "client": ("127.0.0.1", 5000),
        }

        async def receive():
            return {"type": "http.disconnect"}

        events = []

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http(scope, receive, send)

        assert observed["path"] == "/mcp/"
        assert observed["modified_path"] == "/servers/server-1/mcp"
        assert observed["user_context"]["email"] == "user@example.com"
        assert observed["user_context"]["teams"] == ["team-a"]
        assert observed["user_context"]["auth_method"] == "jwt"
        assert events[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_bridge_marks_rust_validated_sessions_in_user_context(self):
        observed = {}

        class FakeTransportApp:
            async def handle_streamable_http(self, _scope, _receive, send):
                observed["user_context"] = user_context_var.get()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 204,
                        "headers": [(b"x-contextforge-mcp-runtime", b"python")],
                    }
                )
                await send({"type": "http.response.body", "body": b"", "more_body": False})

        bridge = InternalTrustedMCPTransportBridge(FakeTransportApp())
        encoded_auth = (
            base64.urlsafe_b64encode(
                orjson.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                    }
                )
            )
            .decode("ascii")
            .rstrip("=")
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/_internal/mcp/transport",
            "query_string": b"session_id=abc123",
            "headers": [
                (b"x-contextforge-mcp-runtime", b"rust"),
                (b"x-contextforge-mcp-runtime-auth", _expected_internal_mcp_runtime_auth_header().encode("ascii")),
                (b"x-contextforge-auth-context", encoded_auth.encode("ascii")),
                (b"x-contextforge-session-validated", b"rust"),
            ],
            "client": ("127.0.0.1", 5000),
        }

        async def receive():
            return {"type": "http.disconnect"}

        events = []

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http(scope, receive, send)

        assert observed["user_context"]["_rust_session_validated"] is True
        assert events[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_bridge_allows_post_transport_calls(self):
        observed = {}

        class FakeTransportApp:
            async def handle_streamable_http(self, scope, receive, send):
                observed["method"] = scope["method"]
                observed["modified_path"] = scope["modified_path"]
                observed["body"] = await receive()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"x-contextforge-mcp-runtime", b"python")],
                    }
                )
                await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        bridge = InternalTrustedMCPTransportBridge(FakeTransportApp())
        encoded_auth = (
            base64.urlsafe_b64encode(
                orjson.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                    }
                )
            )
            .decode("ascii")
            .rstrip("=")
        )

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/_internal/mcp/transport",
            "query_string": b"",
            "headers": [
                (b"x-contextforge-mcp-runtime", b"rust"),
                (b"x-contextforge-mcp-runtime-auth", _expected_internal_mcp_runtime_auth_header().encode("ascii")),
                (b"x-contextforge-auth-context", encoded_auth.encode("ascii")),
                (b"x-contextforge-server-id", b"server-1"),
            ],
            "client": ("127.0.0.1", 5000),
        }

        async def receive():
            return {"type": "http.request", "body": b'{"jsonrpc":"2.0","id":1}', "more_body": False}

        events = []

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http(scope, receive, send)

        assert observed["method"] == "POST"
        assert observed["modified_path"] == "/servers/server-1/mcp"
        assert observed["body"]["body"] == b'{"jsonrpc":"2.0","id":1}'
        assert events[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_bridge_rejects_missing_internal_auth_context(self):
        bridge = InternalTrustedMCPTransportBridge(AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/_internal/mcp/transport",
            "query_string": b"",
            "headers": [
                (b"x-contextforge-mcp-runtime", b"rust"),
                (b"x-contextforge-mcp-runtime-auth", _expected_internal_mcp_runtime_auth_header().encode("ascii")),
            ],
            "client": ("127.0.0.1", 5000),
        }

        async def receive():
            return {"type": "http.disconnect"}

        events = []

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http(scope, receive, send)

        assert events[0]["status"] == 400

    def test_build_internal_mcp_auth_scope_uses_public_request_shape(self):
        """Synthetic auth scope should preserve the public MCP path and client IP."""
        scope = _build_internal_mcp_auth_scope(
            method="post",
            path="/servers/server-1/mcp",
            query_string="session_id=abc123",
            headers={"Authorization": "Bearer token", "X-Test": "value"},
            client_ip="203.0.113.10",
        )

        assert scope["type"] == "http"
        assert scope["method"] == "POST"
        assert scope["path"] == "/servers/server-1/mcp"
        assert scope["raw_path"] == b"/servers/server-1/mcp"
        assert scope["query_string"] == b"session_id=abc123"
        assert scope["client"] == ("203.0.113.10", 0)
        assert (b"authorization", b"Bearer token") in scope["headers"]
        assert (b"x-test", b"value") in scope["headers"]

    @pytest.mark.asyncio
    async def test_run_internal_mcp_authentication_returns_forwarded_user_context(self, monkeypatch):
        """Successful internal MCP auth should surface the forwarded auth context."""

        async def _fake_streamable_http_auth(_scope, _receive, _send):
            user_context_var.set(
                {
                    "email": "user@example.com",
                    "teams": ["team-a"],
                    "is_authenticated": True,
                }
            )
            return True

        monkeypatch.setattr("mcpgateway.main.settings.email_auth_enabled", False)
        monkeypatch.setattr("mcpgateway.main.streamable_http_auth", _fake_streamable_http_auth)
        monkeypatch.setattr("mcpgateway.main.get_plugin_manager", AsyncMock(return_value=None))

        error_response, auth_context = await _run_internal_mcp_authentication(
            method="POST",
            path="/mcp",
            query_string="",
            headers={"authorization": "Bearer token"},
            client_ip="203.0.113.10",
        )

        assert error_response is None
        assert auth_context["email"] == "user@example.com"
        assert auth_context["teams"] == ["team-a"]
        assert auth_context["is_authenticated"] is True

    @pytest.mark.asyncio
    async def test_run_internal_mcp_authentication_runs_pre_request_hooks(self, monkeypatch):
        """HTTP_PRE_REQUEST plugin hooks should transform headers before auth runs."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.plugins.framework import HttpHookType

        async def _fake_streamable_http_auth(_scope, _receive, _send):
            user_context_var.set({"email": "hook-user@example.com", "teams": [], "is_authenticated": True})
            return True

        monkeypatch.setattr("mcpgateway.main.settings.email_auth_enabled", False)
        monkeypatch.setattr("mcpgateway.main.streamable_http_auth", _fake_streamable_http_auth)

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda ht: ht == HttpHookType.HTTP_PRE_REQUEST)
        monkeypatch.setattr(main_mod, "get_plugin_manager", AsyncMock(return_value=mock_pm))

        transformed_headers = {"authorization": "Bearer exchanged-token", "x-injected": "value"}
        original_headers = {"authorization": "Bearer original-token"}

        mock_run_hooks = AsyncMock(return_value=(transformed_headers, None, None))
        monkeypatch.setattr("mcpgateway.main.run_pre_request_hooks", mock_run_hooks)

        error_response, auth_context = await _run_internal_mcp_authentication(
            method="POST",
            path="/mcp",
            query_string="",
            headers=original_headers,
            client_ip="203.0.113.10",
        )

        assert error_response is None
        assert auth_context["email"] == "hook-user@example.com"
        mock_pm.has_hooks_for.assert_called()
        # Verify run_pre_request_hooks was actually invoked with original headers
        mock_run_hooks.assert_awaited_once()
        assert mock_run_hooks.call_args.kwargs["headers"] == original_headers

    @pytest.mark.asyncio
    async def test_handle_internal_mcp_authenticate_returns_auth_context(self, monkeypatch):
        """Trusted Rust authenticate requests should return the derived auth context."""
        request = MagicMock(spec=Request)
        request.json = AsyncMock(
            return_value={
                "method": "POST",
                "path": "/servers/server-1/mcp",
                "queryString": "session_id=abc123",
                "headers": {"authorization": "Bearer token"},
                "clientIp": "203.0.113.10",
            }
        )

        monkeypatch.setattr("mcpgateway.main._is_trusted_internal_mcp_runtime_request", lambda _request: True)
        monkeypatch.setattr(
            "mcpgateway.main._run_internal_mcp_authentication",
            AsyncMock(
                return_value=(
                    None,
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                    },
                )
            ),
        )

        response = await handle_internal_mcp_authenticate(request)

        assert response.status_code == 200
        assert orjson.loads(response.body)["authContext"]["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_handle_internal_mcp_authenticate_rejects_untrusted_requests(self, monkeypatch):
        """The authenticate bridge should remain trusted-runtime only."""
        request = MagicMock(spec=Request)

        monkeypatch.setattr("mcpgateway.main._is_trusted_internal_mcp_runtime_request", lambda _request: False)

        with pytest.raises(HTTPException) as exc_info:
            await handle_internal_mcp_authenticate(request)

        assert exc_info.value.status_code == 403

    def test_build_internal_mcp_auth_scope_skips_non_string_headers_and_defaults_unknown_client(self):
        """Internal auth scope should ignore malformed headers and avoid loopback defaults."""
        scope = _build_internal_mcp_auth_scope(
            method="get",
            path="/mcp",
            query_string="cursor=1",
            headers={"authorization": "Bearer token", "x-bad": 1, 2: "ignored"},  # type: ignore[dict-item]
            client_ip=None,
        )

        assert scope["client"] == ("unknown", 0)
        assert scope["query_string"] == b"cursor=1"
        assert scope["headers"] == [(b"authorization", b"Bearer token")]

    @pytest.mark.asyncio
    async def test_run_internal_mcp_authentication_captures_forwarded_error_response(self, monkeypatch):
        """Auth failures emitted through ASGI send should be reconstructed exactly."""

        async def _fake_streamable_http_auth(_scope, receive, send):
            await receive()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"detail":"bad token"}'})
            return False

        async def _passthrough_middleware(request, call_next):
            return await call_next(request)

        monkeypatch.setattr("mcpgateway.main.settings.email_auth_enabled", True)
        monkeypatch.setattr("mcpgateway.main.streamable_http_auth", _fake_streamable_http_auth)
        monkeypatch.setattr("mcpgateway.main.token_scoping_middleware", _passthrough_middleware)
        monkeypatch.setattr("mcpgateway.main.get_plugin_manager", AsyncMock(return_value=None))

        error_response, auth_context = await _run_internal_mcp_authentication(
            method="POST",
            path="/mcp",
            query_string="",
            headers={"authorization": "Bearer token"},
            client_ip="203.0.113.10",
        )

        assert auth_context == {}
        assert error_response is not None
        assert error_response.status_code == 401
        assert error_response.headers["content-type"] == "application/json"
        assert error_response.headers["www-authenticate"] == "Bearer"
        assert error_response.body == b'{"detail":"bad token"}'

    @pytest.mark.asyncio
    async def test_run_internal_mcp_authentication_reconstructs_captured_response_when_middleware_returns_none(self, monkeypatch):
        """A middleware chain that returns None should still yield a concrete response."""

        async def _ignored_streamable_http_auth(_scope, _receive, _send):
            return True

        async def _none_middleware(_request, _call_next):
            return None

        monkeypatch.setattr("mcpgateway.main.settings.email_auth_enabled", True)
        monkeypatch.setattr("mcpgateway.main.streamable_http_auth", _ignored_streamable_http_auth)
        monkeypatch.setattr("mcpgateway.main.token_scoping_middleware", _none_middleware)
        monkeypatch.setattr("mcpgateway.main.get_plugin_manager", AsyncMock(return_value=None))

        error_response, auth_context = await _run_internal_mcp_authentication(
            method="GET",
            path="/mcp",
            query_string="",
            headers={},
            client_ip=None,
        )

        assert auth_context == {}
        assert error_response is not None
        assert error_response.status_code == 500

    @pytest.mark.parametrize(
        ("payload", "detail"),
        [
            (["bad"], "Invalid internal MCP authenticate payload"),
            ({"method": "POST", "queryString": "", "headers": {}, "clientIp": "203.0.113.10"}, "requires path"),
            ({"method": "POST", "path": "/mcp", "queryString": [], "headers": {}, "clientIp": "203.0.113.10"}, "queryString must be a string"),
            ({"method": "POST", "path": "/mcp", "queryString": "", "headers": {"authorization": 1}, "clientIp": "203.0.113.10"}, "headers must be a string map"),
            ({"method": "POST", "path": "/mcp", "queryString": "", "headers": {}, "clientIp": 123}, "clientIp must be a string"),
        ],
    )
    @pytest.mark.asyncio
    async def test_handle_internal_mcp_authenticate_validates_payload_shape(self, monkeypatch, payload, detail):
        """Malformed trusted authenticate payloads should fail fast with 400s."""
        request = MagicMock(spec=Request)
        request.json = AsyncMock(return_value=payload)

        monkeypatch.setattr("mcpgateway.main._is_trusted_internal_mcp_runtime_request", lambda _request: True)

        with pytest.raises(HTTPException) as exc_info:
            await handle_internal_mcp_authenticate(request)

        assert exc_info.value.status_code == 400
        assert detail in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_handle_internal_mcp_authenticate_returns_forwarded_error_response(self, monkeypatch):
        """Trusted authenticate requests should pass through auth-layer failure responses."""
        request = MagicMock(spec=Request)
        request.json = AsyncMock(
            return_value={
                "method": "POST",
                "path": "/mcp",
                "queryString": "",
                "headers": {"authorization": "Bearer token"},
                "clientIp": "203.0.113.10",
            }
        )
        expected = FastAPIResponse(content=b"denied", status_code=401)

        monkeypatch.setattr("mcpgateway.main._is_trusted_internal_mcp_runtime_request", lambda _request: True)
        monkeypatch.setattr("mcpgateway.main._run_internal_mcp_authentication", AsyncMock(return_value=(expected, {})))

        response = await handle_internal_mcp_authenticate(request)

        assert response is expected

    @pytest.mark.asyncio
    async def test_bridge_rejects_non_http_scopes(self):
        """Non-HTTP trusted transport requests should return 404."""
        bridge = InternalTrustedMCPTransportBridge(AsyncMock())
        events = []

        async def receive():
            return {"type": "websocket.disconnect"}

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http({"type": "websocket"}, receive, send)

        assert events[0]["status"] == 404

    @pytest.mark.asyncio
    async def test_bridge_rejects_unsupported_methods(self):
        """Unsupported internal transport methods should return 405."""
        bridge = InternalTrustedMCPTransportBridge(AsyncMock())
        encoded_auth = base64.urlsafe_b64encode(orjson.dumps({"email": "user@example.com"})).decode("ascii").rstrip("=")
        events = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            events.append(message)

        await bridge.handle_streamable_http(
            {
                "type": "http",
                "method": "PATCH",
                "headers": [
                    (b"x-contextforge-mcp-runtime", b"rust"),
                    (b"x-contextforge-auth-context", encoded_auth.encode("ascii")),
                ],
                "client": ("127.0.0.1", 5000),
            },
            receive,
            send,
        )

        assert events[0]["status"] == 405


class TestMcpSerialization:
    """Test MCP-specific response shaping helpers."""

    def test_serialize_mcp_tool_definition_strips_api_only_fields(self):
        """MCP tool payloads should exclude API-only metadata like dict-shaped tags."""
        payload = _serialize_mcp_tool_definition(
            {
                "name": "a2a-test-agent",
                "description": "A2A tool",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "outputSchema": {"type": "object"},
                "annotations": {"title": "A2A tool"},
                "tags": [{"id": "ai", "label": "ai"}],
                "url": "https://example.com/agent",
            }
        )

        assert payload == {
            "name": "a2a-test-agent",
            "description": "A2A tool",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "outputSchema": {"type": "object"},
            "annotations": {"title": "A2A tool"},
        }
        assert "tags" not in payload
        assert "url" not in payload

    def test_serialize_mcp_tool_definition_handles_unknown_objects(self):
        """Unknown objects should serialize to an empty MCP payload."""
        assert _serialize_mcp_tool_definition(object()) == {}

    def test_serialize_mcp_tool_definition_normalizes_null_description(self):
        """MCP tool payloads should always expose a string description."""
        payload = _serialize_mcp_tool_definition(
            {
                "name": "test-json-tool",
                "description": None,
                "inputSchema": {"type": "object"},
            }
        )

        assert payload == {
            "name": "test-json-tool",
            "description": "",
            "inputSchema": {"type": "object"},
        }

    def test_serialize_legacy_tool_payloads_preserves_dicts_and_unknowns(self):
        """Legacy payload serialization should preserve dicts and tolerate unknown objects."""
        payloads = _serialize_legacy_tool_payloads([{"id": "tool-1"}, object()])
        assert payloads == [{"id": "tool-1"}, {}]


class TestInternalMcpHelperCoverage:
    """Target helper branches added for trusted Rust MCP forwarding."""

    def test_decode_internal_mcp_auth_context_rejects_non_object_payload(self):
        """Non-object JSON payloads should be rejected."""
        header_value = base64.urlsafe_b64encode(orjson.dumps(["not-an-object"])).decode().rstrip("=")
        with pytest.raises(ValueError, match="must be an object"):
            _decode_internal_mcp_auth_context(header_value)

    def test_build_internal_mcp_forwarded_user_rejects_invalid_auth_context(self):
        """Malformed forwarded auth context should return a 400-style HTTPException."""
        request = MagicMock(spec=Request)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-mcp-runtime-auth": _expected_internal_mcp_runtime_auth_header(),
            "x-contextforge-auth-context": "not-base64",
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        with pytest.raises(HTTPException) as excinfo:
            _build_internal_mcp_forwarded_user(request)

        assert excinfo.value.status_code == 400
        assert "Invalid trusted MCP auth context" in excinfo.value.detail

    def test_build_internal_mcp_forwarded_user_requires_internal_runtime_auth_header(self):
        """Trusted Rust forwarding must include the shared internal-auth header."""
        request = MagicMock(spec=Request)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(orjson.dumps({"email": "user@example.com"})).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        with pytest.raises(HTTPException) as excinfo:
            _build_internal_mcp_forwarded_user(request)

        assert excinfo.value.status_code == 403
        assert "only available to the local Rust runtime" in excinfo.value.detail

    def test_build_internal_mcp_forwarded_user_sets_session_validated_and_token_teams(self):
        """Trusted forwarded auth should copy teams and set the Rust session validation marker."""
        request = MagicMock(spec=Request)
        request.headers = _trusted_internal_mcp_headers(
            {
                "email": "user@example.com",
                "teams": ["team-a"],
                "is_authenticated": True,
                "is_admin": False,
                "permission_is_admin": True,
                "token_use": "session",
            },
            **{"x-contextforge-session-validated": "rust"},
        )
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = SimpleNamespace()

        forwarded = _build_internal_mcp_forwarded_user(request)

        assert forwarded["email"] == "user@example.com"
        assert forwarded["is_admin"] is True
        assert request.state.token_teams == ["team-a"]
        assert getattr(request.state, "_mcp_internal_auth_context")["_rust_session_validated"] is True

    def test_build_internal_mcp_forwarded_user_sets_trace_context(self):
        """Trusted forwarded auth should populate trace context for downstream spans."""
        # First-Party
        from mcpgateway.utils.trace_context import clear_trace_context, get_trace_auth_method, get_trace_team_scope, get_trace_user_email

        clear_trace_context()
        request = MagicMock(spec=Request)
        request.headers = _trusted_internal_mcp_headers(
            {
                "email": "trace@example.com",
                "teams": ["team-x"],
                "is_authenticated": True,
                "is_admin": False,
                "permission_is_admin": False,
                "auth_method": "jwt",
            }
        )
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = SimpleNamespace()

        _build_internal_mcp_forwarded_user(request)

        assert get_trace_user_email() == "trace@example.com"
        assert get_trace_auth_method() == "jwt"
        assert get_trace_team_scope() == "team-x"
        clear_trace_context()

    @pytest.mark.asyncio
    async def test_handle_internal_mcp_tools_call_metric_records_buffered_metrics(self):
        """Trusted Rust metrics writeback should use the buffered Python metric recorder."""
        request = MagicMock(spec=Request)
        request.headers = _trusted_internal_mcp_headers(
            {
                "email": "user@example.com",
                "teams": ["team-a"],
                "is_authenticated": True,
                "is_admin": False,
            },
            **{"x-contextforge-server-id": "server-1"},
        )
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = SimpleNamespace()
        request.body = AsyncMock(
            return_value=orjson.dumps(
                {
                    "toolId": "tool-1",
                    "serverId": "server-1",
                    "durationMs": 250.0,
                    "success": True,
                }
            )
        )
        metrics_buffer = MagicMock()

        with patch(
            "mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service",
            return_value=metrics_buffer,
        ):
            response = await handle_internal_mcp_tools_call_metric(request)

        assert response.status_code == 200
        assert orjson.loads(response.body) == {"status": "ok"}
        metrics_buffer.record_tool_metric_with_duration.assert_called_once_with(
            tool_id="tool-1",
            response_time=0.25,
            success=True,
            error_message=None,
        )
        metrics_buffer.record_server_metric_with_duration.assert_called_once_with(
            server_id="server-1",
            response_time=0.25,
            success=True,
            error_message=None,
        )

    @pytest.mark.asyncio
    async def test_handle_internal_mcp_tools_call_metric_rejects_invalid_payload(self):
        """Tool metric writeback should reject missing identifiers."""
        request = MagicMock(spec=Request)
        request.headers = _trusted_internal_mcp_headers({"email": "user@example.com"})
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = SimpleNamespace()
        request.body = AsyncMock(return_value=orjson.dumps({"durationMs": 25, "success": True}))

        response = await handle_internal_mcp_tools_call_metric(request)

        assert response.status_code == 400
        assert orjson.loads(response.body) == {"detail": "Missing toolId"}

    def test_enforce_internal_mcp_server_scope_returns_when_no_auth_context(self):
        """Missing forwarded auth context should skip server-scope enforcement."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace()

        _enforce_internal_mcp_server_scope(request, "server-1")

    def test_extract_scoped_permissions_prefers_internal_auth_context(self):
        """Internal auth context should drive scoped permissions, with empty values deferring to RBAC."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(_mcp_internal_auth_context={"scoped_permissions": []})

        assert _extract_scoped_permissions(request) is None

        request.state._mcp_internal_auth_context = {"scoped_permissions": ["tools.read", "servers.use"]}
        assert _extract_scoped_permissions(request) == {"tools.read", "servers.use"}

    def test_is_permission_admin_user_handles_object_and_dict_inputs(self):
        """Permission-layer admin helper should handle object, dict, and unknown payloads."""
        assert _is_permission_admin_user(SimpleNamespace(is_admin=True)) is True
        assert _is_permission_admin_user({"permission_is_admin": True}) is True
        assert _is_permission_admin_user({"is_admin": True}) is False
        assert _is_permission_admin_user("not-a-user") is False

    @pytest.mark.asyncio
    async def test_ensure_rpc_permission_short_circuits_admin_system_config_for_permission_admin(self):
        """Permission-layer admins should short-circuit admin.system_config after scope enforcement."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(_jwt_verified_payload=("token", {"scopes": {"permissions": ["admin.system_config"]}}))

        with patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(side_effect=AssertionError("RBAC should be skipped"))):
            await _ensure_rpc_permission({"permission_is_admin": True}, MagicMock(), "admin.system_config", "roots/list", request)


class TestEndpointErrorHandling:
    """Test error handling in various endpoints."""

    def test_tool_invocation_error_handling(self, test_client, auth_headers):
        """Test tool invocation with errors to cover error paths."""
        with patch("mcpgateway.main.tool_service.invoke_tool") as mock_invoke:
            # Test different error scenarios - return error instead of raising
            mock_invoke.return_value = {
                "content": [{"type": "text", "text": "Tool error"}],
                "is_error": True,
            }

            req = {
                "jsonrpc": "2.0",
                "id": "test-id",
                "method": "test_tool",
                "params": {"param": "value"},
            }
            response = test_client.post("/rpc/", json=req, headers=auth_headers)
            # Should handle the error gracefully
            assert response.status_code == 200

    def test_server_endpoints_error_conditions(self, test_client, auth_headers):
        """Test server endpoints with various error conditions."""
        # Test server creation with missing required fields (triggers validation)
        req = {"description": "Missing name"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error appropriately
        assert response.status_code == 422

    def test_resource_endpoints_error_conditions(self, test_client, auth_headers):
        """Test resource endpoints with various error conditions."""
        # Test resource not found scenario
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            # First-Party
            from mcpgateway.services.resource_service import ResourceNotFoundError

            mock_read.side_effect = ResourceNotFoundError("Resource not found")

            response = test_client.get("/resources/test/resource", headers=auth_headers)
            assert response.status_code == 404

    def test_prompt_endpoints_error_conditions(self, test_client, auth_headers):
        """Test prompt endpoints with various error conditions."""
        # Test prompt creation with missing required fields
        req = {"description": "Missing name and template"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)
        assert response.status_code == 422

    def test_gateway_endpoints_error_conditions(self, test_client, auth_headers):
        """Test gateway endpoints with various error conditions."""
        # Test gateway creation with missing required fields
        req = {"description": "Missing name and url"}
        response = test_client.post("/gateways/", json=req, headers=auth_headers)
        assert response.status_code == 422


class TestMiddlewareEdgeCases:
    """Test middleware and authentication edge cases."""

    def test_docs_endpoint_without_auth(self):
        """Test accessing docs without authentication."""
        # Create client without auth override to test real auth
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 401

    def test_openapi_endpoint_without_auth(self):
        """Test accessing OpenAPI spec without authentication."""
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 401

    def test_redoc_endpoint_without_auth(self):
        """Test accessing ReDoc without authentication."""
        client = TestClient(app)
        response = client.get("/redoc")
        assert response.status_code == 401


class TestApplicationStartupPaths:
    """Test application startup conditional paths."""

    @pytest.mark.asyncio
    async def test_startup_without_plugin_manager(self, monkeypatch):
        """Test startup path when plugin_manager is None."""
        # NOTE: This test previously used a single giant parenthesized `with (...)` statement
        # with many context managers. On Python 3.12.3 that reliably triggered a compiler
        # segfault when compiling this file. Keep patches explicit via ExitStack instead.
        # Standard
        from contextlib import ExitStack

        mock_logging_service = MagicMock()
        mock_logging_service.initialize = AsyncMock()
        mock_logging_service.shutdown = AsyncMock()
        mock_logging_service.configure_uvicorn_after_startup = MagicMock()

        # Disable background services to avoid real threads/event loops in unit tests.
        monkeypatch.setattr(settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(settings, "metrics_aggregation_enabled", False)
        monkeypatch.setattr(settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(settings, "sso_enabled", False)

        monkeypatch.setattr(settings, "require_strong_secrets", False, raising=False)
        monkeypatch.setattr(settings, "dev_mode", True, raising=False)

        with ExitStack() as stack:
            stack.enter_context(patch("mcpgateway.main.logging_service", mock_logging_service))
            mock_tool = stack.enter_context(patch("mcpgateway.main.tool_service"))
            mock_resource = stack.enter_context(patch("mcpgateway.main.resource_service"))
            mock_prompt = stack.enter_context(patch("mcpgateway.main.prompt_service"))
            mock_gateway = stack.enter_context(patch("mcpgateway.main.gateway_service"))
            mock_root = stack.enter_context(patch("mcpgateway.main.root_service"))
            mock_completion = stack.enter_context(patch("mcpgateway.main.completion_service"))
            mock_sampling = stack.enter_context(patch("mcpgateway.main.sampling_handler"))
            mock_cache = stack.enter_context(patch("mcpgateway.main.resource_cache"))
            mock_session = stack.enter_context(patch("mcpgateway.main.streamable_http_session"))
            mock_session_registry = stack.enter_context(patch("mcpgateway.main.session_registry"))
            mock_export = stack.enter_context(patch("mcpgateway.main.export_service"))
            mock_import = stack.enter_context(patch("mcpgateway.main.import_service"))
            mock_a2a = stack.enter_context(patch("mcpgateway.main.a2a_service"))
            stack.enter_context(patch("mcpgateway.main.refresh_slugs_on_startup"))
            mock_get_redis = stack.enter_context(patch("mcpgateway.main.get_redis_client", new_callable=AsyncMock))
            mock_close_redis = stack.enter_context(patch("mcpgateway.main.close_redis_client", new_callable=AsyncMock))
            mock_init_llmchat = stack.enter_context(patch("mcpgateway.routers.llmchat_router.init_redis", new_callable=AsyncMock))
            mock_shared_http = stack.enter_context(patch("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", new_callable=AsyncMock))
            mock_shared_http_shutdown = stack.enter_context(patch("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", new_callable=AsyncMock))

            # Setup all mocks
            services = [mock_tool, mock_resource, mock_prompt, mock_gateway, mock_root, mock_completion, mock_sampling, mock_cache, mock_session, mock_session_registry, mock_export, mock_import]
            for service in services:
                service.initialize = AsyncMock()
                service.shutdown = AsyncMock()
            mock_a2a.initialize = AsyncMock()
            mock_a2a.shutdown = AsyncMock()

            # Setup Redis mocks
            mock_get_redis.return_value = None
            mock_close_redis.return_value = None
            mock_init_llmchat.return_value = None
            mock_shared_http.return_value = None
            mock_shared_http_shutdown.return_value = None

            # Test lifespan without plugin manager
            # First-Party
            from mcpgateway.main import lifespan

            async with lifespan(app):
                pass

            # Verify initialization happened without plugin manager
            mock_logging_service.initialize.assert_called_once()
            for service in services:
                service.initialize.assert_called_once()
                service.shutdown.assert_called_once()


class TestJsonPathHelpers:
    """Cover JSONPath helpers in main.py."""

    def test_jsonpath_modifier_invalid_expression(self):
        with pytest.raises(HTTPException) as excinfo:
            jsonpath_modifier({"a": 1}, "$[")
        assert "Invalid main JSONPath" in excinfo.value.detail

    def test_jsonpath_modifier_execution_error(self):
        class DummyPath:
            def find(self, _data):
                raise Exception("boom")

        with patch("mcpgateway.main._parse_jsonpath", return_value=DummyPath()):
            with pytest.raises(HTTPException) as excinfo:
                jsonpath_modifier({"a": 1}, "$.a")
        assert "Error executing main JSONPath" in excinfo.value.detail

    def test_transform_data_with_mappings_multi_and_empty(self):
        data = [{"items": [{"id": 1}, {"id": 2}]}, {"items": []}]
        result = transform_data_with_mappings(data, {"ids": "$.items[*].id"})
        assert result[0]["ids"] == [1, 2]
        assert result[1]["ids"] is None

    def test_transform_data_with_mappings_invalid_mapping(self):
        with patch("mcpgateway.main._parse_jsonpath", side_effect=Exception("bad mapping")):
            with pytest.raises(HTTPException) as excinfo:
                transform_data_with_mappings([{"a": 1}], {"x": "$.a"})
        assert "Invalid mapping JSONPath" in excinfo.value.detail

    def test_jsonpath_modifier_debug_logging_with_list(self, monkeypatch):
        """Test jsonpath_modifier debug logging with list data (lines 789-790)."""
        # Standard
        import logging

        # Mock logger to ensure debug is enabled
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        monkeypatch.setattr("mcpgateway.main.logger", mock_logger)

        # Call jsonpath_modifier with list data to trigger the debug logging
        data = [{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}]
        jsonpath_modifier(data, "$.*.id", None)

        # Verify debug logging was called
        mock_logger.isEnabledFor.assert_called_with(logging.DEBUG)
        mock_logger.debug.assert_called()
        # Verify the debug message contains expected parts
        debug_call_args = str(mock_logger.debug.call_args)
        assert "jsonpath_modifier" in debug_call_args
        assert "data_length=2" in debug_call_args or "data_type=list" in debug_call_args


class TestParseApijsonpath:
    """Test _parse_apijsonpath function for complete coverage."""

    def test_parse_apijsonpath_none_input(self):
        """Test that None input returns None (line 721)."""
        result = _parse_apijsonpath(None)
        assert result is None

    def test_parse_apijsonpath_with_valid_string(self):
        """Test successful parsing of valid JSON string (line 729)."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        json_string = '{"jsonpath": "$.name", "mapping": null}'
        result = _parse_apijsonpath(json_string)

        assert result is not None
        assert isinstance(result, JsonPathModifier)
        assert result.jsonpath == "$.name"
        assert result.mapping is None

    def test_parse_apijsonpath_with_valid_string_and_mapping(self):
        """Test successful parsing with mapping to ensure line 729 coverage."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        json_string = '{"jsonpath": "$.items[*]", "mapping": {"id": "$.id", "name": "$.name"}}'
        result = _parse_apijsonpath(json_string)

        assert result is not None
        assert isinstance(result, JsonPathModifier)
        assert result.jsonpath == "$.items[*]"
        assert result.mapping == {"id": "$.id", "name": "$.name"}

    def test_parse_apijsonpath_empty_jsonpath_string(self):
        """Test empty jsonpath in string raises error (lines 728, 732)."""
        json_string = '{"jsonpath": "   ", "mapping": null}'

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(json_string)

        assert excinfo.value.status_code == 400
        assert "JSONPath expression cannot be empty" in excinfo.value.detail

    def test_parse_apijsonpath_invalid_json_debug_mode(self, monkeypatch):
        """Test invalid JSON in DEBUG mode (lines 733-736)."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "DEBUG")

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath('{"invalid json}')

        assert excinfo.value.status_code == 400
        assert "Invalid apijsonpath JSON:" in excinfo.value.detail

    def test_parse_apijsonpath_invalid_json_non_debug_mode(self, monkeypatch):
        """Test invalid JSON in non-DEBUG mode (lines 733-736)."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "INFO")

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath('{"invalid json}')

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Invalid apijsonpath format"

    def test_parse_apijsonpath_jsonpathmodifier_valid(self):
        """Test valid JsonPathModifier instance (lines 745-749)."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        modifier = JsonPathModifier(jsonpath="$.test", mapping=None)
        result = _parse_apijsonpath(modifier)

        assert result is modifier
        assert result.jsonpath == "$.test"

    def test_parse_apijsonpath_jsonpathmodifier_empty_jsonpath(self):
        """Test JsonPathModifier with empty jsonpath (lines 747-748)."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        modifier = JsonPathModifier(jsonpath="  ", mapping=None)

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(modifier)

        assert excinfo.value.status_code == 400
        assert "JSONPath expression cannot be empty" in excinfo.value.detail

    def test_parse_apijsonpath_validation_error_extra_fields(self, monkeypatch):
        """Test that extra fields in JSON string trigger ValidationError path."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "INFO")

        # Valid JSON but with extra field rejected by extra="forbid"
        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath('{"jsonpath": "$.name", "unexpected_field": "value"}')

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Invalid apijsonpath structure"

    def test_parse_apijsonpath_validation_error_debug_mode(self, monkeypatch):
        """Test ValidationError path shows details in DEBUG mode."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "DEBUG")

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath('{"jsonpath": "$.name", "unknown": 123}')

        assert excinfo.value.status_code == 400
        assert "Invalid apijsonpath structure:" in excinfo.value.detail

    def test_parse_apijsonpath_invalid_type_debug_mode(self, monkeypatch):
        """Test invalid type in DEBUG mode (lines 753-754)."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "DEBUG")

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(12345)  # Invalid type (int)

        assert excinfo.value.status_code == 400
        assert "Invalid apijsonpath type: got int" in excinfo.value.detail

    def test_parse_apijsonpath_invalid_type_non_debug_mode(self, monkeypatch):
        """Test invalid type in non-DEBUG mode (lines 753-754)."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "INFO")

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(["list", "input"])  # Invalid type (list)

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Invalid apijsonpath type"

    def test_parse_apijsonpath_unexpected_exception_logging(self, monkeypatch):
        """Test unexpected exception handling with logging (lines 741-744)."""
        # Standard

        # Mock json.loads to raise an unexpected exception (not ValueError/ValidationError/HTTPException)
        def mock_json_loads(s):
            raise RuntimeError("Unexpected error during parsing")

        # Capture log calls
        log_calls = []

        def mock_logger_error(msg, *args, **kwargs):
            log_calls.append((msg, kwargs))

        monkeypatch.setattr("mcpgateway.main.json.loads", mock_json_loads)
        monkeypatch.setattr("mcpgateway.main.logger.error", mock_logger_error)

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath('{"jsonpath": "$.test"}')

        assert excinfo.value.status_code == 500
        assert excinfo.value.detail == "Failed to parse apijsonpath"
        # Verify logging was called
        assert len(log_calls) > 0
        assert "Unexpected error parsing apijsonpath" in log_calls[0][0]
        assert log_calls[0][1].get("exc_info") is True

    def test_parse_apijsonpath_invalid_jsonpath_syntax_string(self, monkeypatch):
        """Test invalid JSONPath syntax in string input triggers early validation."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "DEBUG")

        # Invalid JSONPath syntax
        json_string = '{"jsonpath": "$..[**]", "mapping": null}'

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(json_string)

        assert excinfo.value.status_code == 400
        assert "Invalid JSONPath syntax:" in excinfo.value.detail

    def test_parse_apijsonpath_invalid_jsonpath_syntax_string_non_debug(self, monkeypatch):
        """Test invalid JSONPath syntax in string input (non-DEBUG mode)."""
        monkeypatch.setattr("mcpgateway.main.settings.log_level", "INFO")

        # Invalid JSONPath syntax
        json_string = '{"jsonpath": "$..[**]", "mapping": null}'

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(json_string)

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Invalid JSONPath expression"

    def test_parse_apijsonpath_invalid_jsonpath_syntax_modifier(self, monkeypatch):
        """Test invalid JSONPath syntax in JsonPathModifier instance."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        monkeypatch.setattr("mcpgateway.main.settings.log_level", "DEBUG")

        # Invalid JSONPath syntax
        modifier = JsonPathModifier(jsonpath="$..[**]", mapping=None)

        with pytest.raises(HTTPException) as excinfo:
            _parse_apijsonpath(modifier)

        assert excinfo.value.status_code == 400
        assert "Invalid JSONPath syntax:" in excinfo.value.detail

    def test_parse_apijsonpath_valid_jsonpath_syntax_validation(self):
        """Test that valid JSONPath expressions pass early syntax validation."""
        # First-Party
        from mcpgateway.schemas import JsonPathModifier

        # Valid JSONPath expressions that should pass validation
        valid_paths = [
            '{"jsonpath": "$.name", "mapping": null}',
            '{"jsonpath": "$[*]", "mapping": null}',
            '{"jsonpath": "$.items[0].id", "mapping": null}',
        ]

        for json_string in valid_paths:
            result = _parse_apijsonpath(json_string)
            assert result is not None
            assert isinstance(result, JsonPathModifier)


class TestApijsonpathHTTP:
    """End-to-end HTTP tests for the apijsonpath query parameter via TestClient."""

    def test_list_tools_apijsonpath_via_http(self, test_client, auth_headers):
        """GET /tools?apijsonpath=... should return 200 with JSONPath applied."""
        resp = test_client.get("/tools/", headers=auth_headers, params={"apijsonpath": '{"jsonpath":"$[*].name"}'})
        assert resp.status_code == 200
        data = resp.json()
        # jsonpath_modifier returns a list of matched values (may be empty)
        assert isinstance(data, list)

    def test_list_tools_apijsonpath_invalid_json_via_http(self, test_client, auth_headers):
        """GET /tools?apijsonpath={bad should return 400."""
        resp = test_client.get("/tools/", headers=auth_headers, params={"apijsonpath": "{bad json"})
        assert resp.status_code == 400

    def test_list_tools_apijsonpath_pagination_via_http(self, test_client, auth_headers):
        """GET /tools?apijsonpath=...&include_pagination=true should use nextCursor key."""
        resp = test_client.get(
            "/tools/",
            headers=auth_headers,
            params={"apijsonpath": '{"jsonpath":"$[*].name"}', "include_pagination": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        # Must be camelCase to match CursorPaginatedToolsResponse alias contract
        assert "nextCursor" in data


class TestDocsAuthMiddleware:
    """Cover DocsAuthMiddleware branches."""

    @pytest.mark.asyncio
    async def test_docs_auth_rejects_invalid_token(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", headers={"Authorization": "Bearer bad"})
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_options_passthrough(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", method="OPTIONS")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_unprotected_path(self):
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/api/tools")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_normalizes_prefixed_scope_path(self):
        """When proxy forwards full path, scope_path includes root_path prefix and must be stripped."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/docs", root_path="/qa/gateway")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        # After normalization the path matches /docs, so auth is enforced
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_prefixed_unprotected_path_passes_through(self):
        """An unprotected path with root_path prefix must still pass through after normalization."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/health", root_path="/qa/gateway")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_root_path_slash_does_not_break_paths(self):
        """root_path of '/' must be ignored to avoid stripping leading slash from every path."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/docs", root_path="/")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        # /docs is still recognized as protected (leading slash not stripped)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_docs_auth_partial_prefix_not_stripped(self):
        """root_path='/app' must not strip from '/application/docs' (partial segment match)."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/application/docs", root_path="/app")
        call_next = AsyncMock(return_value="ok")

        response = await middleware.dispatch(request, call_next)

        # "/application/docs" is not a protected path, so it passes through
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_docs_auth_trailing_slash_root_path(self):
        """root_path with trailing slash must still strip prefix correctly."""
        middleware = DocsAuthMiddleware(None)
        request = _make_request("/qa/gateway/docs", root_path="/qa/gateway/")
        call_next = AsyncMock(return_value=StarletteResponse("ok"))

        with patch("mcpgateway.main.require_docs_auth_override", side_effect=HTTPException(status_code=401, detail="nope")):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401


class TestAdminAuthMiddleware:
    """Cover AdminAuthMiddleware branches."""

    @pytest.mark.asyncio
    async def test_admin_auth_bypasses_when_auth_disabled(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", False)
        response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_invalid_jwt_returns_401(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={})):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_revoked_token_redirects(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token", "accept": "text/html"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "jti": "abc"})),
            patch("mcpgateway.main._check_token_revoked_sync", return_value=True),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 302
        assert "token_revoked" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_admin_auth_htmx_request_returns_hx_redirect(self, monkeypatch):
        """HTMX partial requests must receive HX-Redirect header instead of 302 redirect (issue #2874)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token", "accept": "text/html", "hx-request": "true"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "jti": "abc"})),
            patch("mcpgateway.main._check_token_revoked_sync", return_value=True),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert "/admin/login" in response.headers.get("hx-redirect", "")
        assert "token_revoked" in response.headers.get("hx-redirect", "")

    @pytest.mark.asyncio
    async def test_admin_auth_htmx_no_auth_returns_hx_redirect(self, monkeypatch):
        """HTMX requests without valid auth must get HX-Redirect, not 302 (issue #2874)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"hx-request": "true"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={})):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert "/admin/login" in response.headers.get("hx-redirect", "")

    @pytest.mark.asyncio
    async def test_admin_auth_api_token_expired(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"expired": True}),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_proxy_user_allows_access(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        proxy_header = settings.proxy_user_header
        request = _make_request("/admin/tools", headers={proxy_header: "proxy@example.com"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "trust_proxy_auth", True)
        monkeypatch.setattr(settings, "trust_proxy_auth_dangerously", True)
        monkeypatch.setattr(settings, "mcp_client_auth_enabled", False)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value=None),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_platform_admin_bootstrap(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "platform_admin_email", "admin@example.com")

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "admin@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_non_admin_denied(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        # Mock PermissionService to return False for non-admin user without admin permissions
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=False)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "teams": ["team-1"]})),
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_auth_public_only_admin_token_denied(self, monkeypatch):
        """teams=[] tokens are public-only and must not pass admin middleware."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token", "accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "admin@example.com", "is_admin": True, "teams": []})):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_auth_explicit_null_teams_admin_bypass_allowed(self, monkeypatch):
        """teams=null + is_admin=true should preserve unrestricted admin middleware behavior."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "admin@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_session_token_resolves_teams_from_db(self, monkeypatch):
        """Session tokens should resolve team scope via DB helper before admin path checks."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", headers={"Authorization": "Bearer token"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "admin@example.com", "token_use": "session", "is_admin": True}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=None)) as mock_resolve_teams,
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        mock_resolve_teams.assert_awaited_once_with(
            {"sub": "admin@example.com", "token_use": "session", "is_admin": True},
            "admin@example.com",
            {"is_admin": True},
        )
        call_next.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/admin/login",
            "/admin/logout",
            "/admin/forgot-password",
            "/admin/reset-password/token-123",
            "/admin/static/app.css",
        ],
    )
    async def test_admin_auth_exempt_paths_call_next_when_auth_required(self, monkeypatch, path):
        """Cover exempt path short-circuit for public admin routes and static assets."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(path, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/qa/gateway/admin/login",
            "/qa/gateway/admin/forgot-password",
            "/qa/gateway/admin/reset-password/token-123",
        ],
    )
    async def test_admin_auth_exempt_path_with_prefixed_scope_path(self, monkeypatch, path):
        """When proxy forwards full paths, exempt admin auth routes must remain public."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(path, root_path="/qa/gateway")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_root_path_slash_does_not_break_paths(self, monkeypatch):
        """root_path of '/' must be ignored so /admin routes are still detected."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/login", root_path="/")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        # /admin/login is exempt; leading slash must not be stripped
        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_prefixed_non_exempt_path_enforces_auth(self, monkeypatch):
        """A non-exempt prefixed admin path must be detected as admin and require auth."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/qa/gateway/admin/tools", root_path="/qa/gateway", headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        # No credentials: should redirect to login (302), not pass through
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_auth_trailing_slash_root_path(self, monkeypatch):
        """root_path with trailing slash must still normalize correctly."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/qa/gateway/admin/tools", root_path="/qa/gateway/", headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_auth_cookie_token_revocation_check_failure_still_allows(self, monkeypatch):
        """Cover cookie token extraction + revocation check failure path."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "user@example.com", "jti": "jti-1", "is_admin": True, "teams": None}),
            ),
            patch("mcpgateway.main._check_token_revoked_sync", side_effect=RuntimeError("revocation backend down")),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_auth_api_token_revoked_and_success(self, monkeypatch):
        """Cover API token revoked and valid branches (when JWT validation fails)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        with (
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"revoked": True}),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(side_effect=Exception("bad"))),
            patch("mcpgateway.main._lookup_api_token_sync", return_value={"user_email": "admin@example.com"}),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response == "ok"

    @pytest.mark.asyncio
    async def test_admin_auth_user_not_found_returns_401(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_auth_user_not_found_browser_redirects_to_login(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "text/html"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)
        monkeypatch.setattr(settings, "require_user_in_db", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_admin_auth_disabled_user_returns_403(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=False, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_auth_http_exception_and_general_exception_paths(self, monkeypatch):
        middleware = AdminAuthMiddleware(None)
        request = _make_request("/admin/tools", cookies={"jwt_token": "token"}, headers={"accept": "application/json"})
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(side_effect=HTTPException(status_code=401, detail="boom"))

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401

        # Generic exception (e.g., permission check failure) -> 500 Authentication error
        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(side_effect=RuntimeError("perm backend down"))

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "user@example.com", "is_admin": True, "teams": None})),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_admin_auth_team_scoped_request_passes_with_team_role(self, monkeypatch):
        """User with only team-scoped admin.dashboard should pass when request has valid team_id."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "a1b2c3d4e5f6789012345678abcdef01"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01", "fedcba9876543210fedcba9876543210"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # Verify has_admin_permission was called with the validated team_id
        mock_permission_service.has_admin_permission.assert_awaited_once_with(
            "dev@example.com", team_id="a1b2c3d4e5f6789012345678abcdef01", token_teams=["a1b2c3d4e5f6789012345678abcdef01", "fedcba9876543210fedcba9876543210"]
        )

    @pytest.mark.asyncio
    async def test_admin_auth_team_scoped_request_ignores_nonmember_team_id(self, monkeypatch):
        """team_id not in user's teams should be ignored (falls back to global check)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "00000000000000000000000000000099"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        # Return False to simulate no global admin permission either
        mock_permission_service.has_admin_permission = AsyncMock(return_value=False)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403
        # team_id was not in token_teams, so should pass None
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id=None, token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_no_team_id_uses_global_check(self, monkeypatch):
        """Request without team_id should check global permissions only (original behavior)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # No team_id in request, so should pass None
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id=None, token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_empty_string_team_id_ignored(self, monkeypatch):
        """Empty string team_id in query params should be treated as absent."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": ""},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # Empty string is falsy, so team_id should be None
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id=None, token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_admin_bypass_ignores_query_team_id(self, monkeypatch):
        """Admin bypass (token_teams=None) should ignore team_id in query and pass None."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "a1b2c3d4e5f6789012345678abcdef01"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=True)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "admin@example.com", "token_use": "session", "is_admin": True}),
            ),
            # token_teams=None signals admin bypass
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # token_teams is None (admin bypass), so validated_team_id should be None
        mock_permission_service.has_admin_permission.assert_awaited_once_with("admin@example.com", team_id=None, token_teams=None)

    @pytest.mark.asyncio
    async def test_admin_auth_hyphenated_uuid_normalized_to_hex(self, monkeypatch):
        """Hyphenated UUID in query should be normalized to hex and match token_teams."""
        middleware = AdminAuthMiddleware(None)
        # Hyphenated form of the same UUID
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "a1b2c3d4-e5f6-7890-1234-5678abcdef01"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            # DB stores hex format
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # Hyphenated UUID should be normalized to hex and match token_teams
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id="a1b2c3d4e5f6789012345678abcdef01", token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_garbage_team_id_treated_as_absent(self, monkeypatch):
        """Non-UUID team_id in query params should be treated as absent (not a valid UUID)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "not-a-valid-uuid"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # Invalid UUID is discarded, falls back to global check
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id=None, token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_repeated_team_id_uses_last_value(self, monkeypatch):
        """Repeated team_id query keys: .get() returns last value; validate against token_teams."""
        # Third-Party
        from starlette.datastructures import QueryParams

        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
        )
        # Simulate repeated keys — .get() returns the last value
        request.query_params = QueryParams("team_id=00000000000000000000000000000099" "&team_id=a1b2c3d4e5f6789012345678abcdef01")
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                new=AsyncMock(return_value={"sub": "dev@example.com", "token_use": "session", "user": {"is_admin": False}}),
            ),
            patch("mcpgateway.main.resolve_session_teams", new=AsyncMock(return_value=["a1b2c3d4e5f6789012345678abcdef01"])),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # .get() returns last value (hex UUID), which IS in token_teams
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id="a1b2c3d4e5f6789012345678abcdef01", token_teams=["a1b2c3d4e5f6789012345678abcdef01"])

    @pytest.mark.asyncio
    async def test_admin_auth_non_uuid_team_id_matches_legacy_token_teams(self, monkeypatch):
        """Non-UUID team_id should still match when token_teams contains the same non-UUID string (legacy/CLI tokens)."""
        middleware = AdminAuthMiddleware(None)
        request = _make_request(
            "/admin/tools",
            headers={"Authorization": "Bearer token"},
            query_params={"team_id": "team-slug-123"},
        )
        call_next = AsyncMock(return_value="ok")

        monkeypatch.setattr(settings, "auth_required", True)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        mock_user = SimpleNamespace(is_active=True, is_admin=False)
        mock_auth_service = MagicMock()
        mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
        mock_permission_service = MagicMock()
        mock_permission_service.has_admin_permission = AsyncMock(return_value=True)

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch(
                "mcpgateway.main.verify_jwt_token",
                # Non-session token (no token_use="session") uses normalize_token_teams
                new=AsyncMock(return_value={"sub": "dev@example.com", "teams": ["team-slug-123"], "user": {"is_admin": False}}),
            ),
            # normalize_token_teams returns the raw strings from the JWT
            patch("mcpgateway.main.normalize_token_teams", return_value=["team-slug-123"]),
            patch("mcpgateway.main.EmailAuthService", return_value=mock_auth_service),
            patch("mcpgateway.main.PermissionService", return_value=mock_permission_service),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response == "ok"
        # Non-UUID kept as-is, matches token_teams
        mock_permission_service.has_admin_permission.assert_awaited_once_with("dev@example.com", team_id="team-slug-123", token_teams=["team-slug-123"])


class TestMCPPathRewriteMiddleware:
    """Cover MCPPathRewriteMiddleware branches."""

    @pytest.mark.asyncio
    async def test_rewrite_mcp_path(self):
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", new=AsyncMock(return_value=True)):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/mcp/"
        app_mock.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_rewrite_auth_failure(self):
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", new=AsyncMock(return_value=False)):
            await middleware._call_streamable_http(scope, receive, send)

        app_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_path_short_circuits(self):
        app_mock = AsyncMock()
        response = StarletteResponse("ok")
        dispatch = AsyncMock(return_value=response)
        middleware = MCPPathRewriteMiddleware(app_mock, dispatch=dispatch)
        scope = {"type": "http", "path": "/servers/123/mcp", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        dispatch.assert_called_once()
        app_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_rewrite_rejects_empty_server_id_segment(self):
        """Middleware returns 404 for /servers//mcp (empty server ID)."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/servers//mcp", "headers": []}
        receive = AsyncMock()
        sent = []

        async def send(msg):
            sent.append(msg)

        with patch("mcpgateway.main.streamable_http_auth", new=AsyncMock(return_value=True)):
            await middleware._call_streamable_http(scope, receive, send)

        app_mock.assert_not_called()
        # ORJSONResponse sends http.response.start + http.response.body
        assert any(m.get("status") == 404 for m in sent if m.get("type") == "http.response.start")

    @pytest.mark.asyncio
    async def test_rewrite_servers_mcp_with_root_path_in_scope(self):
        """Documented pattern works when root_path is set in scope."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/gateway/servers/123/mcp",
            "root_path": "/gateway",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/gateway/mcp/"  # Rewritten with prefix preserved
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_rewrite_servers_mcp_with_multilevel_prefix(self):
        """Handle complex multi-level prefixes."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/dev/mcp-gateway/service/gateway/servers/123/mcp",
            "root_path": "/dev/mcp-gateway/service/gateway",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/dev/mcp-gateway/service/gateway/mcp/"
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_rewrite_servers_mcp_with_prefix_in_path_no_scope_root(self):
        """Handle prefix in path when scope['root_path'] is empty but APP_ROOT_PATH is set."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/gateway/servers/123/mcp",
            "root_path": "",  # Not set in scope
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch('mcpgateway.config.settings.app_root_path', '/gateway'):
            with patch("mcpgateway.main.streamable_http_auth", return_value=True):
                await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/gateway/mcp/"
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_workaround_mcp_servers_passes_through(self):
        """Undocumented workaround /mcp/servers/{id} passes through without rewrite."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {"type": "http", "path": "/mcp/servers/123", "headers": []}
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/mcp/servers/123"  # NOT rewritten
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_workaround_mcp_servers_with_prefix(self):
        """Workaround /mcp/servers/{id} with prefix passes through."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/gateway/mcp/servers/123",
            "root_path": "/gateway",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        assert scope["path"] == "/gateway/mcp/servers/123"  # NOT rewritten
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_security_arbitrary_prefix_not_rewritten(self):
        """PR #3892 security: Arbitrary paths ending with /mcp are NOT rewritten."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/arbitrary/prefix/mcp",
            "root_path": "",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        # Should pass through WITHOUT rewrite (security check)
        assert scope["path"] == "/arbitrary/prefix/mcp"
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_security_arbitrary_prefix_with_root_path(self):
        """Security: Arbitrary paths rejected even with root_path."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/gateway/arbitrary/prefix/mcp",
            "root_path": "/gateway",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, send)

        # After stripping root_path, path is "/arbitrary/prefix/mcp"
        # Should pass through WITHOUT rewrite
        assert scope["path"] == "/gateway/arbitrary/prefix/mcp"
        app_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_security_empty_server_id_with_prefix_rejected(self):
        """Security: Empty server ID with prefix is rejected."""
        app_mock = AsyncMock()
        middleware = MCPPathRewriteMiddleware(app_mock)
        scope = {
            "type": "http",
            "path": "/gateway/servers//mcp",
            "root_path": "/gateway",
            "headers": []
        }
        receive, send = AsyncMock(), AsyncMock()
        sent = []

        async def mock_send(msg):
            sent.append(msg)

        with patch("mcpgateway.main.streamable_http_auth", return_value=True):
            await middleware._call_streamable_http(scope, receive, mock_send)

        app_mock.assert_not_called()
        # ORJSONResponse sends http.response.start + http.response.body
        assert any(m.get("status") == 404 for m in sent if m.get("type") == "http.response.start")


class TestServerEndpointCoverage:
    """Exercise server endpoints and SSE coverage."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_success(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}
        db = MagicMock()

        # First-Party
        from mcpgateway.services.permission_service import PermissionService

        monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))

        transport = MagicMock()
        transport.session_id = "session-1"
        transport.connect = AsyncMock()
        transport.create_sse_response = AsyncMock(return_value=StarletteResponse("ok"))

        monkeypatch.setattr("mcpgateway.main.update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr("mcpgateway.main._get_token_teams_from_request", lambda _req: None)
        monkeypatch.setattr("mcpgateway.main.SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr("mcpgateway.main.server_service.get_server", AsyncMock(return_value=SimpleNamespace(id="server-1")))
        monkeypatch.setattr("mcpgateway.main.session_registry.add_session", AsyncMock())
        monkeypatch.setattr("mcpgateway.main.session_registry.respond", AsyncMock(return_value=None))
        monkeypatch.setattr("mcpgateway.main.session_registry.register_respond_task", MagicMock())
        monkeypatch.setattr("mcpgateway.main.session_registry.remove_session", AsyncMock())

        response = await sse_endpoint(request, "server-1", db=db, user={"email": "user@example.com", "is_admin": True, "db": MagicMock()})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sse_endpoint_missing_server_returns_404(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}
        db = MagicMock()

        # First-Party
        from mcpgateway.services.server_service import ServerNotFoundError

        monkeypatch.setattr("mcpgateway.main.server_service.get_server", AsyncMock(side_effect=ServerNotFoundError("missing")))

        with pytest.raises(HTTPException) as excinfo:
            await sse_endpoint(request, "missing", db=db, user={"email": "user@example.com"})

        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_sse_endpoint_re_raises_http_exception(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}
        db = MagicMock()

        monkeypatch.setattr(
            "mcpgateway.main.server_service.get_server",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="denied")),
        )

        with pytest.raises(HTTPException) as excinfo:
            await sse_endpoint(request, "server-1", db=db, user={"email": "user@example.com"})

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "denied"

    @pytest.mark.asyncio
    async def test_get_server_denies_when_scope_enforcement_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        db = MagicMock()

        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=SimpleNamespace(id="server-1")))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_server("server-1", request=request, db=db, user={"email": "user@example.com"})

        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_tool_denies_when_scope_enforcement_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        db = MagicMock()
        tool = SimpleNamespace(to_dict=lambda **_kwargs: {"id": "tool-1"})

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=tool))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool("tool-1", request=request, db=db, user={"email": "user@example.com"}, apijsonpath=None)

        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_gateway_denies_when_scope_enforcement_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        db = MagicMock()

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(return_value=SimpleNamespace(id="gw-1")))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_gateway("gw-1", request=request, db=db, user={"email": "user@example.com"})

        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_read_resource_denies_when_scope_enforcement_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)
        db = MagicMock()

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value={"type": "text"}))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.read_resource("res-1", request=request, db=db, user={"email": "user@example.com", "is_admin": False})

        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_server_get_tools_admin_bypass(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        list_tools = AsyncMock(return_value=[tool])
        monkeypatch.setattr("mcpgateway.main.tool_service.list_server_tools", list_tools)

        result = await server_get_tools(request, "server-1", include_metrics=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "tool-1"}]
        list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_get_resources_public_scope(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        list_resources = AsyncMock(return_value=[resource])
        monkeypatch.setattr("mcpgateway.main.resource_service.list_server_resources", list_resources)

        result = await server_get_resources(request, "server-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "res-1"}]
        list_resources.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_get_prompts_public_scope(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        list_prompts = AsyncMock(return_value=[prompt])
        monkeypatch.setattr("mcpgateway.main.prompt_service.list_server_prompts", list_prompts)

        result = await server_get_prompts(request, "server-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result == [{"id": "prompt-1"}]
        list_prompts.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_resources_team_mismatch(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        response = await list_resources(
            request,
            team_id="team-2",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_resources_include_pagination(self, monkeypatch, allow_permission):
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            AsyncMock(return_value=([resource], "next-cursor")),
        )

        result = await list_resources(
            request,
            include_pagination=True,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result.resources == [resource]
        assert result.next_cursor == "next-cursor"

    @pytest.mark.asyncio
    async def test_list_resources_pagination_null_cursor(self, monkeypatch, allow_permission):
        """EDGE-01: nextCursor must be present (as null) even when there are no more pages."""
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            AsyncMock(return_value=([resource], None)),
        )

        result = await list_resources(
            request,
            include_pagination=True,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result.resources == [resource]
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_list_resources_tags_and_public_only_default(self, monkeypatch, allow_permission):
        """Cover tags parsing + token_teams None -> [] public-only default."""
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            AsyncMock(return_value=([], None)),
        )

        result = await list_resources(
            request,
            tags="a, b",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result.resources == []

    @pytest.mark.asyncio
    async def test_list_resources_forwards_gateway_id(self, monkeypatch, allow_permission):
        """gateway_id query param should be forwarded to the service layer."""
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        list_resources_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            list_resources_mock,
        )

        await list_resources(
            request,
            gateway_id="gw-xyz",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert list_resources_mock.await_args.kwargs["gateway_id"] == "gw-xyz"

    @pytest.mark.asyncio
    async def test_list_resources_forwards_gateway_id_null(self, monkeypatch, allow_permission):
        """gateway_id='null' sentinel should be forwarded verbatim to the service layer."""
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr("mcpgateway.main._get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        list_resources_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(
            "mcpgateway.main.resource_service.list_resources",
            list_resources_mock,
        )

        await list_resources(
            request,
            gateway_id="null",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert list_resources_mock.await_args.kwargs["gateway_id"] == "null"


class TestCrudEndpoints:
    """Cover CRUD endpoints for tools/resources/prompts."""

    @pytest.mark.asyncio
    async def test_create_tool_success(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(return_value=tool))

        tool_input = ToolCreate(name="tool-a", url="http://example.com")
        result = await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is tool

    @pytest.mark.asyncio
    async def test_create_tool_team_mismatch(self, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id="team-1")

        tool_input = ToolCreate(name="tool-a", url="http://example.com")
        response = await create_tool(tool_input, request, team_id="team-2", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_tool_success(self, monkeypatch, allow_permission):
        request = _make_request("/tools/tool-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(version=2)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        tool = MagicMock()
        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(return_value=tool))

        tool_update = ToolUpdate(name="tool-updated")
        result = await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert result is tool

    @pytest.mark.asyncio
    async def test_delete_tool_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.tool_service.delete_tool", AsyncMock(return_value=None))
        result = await delete_tool("tool-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_tool_state_success(self, monkeypatch, allow_permission):
        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(return_value=tool))

        result = await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result["tool"] == {"id": "tool-1"}

    @pytest.mark.asyncio
    async def test_create_resource_success(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(return_value=resource))

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        result = await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is resource

    @pytest.mark.asyncio
    async def test_update_resource_success(self, monkeypatch, allow_permission):
        request = _make_request("/resources/res-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        monkeypatch.setattr("mcpgateway.main.resource_service.update_resource", AsyncMock(return_value={"id": "res-1"}))
        monkeypatch.setattr("mcpgateway.main.invalidate_resource_cache", AsyncMock(return_value=None))

        resource_update = ResourceUpdate(name="Res Updated")
        result = await update_resource("res-1", resource_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["id"] == "res-1"

    @pytest.mark.asyncio
    async def test_delete_resource_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(return_value=None))
        result = await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_resource_state_success(self, monkeypatch, allow_permission):
        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}
        monkeypatch.setattr("mcpgateway.main.resource_service.set_resource_state", AsyncMock(return_value=resource))

        result = await set_resource_state("res-1", activate=False, db=MagicMock(), user={"email": "user@example.com"})
        assert result["resource"] == {"id": "res-1"}

    @pytest.mark.asyncio
    async def test_create_prompt_success(self, monkeypatch, allow_permission):
        request = _make_request("/prompts")
        request.state = SimpleNamespace(team_id=None)

        prompt = MagicMock()
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(return_value=prompt))

        prompt_input = PromptCreate(name="Prompt A", template="Hello")
        result = await create_prompt(prompt_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result is prompt

    @pytest.mark.asyncio
    async def test_update_prompt_success(self, monkeypatch, allow_permission):
        request = _make_request("/prompts/prompt-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(return_value={"id": "prompt-1"}))

        prompt_update = PromptUpdate(name="Prompt Updated")
        result = await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["id"] == "prompt-1"

    @pytest.mark.asyncio
    async def test_delete_prompt_success(self, monkeypatch, allow_permission):
        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(return_value=None))
        result = await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_set_prompt_state_success(self, monkeypatch, allow_permission):
        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}
        monkeypatch.setattr("mcpgateway.main.prompt_service.set_prompt_state", AsyncMock(return_value=prompt))

        result = await set_prompt_state("prompt-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert result["prompt"] == {"id": "prompt-1"}

    @pytest.mark.asyncio
    async def test_create_tool_public_only_token_blocks_team_private_visibility(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="team")
        response = await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_tool_public_only_token_forces_team_id_none(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        register_tool = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", register_tool)

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        await create_tool(tool_input, request, team_id="team-1", db=MagicMock(), user={"email": "user@example.com"})
        assert register_tool.await_args.kwargs["team_id"] is None

    @pytest.mark.asyncio
    async def test_create_tool_name_conflict_inactive_suggests_activation(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        # First-Party
        from mcpgateway.services.tool_service import ToolNameConflictError

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=ToolNameConflictError("tool-a", enabled=False, tool_id=123)))

        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409
        assert "activating" in str(excinfo.value.detail).lower()

    @pytest.mark.asyncio
    async def test_create_tool_tool_error_and_unexpected_error(self, monkeypatch, allow_permission):
        request = _make_request("/tools")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        # First-Party
        from mcpgateway.services.tool_service import ToolError

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=ToolError("bad")))
        tool_input = ToolCreate(name="tool-a", url="http://example.com", visibility="public")
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.tool_service.register_tool", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await create_tool(tool_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_update_tool_tool_error_and_unexpected_error(self, monkeypatch, allow_permission):
        request = _make_request("/tools/tool-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(version=0)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )

        # First-Party
        from mcpgateway.services.tool_service import ToolError

        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(side_effect=ToolError("bad")))
        tool_update = ToolUpdate(name="tool-updated")
        with pytest.raises(HTTPException) as excinfo:
            await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.tool_service.update_tool", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await update_tool("tool-1", tool_update, request, db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_set_tool_state_lock_conflict_and_generic_error(self, monkeypatch, allow_permission):
        # First-Party
        from mcpgateway.services.tool_service import ToolLockConflictError

        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(side_effect=ToolLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.tool_service.set_tool_state", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await set_tool_state("tool-1", activate=True, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_resource_public_only_token_team_visibility_forbidden(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        response = await create_resource(resource_input, request, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_resource_team_mismatch_returns_403(self, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        response = await create_resource(resource_input, request, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_resource_public_only_token_forces_team_id_none(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        register_resource = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", register_resource)

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        await create_resource(resource_input, request, team_id="team-1", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert register_resource.await_args.kwargs["team_id"] is None

    @pytest.mark.asyncio
    async def test_create_resource_validation_error_and_integrity_error(self, monkeypatch, allow_permission):
        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=None)

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        # Build a real pydantic ValidationError instance
        # Third-Party
        from pydantic import BaseModel, ValidationError

        class _DummyModel(BaseModel):
            x: int

        try:
            _DummyModel.model_validate({"x": "bad"})
        except ValidationError as err:
            validation_err = err

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_validation_error", lambda _e: "formatted")
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(side_effect=validation_err))

        resource_input = ResourceCreate(uri="res://1", name="Res", content="data")
        with pytest.raises(HTTPException) as excinfo:
            await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        # Third-Party
        from sqlalchemy.exc import IntegrityError

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_database_error", lambda _e: "db-error")
        monkeypatch.setattr("mcpgateway.main.resource_service.register_resource", AsyncMock(side_effect=IntegrityError("stmt", "params", Exception("orig"))))
        with pytest.raises(HTTPException) as excinfo:
            await create_resource(resource_input, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_resource_uri_conflict_maps_to_409(self, monkeypatch, allow_permission):
        request = _make_request("/resources/res-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        # First-Party
        from mcpgateway.services.resource_service import ResourceURIConflictError

        monkeypatch.setattr("mcpgateway.main.resource_service.update_resource", AsyncMock(side_effect=ResourceURIConflictError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await update_resource("res-1", ResourceUpdate(name="Res Updated"), request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_resource_permission_not_found_and_error(self, monkeypatch, allow_permission):
        # First-Party
        from mcpgateway.services.resource_service import ResourceError, ResourceNotFoundError

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=ResourceNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr("mcpgateway.main.resource_service.delete_resource", AsyncMock(side_effect=ResourceError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_resource("res-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_prompt_public_only_and_error_branches(self, monkeypatch, allow_permission):
        request = _make_request("/prompts")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        prompt_input = PromptCreate(name="Prompt A", template="Hello")
        response = await create_prompt(prompt_input, request, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request2 = _make_request("/prompts")
        request2.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        response = await create_prompt(prompt_input, request2, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request3 = _make_request("/prompts")
        request3.state = SimpleNamespace(team_id="team-1", token_teams=[])
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_args, **_kwargs: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        register_prompt = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", register_prompt)
        await create_prompt(prompt_input, request3, team_id="team-1", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert register_prompt.await_args.kwargs["team_id"] is None

        # First-Party
        from mcpgateway.services.prompt_service import PromptError, PromptNameConflictError

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=PromptNameConflictError("dup")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        # Third-Party
        from pydantic import BaseModel, ValidationError

        class _DummyModel(BaseModel):
            x: int

        try:
            _DummyModel.model_validate({"x": "bad"})
        except ValidationError as err:
            validation_err = err

        monkeypatch.setattr("mcpgateway.main.ErrorFormatter.format_validation_error", lambda _e: "formatted")
        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=validation_err))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        monkeypatch.setattr("mcpgateway.main.prompt_service.register_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await create_prompt(prompt_input, request3, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict_prompt_error_and_unexpected(self, monkeypatch, allow_permission):
        request = _make_request("/prompts/prompt-1")
        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_modification_metadata",
            lambda *_args, **_kwargs: {
                "modified_by": "user",
                "modified_from_ip": "127.0.0.1",
                "modified_via": "api",
                "modified_user_agent": "test",
            },
        )
        prompt_update = PromptUpdate(name="Prompt Updated")

        # First-Party
        from mcpgateway.services.prompt_service import PromptError, PromptNameConflictError

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=PromptNameConflictError("dup")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.prompt_service.update_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await update_prompt("prompt-1", prompt_update, request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_prompt_permission_prompt_error_and_unexpected(self, monkeypatch, allow_permission):
        # First-Party
        from mcpgateway.services.prompt_service import PromptError

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=PromptError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr("mcpgateway.main.prompt_service.delete_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await delete_prompt("prompt-1", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500


class TestPassthroughHeaderSetup:
    """Cover passthrough header setup."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("overwrite", [True, False])
    async def test_setup_passthrough_headers(self, monkeypatch, overwrite):
        monkeypatch.setattr(settings, "enable_overwrite_base_headers", overwrite)

        mock_db = MagicMock()

        def _db_gen():
            yield mock_db

        with (
            patch("mcpgateway.main.get_db", _db_gen),
            patch("mcpgateway.main.set_global_passthrough_headers", new=AsyncMock()),
        ):
            await setup_passthrough_headers()


class TestSecurityConfiguration:
    """Cover security configuration helpers."""

    def test_validate_security_configuration_logs_warnings(self, monkeypatch):
        monkeypatch.setattr(settings, "require_strong_secrets", False)
        monkeypatch.setattr(settings, "dev_mode", False)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "jwt_issuer", "mcpgateway")
        monkeypatch.setattr(settings, "jwt_audience", "mcpgateway-api")
        monkeypatch.setattr(settings, "mcpgateway_ui_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "database_url", "sqlite:///./mcp.db")

        monkeypatch.setattr(
            settings,
            "get_security_status",
            lambda: {"warnings": ["warning"], "secure_secrets": False, "auth_enabled": False},
        )

        validate_security_configuration()

    def test_log_critical_issues_exits_when_enforced(self, monkeypatch):
        monkeypatch.setattr(settings, "require_strong_secrets", True)
        with patch("mcpgateway.main.sys.exit") as mock_exit:
            # First-Party
            from mcpgateway.main import log_critical_issues

            log_critical_issues(["bad"])
            mock_exit.assert_called_once_with(1)


class TestSecurityHealthEndpoint:
    """Cover /health/security endpoint branches in main.py.

    The endpoint now requires admin auth via ``require_admin_auth`` dependency.
    Tests call the handler directly with ``_user`` kwarg to simulate DI.
    """

    @pytest.mark.asyncio
    async def test_security_health_returns_healthy_for_admin(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(
            main_mod.settings,
            "get_security_status",
            lambda: {
                "security_score": 80,
                "auth_enabled": True,
                "secure_secrets": True,
                "ssl_verification": True,
                "debug_disabled": True,
                "cors_restricted": True,
                "ui_protected": True,
                "warnings": [],
            },
        )

        result = await main_mod.security_health(request, _user="admin@example.com")
        assert result["status"] == "healthy"
        assert result["score"] == 80
        assert "warnings" not in result

    @pytest.mark.asyncio
    async def test_security_health_includes_warnings_when_present(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(
            main_mod.settings,
            "get_security_status",
            lambda: {
                "security_score": 80,
                "auth_enabled": True,
                "secure_secrets": True,
                "ssl_verification": True,
                "debug_disabled": True,
                "cors_restricted": True,
                "ui_protected": True,
                "warnings": ["w1"],
            },
        )

        result = await main_mod.security_health(request, _user="admin@example.com")
        assert result["status"] == "healthy"
        assert result["warnings"] == ["w1"]

    @pytest.mark.asyncio
    async def test_security_health_unhealthy_low_score(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(
            main_mod.settings,
            "get_security_status",
            lambda: {
                "security_score": 10,
                "auth_enabled": False,
                "secure_secrets": False,
                "ssl_verification": False,
                "debug_disabled": False,
                "cors_restricted": False,
                "ui_protected": False,
                "warnings": ["w1", "w2"],
            },
        )

        result = await main_mod.security_health(request, _user="admin@example.com")
        assert result["status"] == "unhealthy"
        assert result["warnings"] == ["w1", "w2"]

    def test_security_health_requires_admin_auth_http(self, test_client):
        """Unauthenticated HTTP requests to /health/security must be rejected."""
        # The test_client fixture overrides require_auth but NOT require_admin_auth,
        # so this exercises the real admin auth dependency rejection path.
        # Third-Party
        from fastapi.testclient import TestClient

        # First-Party
        from mcpgateway.main import app

        # Create a client with NO auth overrides for admin auth
        no_admin_client = TestClient(app, raise_server_exceptions=False)
        resp = no_admin_client.get("/health/security")
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


class TestRootEndpointsCoverage:
    """Cover export_root + root lookup/update error branches."""

    @pytest.mark.asyncio
    async def test_export_root_success_and_username_extraction(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        root = SimpleNamespace(uri="root://example", name="Root Name")
        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(return_value=root))

        result = await main_mod.export_root.__wrapped__(uri="root://example", user=SimpleNamespace(email="user@example.com"))
        assert result["export_type"] == "root"
        assert result["exported_by"] == "user@example.com"
        assert result["root"]["uri"] == "root://example"

    @pytest.mark.asyncio
    async def test_export_root_not_found_and_generic_error(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_root(uri="root://missing", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_root.__wrapped__(uri="root://err", user="user")
        assert excinfo.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_root_by_uri_success_and_errors(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        root = SimpleNamespace(uri="root://example", name="Root Name")
        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(return_value=root))
        assert await main_mod.get_root_by_uri("root://example", user={"email": "user@example.com"}) == root

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_root_by_uri("root://missing", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "get_root_by_uri", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            await main_mod.get_root_by_uri("root://err", user={"email": "user@example.com"})

    @pytest.mark.asyncio
    async def test_update_root_success_and_errors(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        updated = SimpleNamespace(uri="root://example", name="Updated")
        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(return_value=updated))
        root_payload = SimpleNamespace(name="Updated")
        assert await main_mod.update_root("root://example", root_payload, user={"email": "user@example.com"}) == updated

        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(side_effect=main_mod.RootServiceNotFoundError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_root("root://missing", root_payload, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.root_service, "update_root", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            await main_mod.update_root("root://err", root_payload, user={"email": "user@example.com"})


class TestToolListEndpointCoverage:
    """Cover list_tools() branches (tags parsing, scoping, pagination, mismatch)."""

    @pytest.mark.asyncio
    async def test_list_tools_parses_tags_and_paginates(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        list_tools_mock = AsyncMock(return_value=([tool], "next"))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", list_tools_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        result = await main_mod.list_tools(
            request,
            cursor=None,
            tags="a, b",
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert result.tools == [tool]
        assert result.next_cursor == "next"
        assert list_tools_mock.await_args.kwargs["tags"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_list_tools_admin_bypass_and_public_only_default(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        list_tools_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", list_tools_mock)

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert list_tools_mock.await_args.kwargs["user_email"] is None
        assert list_tools_mock.await_args.kwargs["token_teams"] is None

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert list_tools_mock.await_args.kwargs["token_teams"] == []

    @pytest.mark.asyncio
    async def test_list_tools_team_mismatch_returns_403(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")
        db = MagicMock()

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))
        response = await main_mod.list_tools(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            gateway_id=None,
            db=db,
            apijsonpath=None,
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403


class TestPromptListEndpointCoverage:
    """Cover list_prompts() branches (tags parsing, scoping, pagination, mismatch)."""

    @pytest.mark.asyncio
    async def test_list_prompts_parses_tags_and_paginates(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "prompt-1"}
        list_prompts_mock = AsyncMock(return_value=([prompt], "next"))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))

        result = await main_mod.list_prompts(
            request,
            cursor=None,
            tags="a, b",
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result.prompts == [prompt]
        assert result.next_cursor == "next"
        assert list_prompts_mock.await_args.kwargs["tags"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_list_prompts_team_mismatch_returns_403(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1")
        db = MagicMock()

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", ["team-1"], False))
        response = await main_mod.list_prompts(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_prompts_forwards_gateway_id(self, monkeypatch):
        """gateway_id query param should be forwarded to the service layer."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        list_prompts_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))

        await main_mod.list_prompts(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id="gw-abc",
            db=db,
            user={"email": "user@example.com"},
        )
        assert list_prompts_mock.await_args.kwargs["gateway_id"] == "gw-abc"

    @pytest.mark.asyncio
    async def test_list_prompts_forwards_gateway_id_null(self, monkeypatch):
        """gateway_id='null' sentinel should be forwarded verbatim to the service layer."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        list_prompts_mock = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts_mock)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))

        await main_mod.list_prompts(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id="null",
            db=db,
            user={"email": "user@example.com"},
        )
        assert list_prompts_mock.await_args.kwargs["gateway_id"] == "null"


class TestReadResourceEndpointCoverage:
    """Cover read_resource() serialization branches."""

    @pytest.mark.asyncio
    async def test_read_resource_serializes_text_bytes_and_str(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"X-Request-ID": "rid", "X-Server-ID": "sid"}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        # First-Party
        from mcpgateway.common.models import TextContent

        class TextWithUri(TextContent):
            uri: str

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=TextWithUri(type="text", text="hello", uri="res://1")))
        result = await main_mod.read_resource("res-1", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["text"] == "hello"
        assert result["uri"] == "res://1"

        class BytesWithUri(bytes):
            def __new__(cls, value: bytes, uri: str):  # noqa: D401
                obj = super().__new__(cls, value)
                obj._uri = uri
                return obj

            @property
            def uri(self):  # noqa: D401
                return self._uri

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=BytesWithUri(b"abc", "res://2")))
        result = await main_mod.read_resource("res-2", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["blob"] == "abc"
        assert result["uri"] == "res://2"

        class StrWithUri(str):
            def __new__(cls, value: str, uri: str):  # noqa: D401
                obj = super().__new__(cls, value)
                obj._uri = uri
                return obj

            @property
            def uri(self):  # noqa: D401
                return self._uri

        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=StrWithUri("hi", "res://3")))
        result = await main_mod.read_resource("res-3", request=request, db=db, user={"email": "user@example.com", "is_admin": False})
        assert result["text"] == "hi"
        assert result["uri"] == "res://3"


class TestGetPromptEndpointCoverage:
    """Cover get_prompt() exception mapping branches."""

    @pytest.mark.asyncio
    async def test_get_prompt_maps_common_errors_to_422(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        # PluginViolationError -> 422 with plugin message.
        # First-Party
        from mcpgateway.plugins.framework.errors import PluginViolationError

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PluginViolationError("blocked", violation=SimpleNamespace(code="c"))))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422

        # ValueError -> 422 with message.
        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=ValueError("bad args")))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422

        # PromptError -> 422 with message.
        # First-Party
        from mcpgateway.services.prompt_service import PromptError

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PromptError("bad prompt")))
        response = await main_mod.get_prompt(request, "prompt-1", args={}, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422


class TestGatewayEndpointsCoverage:
    """Cover gateway endpoint error mapping + refresh manual path."""

    @pytest.mark.asyncio
    async def test_delete_gateway_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        # First-Party
        from mcpgateway.services.gateway_service import GatewayError, GatewayNotFoundError

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_gateway_success_invalidates_resource_cache_when_needed(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        db = MagicMock()
        monkeypatch.setattr(db, "commit", MagicMock())
        monkeypatch.setattr(db, "close", MagicMock())

        current = SimpleNamespace(capabilities={"resources": True})
        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(return_value=current))
        monkeypatch.setattr(main_mod.gateway_service, "delete_gateway", AsyncMock(return_value=None))
        invalidate = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod, "invalidate_resource_cache", invalidate)

        result = await main_mod.delete_gateway("gw-1", db=db, user={"email": "user@example.com"})
        assert result["status"] == "success"
        invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_gateway_tools_success_and_errors(self, monkeypatch):
        # Standard
        from datetime import datetime, timezone

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.gateway_service import GatewayError, GatewayNotFoundError

        request = MagicMock(spec=Request)
        request.headers = {"x-test": "1"}
        db = MagicMock()

        result_payload = {
            "duration_ms": 1.0,
            "refreshed_at": datetime.now(timezone.utc),
            "tools_added": 1,
        }
        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(return_value=SimpleNamespace(id="gw-1")))
        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(return_value=result_payload))
        response = await main_mod.refresh_gateway_tools(
            "gw-1",
            request,
            include_resources=True,
            include_prompts=False,
            db=db,
            user={"email": "user@example.com"},
        )
        assert response.gateway_id == "gw-1"
        assert response.tools_added == 1

        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.refresh_gateway_tools(
                "gw-1",
                request,
                include_resources=False,
                include_prompts=False,
                db=db,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(side_effect=GatewayError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.refresh_gateway_tools(
                "gw-1",
                request,
                include_resources=False,
                include_prompts=False,
                db=db,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_refresh_gateway_tools_denies_cross_scope_access(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"x-test": "1"}
        db = MagicMock()

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(return_value=SimpleNamespace(id="gw-1")))
        monkeypatch.setattr(main_mod.gateway_service, "refresh_gateway_manually", AsyncMock(return_value={}))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.refresh_gateway_tools("gw-1", request, include_resources=False, include_prompts=False, db=db, user={"email": "user@example.com"})

        assert excinfo.value.status_code == 403
        main_mod.gateway_service.refresh_gateway_manually.assert_not_awaited()


class TestLifespanAdvanced:
    """Cover lifespan startup/shutdown branches."""

    @pytest.mark.asyncio
    async def test_lifespan_with_feature_flags(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeEvent:
            def __init__(self):
                self._set = False

            def is_set(self):
                return self._set

            def set(self):
                self._set = True

            async def wait(self):
                self._set = True
                return True

        def make_service():
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Feature flags
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", True)
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_jwt_identity_extraction", True)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", True)
        monkeypatch.setattr(main_mod.settings, "db_metrics_recording_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", True)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 1)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)
        # Exercise the llmchat-enabled branch in lifespan (the lazy import
        # and init_redis() call are skipped unless this flag is true).
        monkeypatch.setattr(main_mod.settings, "llmchat_enabled", True)

        _default_manager = MagicMock()
        _default_manager.plugin_count = 2
        mock_get_pm = AsyncMock(return_value=_default_manager)
        mock_shutdown_factory = AsyncMock(side_effect=Exception("boom"))
        monkeypatch.setattr(main_mod, "get_plugin_manager", mock_get_pm)
        monkeypatch.setattr(main_mod, "shutdown_plugin_manager_factory", mock_shutdown_factory)

        logging_service = make_service()
        logging_service.configure_uvicorn_after_startup = MagicMock()
        monkeypatch.setattr(main_mod, "logging_service", logging_service)

        for attr in (
            "tool_service",
            "resource_service",
            "prompt_service",
            "gateway_service",
            "root_service",
            "completion_service",
            "sampling_handler",
            "resource_cache",
            "streamable_http_session",
            "session_registry",
            "export_service",
            "import_service",
        ):
            monkeypatch.setattr(main_mod, attr, make_service())

        monkeypatch.setattr(main_mod, "a2a_service", make_service())

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "setup_passthrough_headers", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr(main_mod, "attempt_to_bootstrap_sso_providers", AsyncMock())

        # Optional service factories
        elicitation_service = MagicMock()
        elicitation_service.start = AsyncMock()
        elicitation_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.elicitation_service.get_elicitation_service",
            MagicMock(return_value=elicitation_service),
        )

        metrics_buffer_service = MagicMock()
        metrics_buffer_service.start = AsyncMock()
        metrics_buffer_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service",
            MagicMock(return_value=metrics_buffer_service),
        )

        metrics_cleanup_service = MagicMock()
        metrics_cleanup_service.start = AsyncMock()
        metrics_cleanup_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service",
            MagicMock(return_value=metrics_cleanup_service),
        )

        metrics_rollup_service = MagicMock()
        metrics_rollup_service.start = AsyncMock()
        metrics_rollup_service.shutdown = AsyncMock()
        monkeypatch.setattr(
            "mcpgateway.services.metrics_rollup_service.get_metrics_rollup_service",
            MagicMock(return_value=metrics_rollup_service),
        )

        # MCP session pool hooks
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.init_mcp_session_pool", MagicMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.start_pool_notification_service", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.close_mcp_session_pool", AsyncMock())
        pool = SimpleNamespace(start_rpc_listener=AsyncMock(), start_heartbeat=MagicMock())
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", MagicMock(return_value=pool))

        # Cache invalidation subscriber
        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock(side_effect=Exception("stop fail"))
        # `mcpgateway.cache` uses lazy `__getattr__` which returns a `registry_cache`
        # instance, so string-based patching can resolve to the wrong object under xdist.
        # First-Party
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        # LLM chat Redis init
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        # Shared HTTP client
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        # Log aggregation helpers
        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        # Async helpers
        monkeypatch.setattr(main_mod.asyncio, "Event", FakeEvent)
        monkeypatch.setattr(main_mod.asyncio, "to_thread", AsyncMock())

        main_mod.app.state.update_http_pool_metrics = MagicMock()

        async with main_mod.lifespan(main_mod.app):
            await asyncio.sleep(0)

        mock_get_pm.assert_awaited_once()
        mock_shutdown_factory.assert_awaited()

    @pytest.mark.asyncio
    async def test_lifespan_exits_on_plugin_initialization_failed(self, monkeypatch):
        """Cover lifespan startup exception branch that raises SystemExit on plugin init failure."""
        # First-Party
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Keep startup/shutdown lightweight.
        for flag, value in (
            ("mcp_session_pool_enabled", False),
            ("mcpgateway_session_affinity_enabled", False),
            ("enable_header_passthrough", False),
            ("mcpgateway_tool_cancellation_enabled", False),
            ("mcpgateway_elicitation_enabled", False),
            ("metrics_buffer_enabled", False),
            ("metrics_cleanup_enabled", False),
            ("metrics_rollup_enabled", False),
            ("sso_enabled", False),
            ("metrics_aggregation_enabled", False),
        ):
            monkeypatch.setattr(main_mod.settings, flag, value)

        logging_service = make_service()
        logging_service.configure_uvicorn_after_startup = MagicMock()
        monkeypatch.setattr(main_mod, "logging_service", logging_service)

        for attr in (
            "tool_service",
            "resource_service",
            "prompt_service",
            "gateway_service",
            "root_service",
            "completion_service",
            "sampling_handler",
            "resource_cache",
            "streamable_http_session",
            "session_registry",
            "export_service",
            "import_service",
        ):
            monkeypatch.setattr(main_mod, attr, make_service())
        monkeypatch.setattr(main_mod, "a2a_service", None)

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        # First-Party
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        monkeypatch.setattr(main_mod, "get_plugin_manager", AsyncMock(side_effect=Exception("Plugin initialization failed")))
        monkeypatch.setattr(main_mod, "shutdown_plugin_manager_factory", AsyncMock())

        with pytest.raises(SystemExit) as excinfo:
            async with main_mod.lifespan(main_mod.app):
                pass

        assert excinfo.value.code == 1

    @pytest.mark.asyncio
    async def test_shutdown_services_continues_on_exception(self):
        """Cover shutdown_services exception logging branch."""
        # First-Party
        import mcpgateway.main as main_mod

        bad = MagicMock()
        bad.shutdown = AsyncMock(side_effect=Exception("boom"))
        good = MagicMock()
        good.shutdown = AsyncMock()

        await main_mod.shutdown_services([bad, good])

        good.shutdown.assert_awaited_once()


class TestUtilityFunctions:
    """Test utility functions for edge cases."""

    def test_message_endpoint_edge_cases(self, test_client, auth_headers):
        """Test message endpoint with edge case parameters."""
        # Test with missing session_id to trigger validation error
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message", json=message, headers=auth_headers)
        assert response.status_code == 400  # Should require session_id parameter

        # Test with valid session_id
        with (
            patch("mcpgateway.main.session_registry.get_session_owner", new=AsyncMock(return_value="test_user@example.com")),
            patch("mcpgateway.main.session_registry.broadcast") as mock_broadcast,
        ):
            response = test_client.post("/message?session_id=test-session", json=message, headers=auth_headers)
            assert response.status_code == 202
            mock_broadcast.assert_called_once()

    def test_root_endpoint_conditional_behavior(self):
        """Test root endpoint behavior based on UI settings.

        Note: Route registration happens at import time based on settings.mcpgateway_ui_enabled.
        Patching settings after import doesn't change which routes are registered.
        This test verifies the currently registered behavior.
        """
        client = TestClient(app)
        response = client.get("/", follow_redirects=False)

        # The behavior depends on whether UI was enabled when app was imported
        if response.status_code == 303:
            # UI enabled: redirects to /admin/
            location = response.headers.get("location", "")
            assert "/admin/" in location
        elif response.status_code == 200:
            # Could be JSON (UI disabled) or HTML (followed redirect to admin)
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()
                assert "name" in data
            # HTML response from admin is also acceptable (UI enabled with auto-redirect)
        else:
            # Accept other valid status codes (e.g., 307 for redirect)
            assert response.status_code in [200, 303, 307]

    def test_exception_handler_scenarios(self, test_client, auth_headers):
        """Test exception handlers with various scenarios."""
        # Test simple validation error by providing invalid data
        req = {"invalid": "data"}  # Missing required 'name' field
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error
        assert response.status_code == 422

    def test_json_rpc_error_paths(self, test_client, auth_headers):
        """Test JSON-RPC error handling paths."""
        # Test with a valid JSON-RPC request that might not find the tool
        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "nonexistent_tool",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)
        # Should return a valid JSON-RPC response even for non-existent tools
        assert response.status_code == 200
        body = response.json()
        # Should have either result or error
        assert "result" in body or "error" in body

    @patch("mcpgateway.main.settings")
    def test_websocket_error_scenarios(self, mock_settings):
        """Test WebSocket error scenarios."""
        # Configure mock settings for auth disabled
        mock_settings.mcpgateway_ws_relay_enabled = True
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.auth_required = False
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.port = 4444

        with patch("mcpgateway.main.ResilientHttpClient") as mock_client:
            # Standard

            mock_instance = mock_client.return_value
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = False

            # Mock a failing post operation
            async def failing_post(*_args, **_kwargs):
                raise Exception("Network error")

            mock_instance.post = failing_post

            client = TestClient(app)
            with client.websocket_connect("/ws") as websocket:
                websocket.send_text('{"jsonrpc":"2.0","method":"ping","id":1}')
                # Should handle the error gracefully
                try:
                    data = websocket.receive_text()
                    # Either gets error response or connection closes
                    if data:
                        response = json.loads(data)
                        assert "error" in response or "result" in response
                except Exception:
                    # Connection may close due to error
                    pass

    @pytest.mark.asyncio
    async def test_websocket_feature_disabled_closes(self, monkeypatch):
        """WebSocket relay should reject connections when feature flag is disabled."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", False)
        websocket = MagicMock()
        websocket.close = AsyncMock()
        websocket.accept = AsyncMock()

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="WebSocket relay is disabled")
        websocket.accept.assert_not_called()

    def test_get_websocket_bearer_token_accepts_lowercase_scheme(self):
        """Bearer scheme parsing should be case-insensitive for WebSocket auth headers."""
        # First-Party
        import mcpgateway.main as main_mod

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "bearer test-token"}

        assert main_mod._get_websocket_bearer_token(websocket) == "test-token"

    def test_get_websocket_bearer_token_ignores_query_param(self):
        """Query-string tokens should not be accepted for WebSocket auth."""
        # First-Party
        import mcpgateway.main as main_mod

        websocket = MagicMock()
        websocket.query_params = {"token": "legacy-token"}
        websocket.headers = {}

        assert main_mod._get_websocket_bearer_token(websocket) is None

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_wraps_unexpected_auth_errors(self, monkeypatch):
        """Unexpected auth backend errors should be normalized to HTTP 401."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer token"}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id=None, token_teams=None, token_use=None)

        monkeypatch.setattr(main_mod, "get_current_user", AsyncMock(side_effect=RuntimeError("db down")))

        with pytest.raises(HTTPException) as exc_info:
            await main_mod._authenticate_websocket_user(websocket)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication failed"

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_propagates_http_exception(self, monkeypatch):
        """HTTPException from auth backend should pass through unchanged."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer token"}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id=None, token_teams=None, token_use=None)

        monkeypatch.setattr(main_mod, "get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token")))

        with pytest.raises(HTTPException) as exc_info:
            await main_mod._authenticate_websocket_user(websocket)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_success_with_bearer_token(self, monkeypatch):
        """Successful bearer auth should return token and no proxy user."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer token", "user-agent": "pytest"}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"], token_use="session")

        user = SimpleNamespace(email="user@example.com", full_name="User Example", is_admin=False)
        monkeypatch.setattr(main_mod, "get_current_user", AsyncMock(return_value=user))
        monkeypatch.setattr(main_mod.PermissionChecker, "has_any_permission", AsyncMock(return_value=True))

        auth_token, proxy_user = await main_mod._authenticate_websocket_user(websocket)

        assert auth_token == "token"
        assert proxy_user is None

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_proxy_auth_missing_header_requires_auth(self, monkeypatch):
        """Proxy-auth mode should reject requests without trusted user header when auth is required."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "trust_proxy_auth", True)
        monkeypatch.setattr(main_mod.settings, "trust_proxy_auth_dangerously", True)
        monkeypatch.setattr(main_mod.settings, "proxy_user_header", "X-Forwarded-User")

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id=None, token_teams=None, token_use=None)

        with pytest.raises(HTTPException) as exc_info:
            await main_mod._authenticate_websocket_user(websocket)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication required"

    @pytest.mark.asyncio
    async def test_authenticate_websocket_user_denies_when_permissions_missing(self, monkeypatch):
        """Authenticated websocket users must have at least one allowed permission."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer token", "user-agent": "pytest"}
        websocket.client = SimpleNamespace(host="127.0.0.1")
        websocket.state = SimpleNamespace(team_id=None, token_teams=[], token_use="api")

        user = SimpleNamespace(email="user@example.com", full_name="User Example", is_admin=False)
        monkeypatch.setattr(main_mod, "get_current_user", AsyncMock(return_value=user))
        monkeypatch.setattr(main_mod.PermissionChecker, "has_any_permission", AsyncMock(return_value=False))

        with pytest.raises(HTTPException) as exc_info:
            await main_mod._authenticate_websocket_user(websocket)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_websocket_bearer_auth_invalid_token_closes(self, monkeypatch):
        """Cover Bearer token extraction + invalid token close path."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {"authorization": "Bearer bad-token"}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()

        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid authentication")))

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="Invalid authentication")
        websocket.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_proxy_auth_required_closes(self, monkeypatch):
        """Cover proxy-auth required branch when trust_proxy_auth is enabled."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "trust_proxy_auth", True)
        monkeypatch.setattr(main_mod.settings, "trust_proxy_auth_dangerously", True)
        monkeypatch.setattr(main_mod.settings, "auth_required", True)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Authentication required")))

        await main_mod.websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(code=1008, reason="Authentication required")
        websocket.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_jsonrpc_error_sends_error_text(self, monkeypatch):
        """Cover JSONRPCError branch inside the websocket relay loop."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod.settings, "federation_timeout", 1)
        monkeypatch.setattr(main_mod.settings, "skip_ssl_verify", False)
        monkeypatch.setattr(main_mod.settings, "port", 4444)
        monkeypatch.setattr(main_mod.settings, "app_root_path", "")

        err = main_mod.JSONRPCError(-32000, "boom", {})

        class DummyClient:
            async def __aenter__(self):  # noqa: D401
                return self

            async def __aexit__(self, *_args):  # noqa: D401, ANN001
                return False

            async def post(self, *_args, **_kwargs):  # noqa: ANN001
                raise err

        monkeypatch.setattr(main_mod, "ResilientHttpClient", lambda *_a, **_k: DummyClient())
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=['{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}', Exception("stop")])

        await main_mod.websocket_endpoint(websocket)

        assert websocket.send_text.await_count >= 1

    @pytest.mark.asyncio
    async def test_websocket_invalid_json_sends_parse_error(self, monkeypatch):
        """Cover orjson.JSONDecodeError -> JSON-RPC parse error response."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=["{", Exception("stop")])

        await main_mod.websocket_endpoint(websocket)

        sent = websocket.send_text.await_args.args[0]
        parsed = json.loads(sent)
        assert parsed["error"]["code"] == -32700

    @pytest.mark.asyncio
    async def test_websocket_outer_exception_close_failure_is_caught(self, monkeypatch):
        """Cover outer exception handler when websocket.close itself fails."""
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "mcp_client_auth_enabled", False)
        monkeypatch.setattr(main_mod.settings, "auth_required", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_ws_relay_enabled", True)
        monkeypatch.setattr(main_mod, "_authenticate_websocket_user", AsyncMock(return_value=(None, None)))

        websocket = MagicMock()
        websocket.query_params = {}
        websocket.headers = {}
        websocket.accept = AsyncMock(side_effect=RuntimeError("accept failed"))
        websocket.close = AsyncMock(side_effect=Exception("close failed"))

        await main_mod.websocket_endpoint(websocket)

        assert websocket.close.await_count == 1

    def test_sse_endpoint_edge_cases(self, test_client, auth_headers):
        """Test SSE endpoint edge cases."""
        with patch("mcpgateway.main.SSETransport") as mock_transport_class, patch("mcpgateway.main.session_registry.add_session"):
            mock_transport = MagicMock()
            mock_transport.session_id = "test-session"

            # Test SSE transport creation error
            mock_transport_class.side_effect = Exception("SSE error")

            response = test_client.get("/servers/test/sse", headers=auth_headers)
            # Should handle SSE creation error
            assert response.status_code in [404, 500, 503]

    @pytest.mark.asyncio
    async def test_utility_sse_bearer_token_and_disconnect_cleanup(self, monkeypatch, allow_permission):
        """Cover /sse auth token extraction + defensive disconnect cleanup callback."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer token"}
        request.cookies = {}
        request.scope = {"root_path": ""}

        user = SimpleNamespace(email="user@example.com", is_admin=True)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: None)

        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        remove_session = AsyncMock()
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)
        respond = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod.session_registry, "respond", respond)
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.asyncio, "create_task", MagicMock(return_value=MagicMock()))

        transport = SimpleNamespace(session_id="session-1", connect=AsyncMock())
        captured: dict[str, object] = {}

        async def _create_sse_response(_request, *, on_disconnect_callback=None):  # noqa: ANN001
            captured["callback"] = on_disconnect_callback
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))

        # Bypass RBAC wrapper so we can pass a non-dict user object and exercise
        # the `hasattr(user, "is_admin")` branch inside the endpoint.
        response = await main_mod.utility_sse_endpoint.__wrapped__(request, user=user)
        assert response.status_code == 200
        assert response.background is not None

        assert callable(captured.get("callback"))
        await captured["callback"]()
        remove_session.assert_awaited_once_with("session-1")

    @pytest.mark.asyncio
    async def test_utility_sse_cookie_token_and_cleanup_warning(self, monkeypatch, allow_permission):
        """Cover cookie token extraction + cleanup exception branch."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.cookies = {"jwt_token": "cookie-token"}
        request.scope = {"root_path": ""}

        user = {"email": "user@example.com", "is_admin": False}

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])

        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.asyncio, "create_task", MagicMock(return_value=MagicMock()))

        remove_session = AsyncMock(side_effect=Exception("boom"))
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)

        transport = SimpleNamespace(session_id="session-2", connect=AsyncMock())
        captured: dict[str, object] = {}

        async def _create_sse_response(_request, *, on_disconnect_callback=None):  # noqa: ANN001
            captured["callback"] = on_disconnect_callback
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))

        response = await main_mod.utility_sse_endpoint(request, user=user)
        assert response.status_code == 200

        # Cleanup callback should swallow errors from session_registry.remove_session.
        await captured["callback"]()

    def test_server_toggle_edge_cases(self, test_client, auth_headers):
        """Test server toggle endpoint edge cases."""
        with patch("mcpgateway.main.server_service.set_server_state") as mock_toggle:
            # Create a proper ServerRead model response
            # First-Party
            from mcpgateway.schemas import ServerRead

            mock_server_data = {
                "id": "1",
                "name": "test_server",
                "description": "A test server",
                "icon": None,
                "created_at": "2023-01-01T00:00:00+00:00",
                "updated_at": "2023-01-01T00:00:00+00:00",
                "enabled": True,
                "associated_tools": [],
                "associated_resources": [],
                "associated_prompts": [],
                "metrics": {
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": 0.0,
                    "max_response_time": 0.0,
                    "avg_response_time": 0.0,
                    "last_execution_time": None,
                },
            }

            mock_toggle.return_value = ServerRead(**mock_server_data)

            # Test activate=true
            response = test_client.post("/servers/1/state?activate=true", headers=auth_headers)
            assert response.status_code == 200

            # Test activate=false
            mock_server_data["enabled"] = False
            mock_toggle.return_value = ServerRead(**mock_server_data)
            response = test_client.post("/servers/1/state?activate=false", headers=auth_headers)
            assert response.status_code == 200


# Test fixtures
@pytest.fixture(autouse=True)
def reset_db(app_with_temp_db):
    """Clear the temp DB between tests when using the module-scoped app."""
    engine = db_mod.engine
    if engine is None:
        yield
        return

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

        for table in reversed(db_mod.Base.metadata.sorted_tables):
            conn.execute(table.delete())

        if engine.dialect.name == "sqlite":
            try:
                conn.exec_driver_sql("DELETE FROM sqlite_sequence")
            except sa.exc.DatabaseError:
                pass
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    yield


# Test fixtures
@pytest.fixture
def test_client(app_with_temp_db):
    """Test client with auth override for testing protected endpoints."""
    # Standard
    from unittest.mock import MagicMock, patch

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.verify_credentials import require_auth

    # Mock user object for RBAC system
    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,  # Give admin privileges for tests
        is_active=True,
        auth_provider="test",
    )

    # Mock security_logger to prevent database access
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    # Mock require_auth_override function
    def mock_require_auth_override(user: str) -> str:
        return user

    # Patch the require_docs_auth_override function
    patcher = patch("mcpgateway.main.require_docs_auth_override", mock_require_auth_override)
    patcher.start()

    # Override the core auth function used by RBAC system
    app_with_temp_db.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    # Override get_current_user_with_permissions for RBAC system
    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test"}

    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock the permission service to always return True for tests
    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    async def mock_check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type=None,
        resource_id=None,
        team_id=None,
        token_teams=None,
        ip_address=None,
        user_agent=None,
        allow_admin_bypass=True,
        check_any_team=False,
        **_kwargs,
    ) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    # Override require_auth for backward compatibility
    app_with_temp_db.dependency_overrides[require_auth] = lambda: "test_user"

    client = TestClient(app_with_temp_db)
    yield client

    # Clean up overrides and restore original methods
    app_with_temp_db.dependency_overrides.pop(require_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    patcher.stop()  # Stop the require_auth_override patch
    sec_patcher.stop()  # Stop the security_logger patch
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission


@pytest.fixture
def allow_permission(monkeypatch):
    """Force permission checks to pass for direct endpoint calls."""
    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))
    return True


class TestA2AEndpoints:
    """Exercise A2A endpoints in main.py."""

    @pytest.fixture(autouse=True)
    def _ensure_a2a_router(self, main_app_with_a2a_router):
        """Guarantee ``a2a_router`` is mounted on ``main.app`` for this class.

        Under xdist a worker may have imported main while A2A was
        transiently disabled, leaving the router unmounted.
        ``main_app_with_a2a_router`` dynamically mounts it on the live
        app so every test in this class can hit /a2a/* deterministically.
        """
        return main_app_with_a2a_router

    @staticmethod
    def _agent_read(agent_id: str = "agent-1") -> dict:
        return {
            "id": agent_id,
            "name": "Agent One",
            "slug": "agent-one",
            "description": "Test agent",
            "endpoint_url": "http://example.com/agent",
            "agent_type": "generic",
            "protocol_version": "1.0",
            "capabilities": {},
            "config": {},
            "enabled": True,
            "reachable": True,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "last_interaction": None,
            "tags": [],
            "metrics": None,
        }

    def test_create_a2a_agent(self, test_client, auth_headers):
        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch(
                "mcpgateway.main.MetadataCapture.extract_creation_metadata",
                return_value={
                    "created_by": "user",
                    "created_from_ip": "127.0.0.1",
                    "created_via": "api",
                    "created_user_agent": "test",
                    "import_batch_id": None,
                    "federation_source": None,
                },
            ),
        ):
            mock_service.register_agent = AsyncMock(return_value=self._agent_read())
            payload = {"agent": {"name": "Agent One", "endpoint_url": "http://example.com/agent"}, "team_id": None, "visibility": "public"}
            response = test_client.post("/a2a", json=payload, headers=auth_headers)
            assert response.status_code == 201
            assert response.json()["name"] == "Agent One"

    def test_update_a2a_agent(self, test_client, auth_headers):
        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch(
                "mcpgateway.main.MetadataCapture.extract_modification_metadata",
                return_value={"modified_by": "user", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
            ),
        ):
            mock_service.update_agent = AsyncMock(return_value=self._agent_read("agent-2"))
            payload = {"agent": {"name": "Agent Two", "endpoint_url": "http://example.com/agent-two"}}
            response = test_client.put("/a2a/agent-2", json=payload, headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["id"] == "agent-2"

    def test_delete_a2a_agent(self, test_client, auth_headers):
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.delete_agent = AsyncMock()
            response = test_client.delete("/a2a/agent-3", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "success"

    def test_invoke_a2a_agent(self, test_client, auth_headers):
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.invoke_agent = AsyncMock(return_value={"ok": True})
            response = test_client.post(
                "/a2a/agent-4/invoke",
                json={"parameters": {"query": "hello"}, "interaction_type": "query"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True


class TestA2ABranchCoverage:
    """Cover A2A branches that aren't hit via happy-path API tests."""

    @pytest.mark.asyncio
    async def test_create_a2a_agent_rejects_public_only_token_for_team_visibility(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None, token_teams=[])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        response = await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="team", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_a2a_agent_team_mismatch_and_service_unavailable(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        response = await main_mod.create_a2a_agent(agent, request, team_id="team-2", visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_a2a_agent_validation_and_integrity_errors(self, monkeypatch):
        # Third-Party
        from pydantic import BaseModel, ValidationError
        from sqlalchemy.exc import IntegrityError

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import A2AAgentCreate

        class _Tmp(BaseModel):
            value: int

        try:
            _Tmp.model_validate({})
        except ValidationError as e:
            validation_error = e

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])

        monkeypatch.setattr(
            "mcpgateway.main.MetadataCapture.extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", lambda _e: "bad")
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_database_error", lambda _e: "db")

        agent = A2AAgentCreate(name="agent", endpoint_url="http://example.com/agent")
        svc = MagicMock()
        svc.register_agent = AsyncMock(side_effect=validation_error)
        monkeypatch.setattr(main_mod, "a2a_service", svc)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        svc.register_agent = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("orig")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_a2a_agent(agent, request, team_id=None, visibility="public", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_a2a_agent_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

        svc = MagicMock()
        svc.delete_agent = AsyncMock(side_effect=PermissionError("nope"))
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

        svc.delete_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        svc.delete_agent = AsyncMock(side_effect=A2AAgentError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_a2a_agent("agent-1", purge_metrics=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_a2a_agent_branches_and_errors(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 503

        svc = MagicMock()
        svc.invoke_agent = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, False))
        result = await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert result["ok"] is True
        assert svc.invoke_agent.await_args.kwargs["token_teams"] == []

        svc.invoke_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

        svc.invoke_agent = AsyncMock(side_effect=A2AAgentError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.invoke_a2a_agent("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        # Cover user_id=str(user) branch by bypassing RBAC wrapper.
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))
        svc.invoke_agent = AsyncMock(return_value={"ok": True})
        result = await main_mod.invoke_a2a_agent.__wrapped__("agent", request, parameters={}, interaction_type="query", db=MagicMock(), user="basic-user")
        assert result["ok"] is True
        assert svc.invoke_agent.await_args.kwargs["user_id"] == "basic-user"

    @pytest.mark.asyncio
    async def test_list_and_get_a2a_agents_branches(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)
        db = MagicMock()

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_a2a_agents(
                request,
                include_inactive=False,
                tags="a, b",
                team_id=None,
                visibility=None,
                cursor=None,
                include_pagination=False,
                limit=None,
                db=db,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 503

        agent = MagicMock()
        agent.model_dump.return_value = {"id": "agent-1"}
        svc = MagicMock()
        svc.list_agents = AsyncMock(return_value=([agent], "next"))
        svc.get_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", None, True))

        result = await main_mod.list_a2a_agents(
            request,
            include_inactive=False,
            tags="a, b",
            team_id=None,
            visibility=None,
            cursor=None,
            include_pagination=True,
            limit=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result.agents == [agent]
        assert result.next_cursor == "next"

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_a2a_agent("agent-1", request, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404


class TestRpcHandling:
    """Cover RPC handler branches."""

    @pytest.fixture(autouse=True)
    def _trust_internal_rust_headers_for_handler_logic_tests(self, monkeypatch):
        """Keep this suite focused on handler logic, not trust-boundary validation.

        The trust boundary itself is covered separately by the dedicated helper
        and middleware tests above.
        """
        monkeypatch.setattr(
            "mcpgateway.main._is_trusted_internal_mcp_runtime_request",
            lambda request: request.headers.get("x-contextforge-mcp-runtime") == "rust" and getattr(getattr(request, "client", None), "host", None) in ("127.0.0.1", "::1"),
        )

    @staticmethod
    def _make_request(payload: dict) -> MagicMock:
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.headers = {}
        request.query_params = {}
        request.state = MagicMock()
        return request

    async def test_handle_rpc_parse_error(self):
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=b"{bad")
        request.headers = {}
        request.query_params = {}
        response = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 400

    async def test_handle_rpc_tools_list_server(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {"server_id": "srv"}}
        request = self._make_request(payload)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock(return_value=[tool])) as mock_list_server_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert len(result["result"]["tools"]) == 1
            assert mock_list_server_tools.await_args.args[1] == "srv"

    async def test_handle_rpc_tools_list_uses_internal_rust_server_header(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {"server_id": "body-srv"}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "header-srv",
        }

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-header"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock(return_value=[tool])) as mock_list_server_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})

        assert len(result["result"]["tools"]) == 1
        assert mock_list_server_tools.await_args.args[1] == "header-srv"

    async def test_handle_rpc_ignores_internal_server_header_without_rust_runtime_marker(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-server-id": "spoofed-srv",
        }

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-plain"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))) as mock_list_tools,
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock()) as mock_list_server_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})

        assert len(result["result"]["tools"]) == 1
        mock_list_tools.assert_awaited_once()
        mock_list_server_tools.assert_not_awaited()

    async def test_handle_internal_mcp_rpc_uses_forwarded_auth_context(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "token_use": "session",
                        "scoped_permissions": ["tools.read"],
                        "scoped_server_id": "srv-scoped",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._handle_rpc_authenticated", new=AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": "1"})) as mock_dispatch,
        ):
            result = await handle_internal_mcp_rpc(request)

        assert result["jsonrpc"] == "2.0"
        forwarded_user = mock_dispatch.await_args.kwargs["user"]
        assert forwarded_user["email"] == "user@example.com"
        assert forwarded_user["is_admin"] is True
        assert request.state.token_teams == ["team-a"]
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    async def test_handle_internal_mcp_rpc_rejects_non_loopback_requests(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="10.0.0.2")

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_rpc(request)

        assert excinfo.value.status_code == 403

    async def test_handle_internal_mcp_rpc_rolls_back_on_dispatch_error(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._handle_rpc_authenticated", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_rpc(request)

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    async def test_handle_internal_mcp_rpc_skips_jsonrpc_model_validation(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": [],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.read"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        tool = MagicMock()
        tool.model_dump.return_value = {"name": "tool-1", "description": "desc", "inputSchema": {"type": "object"}}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main.RPCRequest", side_effect=AssertionError("trusted internal MCP dispatch should skip RPCRequest validation")),
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
        ):
            result = await handle_internal_mcp_rpc(request)

        assert result["result"]["tools"][0]["name"] == "tool-1"

    async def test_handle_internal_mcp_initialize_returns_jsonrpc_result(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "init-1", "method": "initialize", "params": {"session_id": "sess-1", "protocolVersion": "2025-11-25"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "mcp-session-id": "client-session-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        init_result = MagicMock()
        init_result.model_dump.return_value = {"protocolVersion": "2025-11-25", "capabilities": {}}
        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", AsyncMock(return_value="user@example.com"))
        handle_initialize_logic = AsyncMock(return_value=init_result)
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", handle_initialize_logic)

        response = await handle_internal_mcp_initialize(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "jsonrpc": "2.0",
            "id": "init-1",
            "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
        }
        handle_initialize_logic.assert_awaited_once_with(
            {"session_id": "sess-1", "protocolVersion": "2025-11-25"},
            session_id="sess-1",
            server_id="srv-1",
        )

    async def test_handle_internal_mcp_initialize_rejects_session_owner_mismatch(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "init-deny", "method": "initialize", "params": {"session_id": "sess-1", "protocolVersion": "2025-11-25"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", AsyncMock(return_value="other@example.com"))
        handle_initialize_logic = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", handle_initialize_logic)

        response = await handle_internal_mcp_initialize(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "jsonrpc": "2.0",
            "id": "init-deny",
            "error": {"code": -32003, "message": "Access denied", "data": {"method": "initialize"}},
        }
        handle_initialize_logic.assert_not_awaited()

    async def test_handle_internal_mcp_session_delete_cleans_up_session_state(self, monkeypatch):
        request = self._make_request({})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "mcp-session-id": "sess-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        remove_session = AsyncMock()
        cleanup_owner = AsyncMock()
        pool = MagicMock()
        pool.cleanup_streamable_http_session_owner = cleanup_owner
        monkeypatch.setattr("mcpgateway.main._validate_streamable_session_access", AsyncMock(return_value=(True, 200, "")))
        monkeypatch.setattr("mcpgateway.main.session_registry.remove_session", remove_session)
        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_session_affinity_enabled", True)

        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool):
            response = await handle_internal_mcp_session_delete(request)

        assert response.status_code == 204
        remove_session.assert_awaited_once_with("sess-1")
        cleanup_owner.assert_awaited_once_with("sess-1")

    async def test_handle_internal_mcp_session_delete_skips_python_validation_when_rust_validated(self, monkeypatch):
        request = self._make_request({})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "mcp-session-id": "sess-1",
            "x-contextforge-session-validated": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        remove_session = AsyncMock()
        monkeypatch.setattr("mcpgateway.main._validate_streamable_session_access", AsyncMock(side_effect=AssertionError("should not be called")))
        monkeypatch.setattr("mcpgateway.main.session_registry.remove_session", remove_session)
        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_session_affinity_enabled", False)

        response = await handle_internal_mcp_session_delete(request)

        assert response.status_code == 204
        remove_session.assert_awaited_once_with("sess-1")

    async def test_handle_internal_mcp_session_delete_requires_session_header(self):
        request = self._make_request({})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        response = await handle_internal_mcp_session_delete(request)

        assert response.status_code == 400
        assert json.loads(response.body.decode()) == {"detail": "mcp-session-id header is required"}

    async def test_handle_internal_mcp_notifications_initialized_returns_no_content(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        notify = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", notify)

        response = await handle_internal_mcp_notifications_initialized(request)

        assert response.status_code == 204
        notify.assert_awaited_once_with("Client initialized", LogLevel.INFO)

    async def test_handle_internal_mcp_notifications_initialized_rejects_wrong_method(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "notif-1", "method": "notifications/message", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        response = await handle_internal_mcp_notifications_initialized(request)

        assert response.status_code == 400
        assert json.loads(response.body.decode()) == {
            "jsonrpc": "2.0",
            "id": "notif-1",
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    async def test_handle_internal_mcp_notifications_message_returns_no_content(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "hello", "level": "info", "logger": "tests"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        notify = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", notify)

        response = await handle_internal_mcp_notifications_message(request)

        assert response.status_code == 204
        notify.assert_awaited_once_with("hello", LogLevel.INFO, "tests")

    async def test_handle_internal_mcp_notifications_message_rejects_wrong_method(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "notif-2", "method": "notifications/initialized", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        response = await handle_internal_mcp_notifications_message(request)

        assert response.status_code == 400
        assert json.loads(response.body.decode()) == {
            "jsonrpc": "2.0",
            "id": "notif-2",
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    async def test_handle_internal_mcp_notifications_cancelled_returns_no_content(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "run-1", "reason": "stop"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main._authorize_run_cancellation", AsyncMock())
        cancel_run = AsyncMock()
        notify = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.cancellation_service.cancel_run", cancel_run)
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", notify)

        response = await handle_internal_mcp_notifications_cancelled(request)

        assert response.status_code == 204
        cancel_run.assert_awaited_once_with("run-1", reason="stop")
        notify.assert_awaited_once_with("Request cancelled: run-1", LogLevel.INFO)

    async def test_handle_internal_mcp_notifications_cancelled_rejects_wrong_method(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "notif-3", "method": "notifications/initialized", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        response = await handle_internal_mcp_notifications_cancelled(request)

        assert response.status_code == 400
        assert json.loads(response.body.decode()) == {
            "jsonrpc": "2.0",
            "id": "notif-3",
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    async def test_handle_internal_mcp_resources_list_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resources-1", "method": "resources/list", "params": {"cursor": "cursor-1"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://one", "name": "Resource One"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], "next-1"))),
        ):
            response = await handle_internal_mcp_resources_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "resources": [{"uri": "resource://one", "name": "Resource One"}],
            "nextCursor": "next-1",
        }

    async def test_handle_internal_mcp_resources_read_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resources-read-1", "method": "resources/read", "params": {"uri": "resource://one", "requestId": "req-1"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://one", "text": "hello"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(return_value=resource)),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "contents": [{"uri": "resource://one", "text": "hello"}],
        }

    async def test_handle_internal_mcp_resources_read_normalizes_legacy_resource_content(self):
        # First-Party
        from mcpgateway.common.models import ResourceContent

        request = self._make_request({"jsonrpc": "2.0", "id": "resources-read-legacy", "method": "resources/read", "params": {"uri": "resource://legacy"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        resource = ResourceContent(
            type="resource",
            id="legacy-id",
            uri="resource://legacy",
            mime_type="text/plain",
            text="legacy-text",
        )
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(return_value=resource)),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "contents": [{"uri": "resource://legacy", "mimeType": "text/plain", "text": "legacy-text"}],
        }

    async def test_handle_internal_mcp_resource_templates_list_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resource-templates-1", "method": "resources/templates/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}", "name": "Resource Template"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
        ):
            response = await handle_internal_mcp_resource_templates_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "resourceTemplates": [{"uriTemplate": "resource://{id}", "name": "Resource Template"}],
        }

    async def test_handle_internal_mcp_resource_templates_list_scope_and_cleanup_paths(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resource-templates-2", "method": "resources/templates/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}"}

        ok_db = MagicMock()
        ok_db.is_active = True
        ok_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
        ):
            response = await handle_internal_mcp_resource_templates_list(request)
        assert response.status_code == 200

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_resource_templates_list(request)
        err_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_resources_subscribe_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resources-sub-1", "method": "resources/subscribe", "params": {"uri": "resource://one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_scoped_resource_access_context", return_value=("user@example.com", [])),
            patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(return_value=None)) as subscribe_resource,
        ):
            response = await handle_internal_mcp_resources_subscribe(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {}
        subscription = subscribe_resource.await_args.args[1]
        assert subscription.uri == "resource://one"
        assert subscription.subscriber_id == "user@example.com"

    async def test_handle_internal_mcp_resources_unsubscribe_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resources-unsub-1", "method": "resources/unsubscribe", "params": {"uri": "resource://one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.resource_service.unsubscribe_resource", new=AsyncMock(return_value=None)) as unsubscribe_resource,
        ):
            response = await handle_internal_mcp_resources_unsubscribe(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {}
        subscription = unsubscribe_resource.await_args.args[1]
        assert subscription.uri == "resource://one"
        assert subscription.subscriber_id == "user@example.com"

    async def test_handle_internal_mcp_resources_subscribe_and_unsubscribe_extra_error_paths(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceNotFoundError

        subscribe_request = self._make_request({"jsonrpc": "2.0", "id": "resources-sub-2", "method": "resources/subscribe", "params": []})
        subscribe_request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        subscribe_request.client = SimpleNamespace(host="127.0.0.1")

        missing_response = await handle_internal_mcp_resources_subscribe(subscribe_request)
        assert missing_response.status_code == 400

        subscribe_request.body = AsyncMock(return_value=json.dumps({"jsonrpc": "2.0", "id": "resources-sub-3", "method": "resources/subscribe", "params": {"uri": "resource://missing"}}).encode())
        with (
            patch("mcpgateway.main.SessionLocal", return_value=MagicMock()),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(side_effect=ResourceNotFoundError("missing"))),
        ):
            not_found_response = await handle_internal_mcp_resources_subscribe(subscribe_request)
        assert not_found_response.status_code == 404

        subscribe_request.body = AsyncMock(return_value=json.dumps({"jsonrpc": "2.0", "id": "resources-sub-4", "method": "resources/subscribe", "params": {"uri": "resource://one"}}).encode())
        subscribe_request.headers.pop("x-contextforge-server-id", None)
        with (
            patch("mcpgateway.main.SessionLocal", return_value=MagicMock()),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(side_effect=PermissionError("denied"))),
        ):
            denied_response = await handle_internal_mcp_resources_subscribe(subscribe_request)
        assert denied_response.status_code == 403

        subscribe_error_db = MagicMock()
        subscribe_error_db.rollback.side_effect = RuntimeError("rollback failed")
        subscribe_error_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=subscribe_error_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            error_response = await handle_internal_mcp_resources_subscribe(subscribe_request)
        assert error_response.status_code == 500
        subscribe_error_db.invalidate.assert_called_once()

        unsubscribe_request = self._make_request({"jsonrpc": "2.0", "id": "resources-unsub-2", "method": "resources/unsubscribe", "params": []})
        unsubscribe_request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        unsubscribe_request.client = SimpleNamespace(host="127.0.0.1")
        unsubscribe_missing = await handle_internal_mcp_resources_unsubscribe(unsubscribe_request)
        assert unsubscribe_missing.status_code == 400

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        unsubscribe_request.body = AsyncMock(return_value=json.dumps({"jsonrpc": "2.0", "id": "resources-unsub-3", "method": "resources/unsubscribe", "params": {"uri": "resource://one"}}).encode())
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main.resource_service.unsubscribe_resource", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            error_response = await handle_internal_mcp_resources_unsubscribe(unsubscribe_request)
        assert error_response.status_code == 500
        err_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_prompts_list_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "prompts-1", "method": "prompts/list", "params": {"cursor": "cursor-1"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-one", "description": "Prompt One"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.prompt_service.list_prompts", new=AsyncMock(return_value=([prompt], "next-prompt"))),
        ):
            response = await handle_internal_mcp_prompts_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "prompts": [{"name": "prompt-one", "description": "Prompt One"}],
            "nextCursor": "next-prompt",
        }

    async def test_handle_internal_mcp_prompts_get_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "prompts-get-1", "method": "prompts/get", "params": {"name": "prompt-one", "arguments": {"subject": "hi"}}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-one", "messages": [{"role": "user", "content": "hi"}]}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=prompt)),
        ):
            response = await handle_internal_mcp_prompts_get(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "name": "prompt-one",
            "messages": [{"role": "user", "content": "hi"}],
        }

    async def test_handle_internal_mcp_roots_list_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "roots-1", "method": "roots/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "admin@example.com",
                        "teams": None,
                        "is_authenticated": True,
                        "is_admin": True,
                        "permission_is_admin": True,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()
        root = MagicMock()
        root.model_dump.return_value = {"uri": "file:///tmp", "name": "tmp"}

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main.root_service.list_roots", new=AsyncMock(return_value=[root])),
        ):
            response = await handle_internal_mcp_roots_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "roots": [{"uri": "file:///tmp", "name": "tmp"}],
        }

    async def test_handle_internal_mcp_completion_complete_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "completion-1", "method": "completion/complete", "params": {"prompt": "hi"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(return_value={"completion": {"text": "done"}})),
        ):
            response = await handle_internal_mcp_completion_complete(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"completion": {"text": "done"}}

    async def test_handle_internal_mcp_completion_complete_returns_json_error_on_exception(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "completion-err-1", "method": "completion/complete", "params": {"prompt": "hi"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_completion_complete(request)

        assert response.status_code == 500
        assert json.loads(response.body.decode()) == {
            "code": -32000,
            "message": "Internal error",
            "data": "boom",
        }

    async def test_handle_internal_mcp_completion_complete_scope_and_cleanup_variants(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "completion-3", "method": "completion/complete", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        ok_db = MagicMock()
        ok_db.is_active = True
        ok_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(return_value={"completion": {"text": "ok"}})),
        ):
            response = await handle_internal_mcp_completion_complete(request)
        assert response.status_code == 200

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_completion_complete(request)
        assert response.status_code == 500
        err_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_roots_list_ignores_invalidate_failure_on_cleanup(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "roots-err", "method": "roots/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main.root_service.list_roots", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_roots_list(request)
        err_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_sampling_create_message_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "sampling-1", "method": "sampling/createMessage", "params": {"messages": []}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(return_value={"messages": [{"text": "ok"}]})),
        ):
            response = await handle_internal_mcp_sampling_create_message(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"messages": [{"text": "ok"}]}

    async def test_handle_internal_mcp_sampling_create_message_returns_json_error_on_exception(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "sampling-err-1", "method": "sampling/createMessage", "params": {"messages": []}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(side_effect=RuntimeError("sampling boom"))),
        ):
            response = await handle_internal_mcp_sampling_create_message(request)

        assert response.status_code == 500
        assert json.loads(response.body.decode()) == {
            "code": -32000,
            "message": "Internal error",
            "data": "sampling boom",
        }

    async def test_handle_internal_mcp_sampling_create_message_scope_and_jsonrpc_variants(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "sampling-3", "method": "sampling/createMessage", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        ok_db = MagicMock()
        ok_db.is_active = True
        ok_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(return_value={"messages": []})),
        ):
            response = await handle_internal_mcp_sampling_create_message(request)
        assert response.status_code == 200

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": "sampling/createMessage"}))),
        ):
            response = await handle_internal_mcp_sampling_create_message(request)
        assert response.status_code == 403

        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_sampling_create_message(request)
        assert response.status_code == 500
        err_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_logging_set_level_returns_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "logging-1", "method": "logging/setLevel", "params": {"level": "warning"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "admin@example.com",
                        "teams": None,
                        "is_authenticated": True,
                        "is_admin": True,
                        "permission_is_admin": True,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)),
        ):
            response = await handle_internal_mcp_logging_set_level(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {}

    async def test_handle_internal_mcp_logging_set_level_non_dict_params_and_cleanup_path(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "logging-2", "method": "logging/setLevel", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        ok_db = MagicMock()
        ok_db.is_active = True
        ok_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.LogLevel", lambda _value=None: "info"),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)),
        ):
            response = await handle_internal_mcp_logging_set_level(request)
        assert response.status_code == 200

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_logging_set_level(request)
        assert response.status_code == 500
        err_db.invalidate.assert_called_once()

    @pytest.mark.parametrize(
        ("handler", "method_name"),
        [
            (handle_internal_mcp_initialize, "initialize"),
            (handle_internal_mcp_notifications_initialized, "notifications/initialized"),
            (handle_internal_mcp_notifications_message, "notifications/message"),
            (handle_internal_mcp_notifications_cancelled, "notifications/cancelled"),
            (handle_internal_mcp_resources_list, "resources/list"),
            (handle_internal_mcp_resources_read, "resources/read"),
            (handle_internal_mcp_resources_subscribe, "resources/subscribe"),
            (handle_internal_mcp_resources_unsubscribe, "resources/unsubscribe"),
            (handle_internal_mcp_resource_templates_list, "resources/templates/list"),
            (handle_internal_mcp_roots_list, "roots/list"),
            (handle_internal_mcp_completion_complete, "completion/complete"),
            (handle_internal_mcp_sampling_create_message, "sampling/createMessage"),
            (handle_internal_mcp_logging_set_level, "logging/setLevel"),
            (handle_internal_mcp_prompts_list, "prompts/list"),
            (handle_internal_mcp_prompts_get, "prompts/get"),
        ],
    )
    async def test_internal_mcp_handlers_reject_parse_errors(self, handler, method_name):
        """Trusted internal handlers should return JSON-RPC parse errors on malformed bodies."""
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=b"{bad")
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.query_params = {}
        request.state = MagicMock()
        request.client = SimpleNamespace(host="127.0.0.1")

        if handler in {
            handle_internal_mcp_resources_list,
            handle_internal_mcp_resources_read,
            handle_internal_mcp_resources_subscribe,
            handle_internal_mcp_resources_unsubscribe,
            handle_internal_mcp_resource_templates_list,
            handle_internal_mcp_roots_list,
            handle_internal_mcp_completion_complete,
            handle_internal_mcp_sampling_create_message,
            handle_internal_mcp_logging_set_level,
            handle_internal_mcp_prompts_list,
            handle_internal_mcp_prompts_get,
        }:
            mock_db = MagicMock()
            mock_db.is_active = True
            mock_db.in_transaction.return_value = object()
            with patch("mcpgateway.main.SessionLocal", return_value=mock_db):
                response = await handler(request)
        else:
            response = await handler(request)

        assert response.status_code == 400, method_name
        assert json.loads(response.body.decode())["error"]["code"] == -32700

    @pytest.mark.parametrize(
        ("handler", "expected_method", "wrong_method"),
        [
            (handle_internal_mcp_initialize, "initialize", "tools/list"),
            (handle_internal_mcp_notifications_initialized, "notifications/initialized", "notifications/message"),
            (handle_internal_mcp_notifications_message, "notifications/message", "notifications/initialized"),
            (handle_internal_mcp_notifications_cancelled, "notifications/cancelled", "notifications/initialized"),
            (handle_internal_mcp_resources_list, "resources/list", "tools/list"),
            (handle_internal_mcp_resources_read, "resources/read", "resources/list"),
            (handle_internal_mcp_resources_subscribe, "resources/subscribe", "resources/unsubscribe"),
            (handle_internal_mcp_resources_unsubscribe, "resources/unsubscribe", "resources/subscribe"),
            (handle_internal_mcp_resource_templates_list, "resources/templates/list", "resources/list"),
            (handle_internal_mcp_roots_list, "roots/list", "tools/list"),
            (handle_internal_mcp_completion_complete, "completion/complete", "tools/list"),
            (handle_internal_mcp_sampling_create_message, "sampling/createMessage", "tools/list"),
            (handle_internal_mcp_logging_set_level, "logging/setLevel", "tools/list"),
            (handle_internal_mcp_prompts_list, "prompts/list", "tools/list"),
            (handle_internal_mcp_prompts_get, "prompts/get", "prompts/list"),
        ],
    )
    async def test_internal_mcp_handlers_reject_invalid_method(self, handler, expected_method, wrong_method):
        """Trusted internal handlers should reject unexpected JSON-RPC methods."""
        request = self._make_request({"jsonrpc": "2.0", "id": "bad-method", "method": wrong_method, "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        if handler in {
            handle_internal_mcp_resources_list,
            handle_internal_mcp_resources_read,
            handle_internal_mcp_resources_subscribe,
            handle_internal_mcp_resources_unsubscribe,
            handle_internal_mcp_resource_templates_list,
            handle_internal_mcp_roots_list,
            handle_internal_mcp_completion_complete,
            handle_internal_mcp_sampling_create_message,
            handle_internal_mcp_logging_set_level,
            handle_internal_mcp_prompts_list,
            handle_internal_mcp_prompts_get,
        }:
            mock_db = MagicMock()
            mock_db.is_active = True
            mock_db.in_transaction.return_value = object()
            with patch("mcpgateway.main.SessionLocal", return_value=mock_db):
                response = await handler(request)
        else:
            response = await handler(request)

        assert response.status_code == 400, expected_method
        assert json.loads(response.body.decode())["error"]["code"] == -32600

    @pytest.mark.parametrize(
        ("handler", "method_name", "params", "patch_target", "expected_payload"),
        [
            (
                handle_internal_mcp_resources_list,
                "resources/list",
                [],
                "mcpgateway.main.resource_service.list_resources",
                {"resources": [], "nextCursor": "next"},
            ),
            (
                handle_internal_mcp_resource_templates_list,
                "resources/templates/list",
                [],
                "mcpgateway.main.resource_service.list_resource_templates",
                {"resourceTemplates": []},
            ),
            (
                handle_internal_mcp_completion_complete,
                "completion/complete",
                [],
                "mcpgateway.main.completion_service.handle_completion",
                {"completion": {"text": "done"}},
            ),
            (
                handle_internal_mcp_sampling_create_message,
                "sampling/createMessage",
                [],
                "mcpgateway.main.sampling_handler.create_message",
                {"messages": []},
            ),
            (
                handle_internal_mcp_prompts_list,
                "prompts/list",
                [],
                "mcpgateway.main.prompt_service.list_prompts",
                {"prompts": [], "nextCursor": "next"},
            ),
        ],
    )
    async def test_internal_mcp_handlers_accept_non_dict_params(self, handler, method_name, params, patch_target, expected_payload):
        """Handlers should coerce non-dict params to {} and continue safely."""
        request = self._make_request({"jsonrpc": "2.0", "id": "params-1", "method": method_name, "params": params})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        patch_value = None
        if handler in {handle_internal_mcp_resources_list, handle_internal_mcp_prompts_list}:
            patch_value = ([], "next")
        elif handler is handle_internal_mcp_resource_templates_list:
            patch_value = []
        elif handler is handle_internal_mcp_completion_complete:
            patch_value = {"completion": {"text": "done"}}
        elif handler is handle_internal_mcp_sampling_create_message:
            patch_value = {"messages": []}

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main._get_scoped_resource_access_context", return_value=("user@example.com", [])),
            patch(patch_target, new=AsyncMock(return_value=patch_value)),
        ):
            response = await handler(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == expected_payload

    async def test_handle_internal_mcp_tools_list_returns_direct_definitions(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.read"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", ["team-a"], False)),
            patch(
                "mcpgateway.main.tool_service.list_server_mcp_tool_definitions",
                new=AsyncMock(return_value=[{"name": "echo", "inputSchema": {"type": "object"}, "annotations": {}}]),
            ) as mock_list_defs,
        ):
            response = await handle_internal_mcp_tools_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"tools": [{"name": "echo", "inputSchema": {"type": "object"}, "annotations": {}}]}
        assert mock_list_defs.await_args.args[1] == "srv-1"

    async def test_handle_internal_mcp_tools_list_authz_returns_no_content(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.read"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with patch("mcpgateway.main.SessionLocal", return_value=mock_db):
            response = await handle_internal_mcp_tools_list_authz(request)

        assert response.status_code == 204
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    async def test_handle_internal_mcp_tools_list_authz_skips_rbac_for_unauthenticated_public_only(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": None,
                        "teams": [],
                        "is_authenticated": False,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock(side_effect=AssertionError("RBAC should be skipped"))),
        ):
            response = await handle_internal_mcp_tools_list_authz(request)

        assert response.status_code == 204
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @pytest.mark.parametrize(
        "handler",
        [
            handle_internal_mcp_resources_list_authz,
            handle_internal_mcp_resources_read_authz,
            handle_internal_mcp_resource_templates_list_authz,
            handle_internal_mcp_prompts_list_authz,
            handle_internal_mcp_prompts_get_authz,
        ],
    )
    async def test_server_scoped_internal_mcp_authz_wrappers_return_no_content(self, handler):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "noop", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.get_plugin_manager", new=AsyncMock(return_value=None)),
        ):
            response = await handler(request)

        assert response.status_code == 204
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @pytest.mark.parametrize(
        ("handler", "hook_types", "expected_reason"),
        [
            (
                handle_internal_mcp_resources_read_authz,
                {
                    ResourceHookType.RESOURCE_PRE_FETCH,
                    ResourceHookType.RESOURCE_POST_FETCH,
                },
                "resource-hooks-configured",
            ),
            (
                handle_internal_mcp_prompts_get_authz,
                {
                    PromptHookType.PROMPT_PRE_FETCH,
                    PromptHookType.PROMPT_POST_FETCH,
                },
                "prompt-hooks-configured",
            ),
        ],
    )
    async def test_server_scoped_internal_mcp_authz_wrappers_return_forwarding_hint_when_hooks_active(
        self,
        handler,
        hook_types,
        expected_reason,
    ):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "noop", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()
        mock_plugin_manager = MagicMock()
        mock_plugin_manager.has_hooks_for.side_effect = lambda hook_type: hook_type in hook_types

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main.get_plugin_manager", new=AsyncMock(return_value=mock_plugin_manager)),
        ):
            response = await handler(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {
            "directExecutionEligible": False,
            "fallbackReason": expected_reason,
        }
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    async def test_server_scoped_internal_mcp_authz_wrapper_rolls_back_and_invalidates_on_error(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "noop", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_resources_list_authz(request)

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called_once()

    async def test_handle_internal_mcp_tools_list_rejects_scoped_server_mismatch(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-2",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.read"],
                        "scoped_server_id": "srv-1",
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_tools_list(request)

        assert excinfo.value.status_code == 403

    async def test_handle_internal_mcp_tools_list_requires_server_scope(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_tools_list(request)

        assert excinfo.value.status_code == 400

    async def test_handle_internal_mcp_tools_list_admin_public_and_cleanup_paths(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "tools-list-2", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        ok_db = MagicMock()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.tool_service.list_server_mcp_tool_definitions", new=AsyncMock(return_value=[])),
        ):
            response = await handle_internal_mcp_tools_list(request)
        assert response.status_code == 200

        request_public = self._make_request({"jsonrpc": "2.0", "id": "tools-list-3", "method": "tools/list", "params": {}})
        request_public.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request_public.client = SimpleNamespace(host="127.0.0.1")

        http_db = MagicMock()
        http_db.rollback.side_effect = RuntimeError("rollback failed")
        http_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=http_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=HTTPException(status_code=403, detail="denied"))),
        ):
            with pytest.raises(HTTPException):
                await handle_internal_mcp_tools_list(request_public)
        http_db.invalidate.assert_called_once()

        generic_db = MagicMock()
        generic_db.rollback.side_effect = RuntimeError("rollback failed")
        generic_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=generic_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.tool_service.list_server_mcp_tool_definitions", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_tools_list(request_public)
        assert response.status_code == 500
        generic_db.invalidate.assert_called_once()

        jsonrpc_db = MagicMock()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=jsonrpc_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": "tools/list"}))),
        ):
            response = await handle_internal_mcp_tools_list(request_public)
        assert response.status_code == 403
        assert json.loads(response.body.decode())["code"] == -32003

    async def test_handle_internal_mcp_tools_call_returns_jsonrpc_result(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "2", "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "hello"}}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.execute"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()
        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"content": [{"type": "text", "text": "ok"}], "isError": False}

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)) as mock_invoke_tool,
        ):
            result = await handle_internal_mcp_tools_call(request)

        assert result["jsonrpc"] == "2.0"
        assert result["result"]["content"][0]["text"] == "ok"
        assert mock_invoke_tool.await_args.kwargs["server_id"] == "srv-1"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called()

    async def test_handle_internal_mcp_tools_call_skips_rbac_for_unauthenticated_public_only(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "3", "method": "tools/call", "params": {"name": "echo", "arguments": {}}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": None,
                        "teams": [],
                        "is_authenticated": False,
                        "is_admin": False,
                        "permission_is_admin": False,
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()
        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"content": [{"type": "text", "text": "ok"}], "isError": False}

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock(side_effect=AssertionError("RBAC should be skipped"))),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)),
        ):
            result = await handle_internal_mcp_tools_call(request)

        assert result["result"]["content"][0]["text"] == "ok"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called()

    async def test_handle_internal_mcp_tools_call_returns_jsonrpc_not_found(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "4", "method": "tools/call", "params": {"name": "missing-tool", "arguments": {}}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": True,
                        "scoped_permissions": ["tools.execute"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ToolNotFoundError("Tool not found: missing-tool"))),
        ):
            result = await handle_internal_mcp_tools_call(request)

        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "4"
        assert result["error"]["code"] == -32601
        assert "Tool not found: missing-tool" in result["error"]["message"]
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called()

    async def test_handle_internal_mcp_tools_call_resolve_returns_jsonrpc_not_found(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resolve-1", "method": "tools/call", "params": {"name": "missing-tool", "arguments": {}}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "email": "user@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": True,
                        "is_admin": False,
                        "permission_is_admin": False,
                        "scoped_permissions": ["tools.execute"],
                    }
                ).encode()
            )
            .decode()
            .rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(side_effect=ToolNotFoundError("Tool not found: missing-tool"))),
        ):
            response = await handle_internal_mcp_tools_call_resolve(request)

        assert response.status_code == 404
        payload = json.loads(response.body)
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == "resolve-1"
        assert payload["error"]["code"] == -32601
        assert "Tool not found: missing-tool" in payload["error"]["message"]
        mock_db.close.assert_called()

    async def test_handle_internal_mcp_initialize_non_dict_params_returns_internal_error(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = self._make_request({"jsonrpc": "2.0", "id": "init-err", "method": "initialize", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr(main_mod, "_execute_rpc_initialize", AsyncMock(side_effect=RuntimeError("init boom")))

        response = await handle_internal_mcp_initialize(request)
        payload = json.loads(response.body.decode())

        assert payload["error"]["code"] == -32000
        assert payload["error"]["data"] == "init boom"

    async def test_handle_internal_mcp_initialize_generates_id_and_returns_jsonrpc_error(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "method": "initialize", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main._execute_rpc_initialize", AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": "initialize"})))

        response = await handle_internal_mcp_initialize(request)
        payload = json.loads(response.body.decode())

        assert payload["error"]["code"] == -32003
        assert payload["id"] is not None

    async def test_handle_internal_mcp_session_delete_denies_invalid_session_access(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "sess-del", "method": "delete", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "mcp-session-id": "sess-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main._validate_streamable_session_access", AsyncMock(return_value=(False, 403, "denied")))

        response = await handle_internal_mcp_session_delete(request)
        assert response.status_code == 403
        assert json.loads(response.body.decode())["detail"] == "denied"

    async def test_handle_internal_mcp_session_delete_ignores_pool_runtime_errors(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "sess-del", "method": "delete", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "mcp-session-id": "sess-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "_rust_session_validated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_session_affinity_enabled", True)
        monkeypatch.setattr("mcpgateway.main.session_registry.remove_session", AsyncMock(return_value=None))
        monkeypatch.setattr("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", MagicMock(side_effect=RuntimeError("pool unavailable")))

        response = await handle_internal_mcp_session_delete(request)
        assert response.status_code == 204

    async def test_handle_internal_mcp_notifications_initialized_re_raises_http_exception(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n1", "method": "notifications/initialized", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main._enforce_internal_mcp_server_scope", MagicMock(side_effect=HTTPException(status_code=403, detail="scope mismatch")))

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_notifications_initialized(request)

        assert excinfo.value.status_code == 403

    async def test_handle_internal_mcp_notifications_initialized_returns_internal_error_on_logging_failure(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n2", "method": "notifications/initialized", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        monkeypatch.setattr("mcpgateway.main.logging_service.notify", AsyncMock(side_effect=RuntimeError("notify boom")))

        response = await handle_internal_mcp_notifications_initialized(request)
        assert json.loads(response.body.decode())["error"]["data"] == "notify boom"

    async def test_handle_internal_mcp_notifications_message_accepts_non_dict_params(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n3", "method": "notifications/message", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        notify = AsyncMock(return_value=None)
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", notify)

        response = await handle_internal_mcp_notifications_message(request)
        assert response.status_code == 204
        assert notify.await_args.args[0] is None

    async def test_handle_internal_mcp_notifications_message_re_raises_http_exception(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n3b", "method": "notifications/message", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        monkeypatch.setattr("mcpgateway.main._enforce_internal_mcp_server_scope", MagicMock(side_effect=HTTPException(status_code=403, detail="scope mismatch")))

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_notifications_message(request)

        assert excinfo.value.status_code == 403

    async def test_handle_internal_mcp_notifications_cancelled_accepts_non_dict_params_and_returns_internal_error(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n4", "method": "notifications/cancelled", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", AsyncMock(side_effect=RuntimeError("cancel notify boom")))

        response = await handle_internal_mcp_notifications_cancelled(request)
        payload = json.loads(response.body.decode())
        assert payload["error"]["data"] == "cancel notify boom"

    async def test_handle_internal_mcp_resources_list_server_scope_admin_unrestricted(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "res-list", "method": "resources/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://one"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.resource_service.list_server_resources", new=AsyncMock(return_value=[resource])),
        ):
            response = await handle_internal_mcp_resources_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"resources": [{"uri": "resource://one"}]}

    async def test_handle_internal_mcp_resources_list_public_only_and_generic_cleanup_path(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "res-list-2", "method": "resources/list", "params": {"cursor": "c1"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://two"}

        list_db = MagicMock()
        list_db.is_active = True
        list_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=list_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], "next-cursor"))),
        ):
            response = await handle_internal_mcp_resources_list(request)
        assert json.loads(response.body.decode()) == {"resources": [{"uri": "resource://two"}], "nextCursor": "next-cursor"}

        error_db = MagicMock()
        error_db.rollback.side_effect = RuntimeError("rollback failed")
        error_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=error_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_resources_list(request)
        assert response.status_code == 500
        error_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_resources_read_server_scope_missing_uri(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "res-read", "method": "resources/read", "params": []})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 400
        assert json.loads(response.body.decode())["message"] == "Missing resource URI in parameters"

    async def test_handle_internal_mcp_resources_read_admin_unrestricted_with_plain_payload(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "res-read", "method": "resources/read", "params": {"uri": "resource://one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(return_value={"uri": "resource://one"})),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"contents": [{"uri": "resource://one"}]}

    async def test_handle_internal_mcp_resources_read_returns_not_found_payload(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceNotFoundError

        request = self._make_request({"jsonrpc": "2.0", "id": "res-read", "method": "resources/read", "params": {"uri": "resource://missing"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ResourceNotFoundError("missing"))),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 404
        assert json.loads(response.body.decode())["data"] == {"uri": "resource://missing"}

    async def test_handle_internal_mcp_resources_read_ignores_invalidate_failure_on_cleanup(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "res-read-err", "method": "resources/read", "params": {"uri": "resource://err"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 500
        mock_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_resources_read_returns_resource_error_payload(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceError

        request = self._make_request({"jsonrpc": "2.0", "id": "res-read-ambiguous", "method": "resources/read", "params": {"uri": "resource://dup"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch(
                "mcpgateway.main.resource_service.read_resource",
                new=AsyncMock(side_effect=ResourceError("Resource URI 'resource://dup' is ambiguous across multiple servers; use /servers/{id}/mcp.")),
            ),
        ):
            response = await handle_internal_mcp_resources_read(request)

        assert response.status_code == 400
        payload = json.loads(response.body.decode())
        assert payload["code"] == -32602
        assert payload["data"] == {"uri": "resource://dup"}

    async def test_handle_internal_mcp_prompts_list_server_scope_public_only_when_token_teams_missing(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "prompts-list", "method": "prompts/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-one"}
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.prompt_service.list_server_prompts", new=AsyncMock(return_value=[prompt])),
        ):
            response = await handle_internal_mcp_prompts_list(request)

        assert response.status_code == 200
        assert json.loads(response.body.decode()) == {"prompts": [{"name": "prompt-one"}]}

    async def test_handle_internal_mcp_prompts_list_admin_unrestricted_and_cleanup_path(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "prompts-list-2", "method": "prompts/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-two"}

        admin_db = MagicMock()
        admin_db.is_active = True
        admin_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=admin_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.prompt_service.list_prompts", new=AsyncMock(return_value=([prompt], "next"))),
        ):
            response = await handle_internal_mcp_prompts_list(request)
        assert json.loads(response.body.decode()) == {"prompts": [{"name": "prompt-two"}], "nextCursor": "next"}

        error_db = MagicMock()
        error_db.rollback.side_effect = RuntimeError("rollback failed")
        error_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=error_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.prompt_service.list_prompts", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_prompts_list(request)
        error_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_prompts_get_missing_name_and_not_found(self):
        # First-Party
        from mcpgateway.services.prompt_service import PromptError, PromptNotFoundError

        request_missing = self._make_request({"jsonrpc": "2.0", "id": "prompt-get", "method": "prompts/get", "params": []})
        request_missing.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request_missing.client = SimpleNamespace(host="127.0.0.1")
        request_missing.state = MagicMock()
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
        ):
            response = await handle_internal_mcp_prompts_get(request_missing)

        assert response.status_code == 400
        assert json.loads(response.body.decode())["message"] == "Missing prompt name in parameters"

        request_not_found = self._make_request({"jsonrpc": "2.0", "id": "prompt-get", "method": "prompts/get", "params": {"name": "missing"}})
        request_not_found.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request_not_found.client = SimpleNamespace(host="127.0.0.1")
        request_not_found.state = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(side_effect=PromptNotFoundError("missing"))),
        ):
            response = await handle_internal_mcp_prompts_get(request_not_found)

        assert response.status_code == 404
        assert json.loads(response.body.decode())["data"] == {"name": "missing"}

        request_invalid = self._make_request({"jsonrpc": "2.0", "id": "prompt-get", "method": "prompts/get", "params": {"name": "broken"}})
        request_invalid.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com"}).encode()).decode().rstrip("="),
        }
        request_invalid.client = SimpleNamespace(host="127.0.0.1")
        request_invalid.state = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "admin@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(side_effect=PromptError("bad prompt arguments"))),
        ):
            response = await handle_internal_mcp_prompts_get(request_invalid)

        assert response.status_code == 422
        body = json.loads(response.body.decode())
        assert body["message"] == "bad prompt arguments"
        assert body["data"] == {"name": "broken"}

    async def test_handle_internal_mcp_prompts_get_public_only_and_generic_cleanup_path(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "prompt-get-2", "method": "prompts/get", "params": {"name": "prompt-one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        request.state = MagicMock()

        ok_db = MagicMock()
        ok_db.is_active = True
        ok_db.in_transaction.return_value = object()
        payload = MagicMock()
        payload.model_dump.return_value = {"name": "prompt-one", "template": "hi"}
        with (
            patch("mcpgateway.main.SessionLocal", return_value=ok_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=payload)),
        ):
            response = await handle_internal_mcp_prompts_get(request)
        assert json.loads(response.body.decode())["name"] == "prompt-one"

        err_db = MagicMock()
        err_db.rollback.side_effect = RuntimeError("rollback failed")
        err_db.invalidate.side_effect = RuntimeError("invalidate failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=err_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_prompts_get(request)
        err_db.invalidate.assert_called_once()

    @pytest.mark.parametrize(
        ("handler", "method_name"),
        [
            (handle_internal_mcp_resources_list, "resources/list"),
            (handle_internal_mcp_resources_read, "resources/read"),
            (handle_internal_mcp_resources_subscribe, "resources/subscribe"),
            (handle_internal_mcp_resources_unsubscribe, "resources/unsubscribe"),
            (handle_internal_mcp_resource_templates_list, "resources/templates/list"),
            (handle_internal_mcp_roots_list, "roots/list"),
            (handle_internal_mcp_completion_complete, "completion/complete"),
            (handle_internal_mcp_logging_set_level, "logging/setLevel"),
            (handle_internal_mcp_prompts_list, "prompts/list"),
            (handle_internal_mcp_prompts_get, "prompts/get"),
        ],
    )
    async def test_internal_mcp_handlers_return_jsonrpc_errors_from_authorization(self, handler, method_name):
        request = self._make_request({"jsonrpc": "2.0", "id": "rpc-1", "method": method_name, "params": {"uri": "resource://one", "name": "prompt-one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.query_params = {}
        request.state = MagicMock()
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": method_name}))),
        ):
            response = await handler(request)

        assert response.status_code == 403

    @pytest.mark.parametrize(
        ("handler", "method_name", "patch_target", "raises"),
        [
            (handle_internal_mcp_resources_list, "resources/list", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_resources_read, "resources/read", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_resources_subscribe, "resources/subscribe", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_resources_unsubscribe, "resources/unsubscribe", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_resource_templates_list, "resources/templates/list", "mcpgateway.main._authorize_internal_mcp_request", True),
            (handle_internal_mcp_roots_list, "roots/list", "mcpgateway.main._authorize_internal_mcp_request", True),
            (handle_internal_mcp_completion_complete, "completion/complete", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_sampling_create_message, "sampling/createMessage", "mcpgateway.main.sampling_handler.create_message", False),
            (handle_internal_mcp_logging_set_level, "logging/setLevel", "mcpgateway.main._authorize_internal_mcp_request", False),
            (handle_internal_mcp_prompts_list, "prompts/list", "mcpgateway.main._authorize_internal_mcp_request", True),
            (handle_internal_mcp_prompts_get, "prompts/get", "mcpgateway.main._authorize_internal_mcp_request", True),
        ],
    )
    async def test_internal_mcp_handlers_rollback_and_handle_generic_errors(self, handler, method_name, patch_target, raises):
        request = self._make_request({"jsonrpc": "2.0", "id": "rpc-2", "method": method_name, "params": {"uri": "resource://one", "name": "prompt-one"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.query_params = {}
        request.state = MagicMock()
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")

        with patch("mcpgateway.main.SessionLocal", return_value=mock_db), patch(patch_target, new=AsyncMock(side_effect=RuntimeError("boom"))):
            if raises:
                with pytest.raises(RuntimeError, match="boom"):
                    await handler(request)
            else:
                response = await handler(request)
                assert response.status_code == 500

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_tools_call_returns_forwarded_affinity_response(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "aff-1", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new=AsyncMock(return_value={"jsonrpc": "2.0", "result": {"ok": True}, "id": "aff-1"})),
        ):
            result = await handle_internal_mcp_tools_call(request)

        assert result == {"jsonrpc": "2.0", "result": {"ok": True}, "id": "aff-1"}

    async def test_handle_internal_mcp_tools_call_rolls_back_and_invalidates_on_unexpected_error(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "aff-2", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main._execute_rpc_tools_call", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_tools_call(request)

        mock_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_tools_call_resolve_returns_jsonrpc_error_and_rolls_back(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resolve-2", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": "tools/call"}))),
        ):
            response = await handle_internal_mcp_tools_call_resolve(request)

        assert response.status_code == 403
        payload = json.loads(response.body.decode())
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == "resolve-2"
        assert payload["error"]["code"] == -32003
        assert payload["error"]["message"] == "Access denied"
        assert payload["error"]["data"] == {"method": "tools/call"}

    async def test_handle_internal_mcp_tools_call_resolve_commits_success_and_invalidates_on_error(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resolve-3", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        success_db = MagicMock()
        success_db.is_active = True
        success_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=success_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(return_value={"eligible": True})),
        ):
            response = await handle_internal_mcp_tools_call_resolve(request)
        assert response.status_code == 200
        success_db.commit.assert_called_once()

        error_db = MagicMock()
        error_db.rollback.side_effect = RuntimeError("rollback failed")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=error_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(side_effect=RuntimeError("resolve boom"))),
        ):
            with pytest.raises(RuntimeError, match="resolve boom"):
                await handle_internal_mcp_tools_call_resolve(request)
        error_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_rpc_rolls_back_and_invalidates_on_error(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "rpc-rollback", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._handle_rpc_authenticated", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_rpc(request)

        mock_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_rpc_ignores_invalidate_failure_on_cleanup(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "rpc-rollback", "method": "tools/list", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._handle_rpc_authenticated", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_rpc(request)

        mock_db.invalidate.assert_called_once()

    async def test_handle_internal_mcp_notifications_message_returns_internal_error_on_logging_failure(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n5", "method": "notifications/message", "params": {"level": "info"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        monkeypatch.setattr("mcpgateway.main.logging_service.notify", AsyncMock(side_effect=RuntimeError("message boom")))

        response = await handle_internal_mcp_notifications_message(request)
        assert json.loads(response.body.decode())["error"]["data"] == "message boom"

    async def test_handle_internal_mcp_notifications_cancelled_re_raises_http_exception(self, monkeypatch):
        request = self._make_request({"jsonrpc": "2.0", "id": "n6", "method": "notifications/cancelled", "params": {"requestId": "req-1"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        monkeypatch.setattr("mcpgateway.main._enforce_internal_mcp_server_scope", MagicMock(side_effect=HTTPException(status_code=403, detail="scope mismatch")))

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_notifications_cancelled(request)

        assert excinfo.value.status_code == 403

    async def test_handle_internal_mcp_tools_call_rejects_parse_error_invalid_method_and_missing_tool_name(self):
        parse_request = MagicMock(spec=Request)
        parse_request.body = AsyncMock(return_value=b"{bad")
        parse_request.headers = {"x-contextforge-mcp-runtime": "rust", "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("=")}
        parse_request.query_params = {}
        parse_request.state = MagicMock()
        parse_request.client = SimpleNamespace(host="127.0.0.1")

        parse_response = await handle_internal_mcp_tools_call(parse_request)
        assert parse_response.status_code == 400
        assert json.loads(parse_response.body.decode())["error"]["code"] == -32700

        invalid_request = self._make_request({"jsonrpc": "2.0", "id": "bad-method", "method": "tools/list", "params": {}})
        invalid_request.headers = parse_request.headers
        invalid_request.client = parse_request.client
        invalid_result = await handle_internal_mcp_tools_call(invalid_request)
        assert json.loads(invalid_result.body.decode())["error"]["code"] == -32600

        missing_name_request = self._make_request({"jsonrpc": "2.0", "id": "missing-name", "method": "tools/call", "params": []})
        missing_name_request.headers = parse_request.headers
        missing_name_request.client = parse_request.client
        missing_name_result = await handle_internal_mcp_tools_call(missing_name_request)
        assert missing_name_result["error"]["code"] == -32602

    async def test_handle_internal_mcp_tools_call_generates_id_and_reraises_plugin_error_while_ignoring_close_failures(self):
        request = self._make_request({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.in_transaction.return_value = object()
        mock_db.close.side_effect = [None, RuntimeError("close failed")]

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main._execute_rpc_tools_call", new=AsyncMock(side_effect=PluginError(MagicMock(message="plugin boom")))),
        ):
            with pytest.raises(PluginError):
                await handle_internal_mcp_tools_call(request)

    async def test_handle_internal_mcp_tools_call_resolve_rejects_parse_error_invalid_method_missing_name_and_tool_error(self):
        base_headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }

        parse_request = MagicMock(spec=Request)
        parse_request.body = AsyncMock(return_value=b"{bad")
        parse_request.headers = base_headers
        parse_request.query_params = {}
        parse_request.state = MagicMock()
        parse_request.client = SimpleNamespace(host="127.0.0.1")
        parse_response = await handle_internal_mcp_tools_call_resolve(parse_request)
        assert parse_response.status_code == 400
        assert json.loads(parse_response.body.decode())["error"]["code"] == -32700

        invalid_request = self._make_request({"jsonrpc": "2.0", "id": "bad-method", "method": "tools/list", "params": {}})
        invalid_request.headers = base_headers
        invalid_request.client = parse_request.client
        invalid_response = await handle_internal_mcp_tools_call_resolve(invalid_request)
        assert invalid_response.status_code == 400
        assert json.loads(invalid_response.body.decode())["error"]["code"] == -32600

        missing_name_request = self._make_request({"jsonrpc": "2.0", "id": "missing-name", "method": "tools/call", "params": []})
        missing_name_request.headers = base_headers
        missing_name_request.client = parse_request.client
        missing_name_response = await handle_internal_mcp_tools_call_resolve(missing_name_request)
        assert missing_name_response.status_code == 400
        assert json.loads(missing_name_response.body.decode())["error"]["code"] == -32602

        tool_error_request = self._make_request({"jsonrpc": "2.0", "id": "tool-error", "method": "tools/call", "params": {"name": "echo"}})
        tool_error_request.headers = base_headers
        tool_error_request.client = parse_request.client
        mock_db = MagicMock()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(side_effect=ToolError("tool boom"))),
        ):
            tool_error_response = await handle_internal_mcp_tools_call_resolve(tool_error_request)
        assert tool_error_response.status_code == 400
        assert json.loads(tool_error_response.body.decode())["error"]["code"] == -32000

    async def test_handle_internal_mcp_tools_call_resolve_scope_and_filter_context_variants(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "resolve-scope", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "admin@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        admin_db = MagicMock()
        admin_db.is_active = True
        admin_db.in_transaction.return_value = object()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=admin_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@example.com", None, True)),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(return_value={"eligible": True})),
        ):
            response = await handle_internal_mcp_tools_call_resolve(request)
        assert response.status_code == 200

        public_db = MagicMock()
        public_db.rollback.side_effect = RuntimeError("rollback failed")
        public_db.invalidate.side_effect = RuntimeError("invalidate failed")
        request_no_scope = self._make_request({"jsonrpc": "2.0", "id": "resolve-scope-2", "method": "tools/call", "params": {"name": "echo"}})
        request_no_scope.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request_no_scope.client = SimpleNamespace(host="127.0.0.1")
        with (
            patch("mcpgateway.main.SessionLocal", return_value=public_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(side_effect=RuntimeError("resolve boom"))),
        ):
            with pytest.raises(RuntimeError, match="resolve boom"):
                await handle_internal_mcp_tools_call_resolve(request_no_scope)
        public_db.invalidate.assert_called_once()

    async def test_internal_mcp_tools_call_resolve_re_raises_plugin_errors_and_ignores_close_failures(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "plugin-err", "method": "tools/call", "params": {"name": "echo"}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com", "is_authenticated": True}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.close.side_effect = RuntimeError("close failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._ensure_rpc_permission", new=AsyncMock()),
            patch("mcpgateway.main.tool_service.prepare_rust_mcp_tool_execution", new=AsyncMock(side_effect=PluginError(MagicMock(message="plugin boom")))),
        ):
            with pytest.raises(PluginError):
                await handle_internal_mcp_tools_call_resolve(request)

    async def test_server_scoped_authz_missing_server_scope_and_jsonrpc_error(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "authz", "method": "noop", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")

        with pytest.raises(HTTPException) as excinfo:
            await handle_internal_mcp_resources_list_authz(request)
        assert excinfo.value.status_code == 400

        request.headers["x-contextforge-server-id"] = "srv-1"
        mock_db = MagicMock()
        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=JSONRPCError(-32003, "Access denied", {"method": "resources/list"}))),
        ):
            response = await handle_internal_mcp_resources_list_authz(request)

        assert response.status_code == 403

    async def test_server_scoped_authz_ignores_invalidate_failure_on_cleanup(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "authz", "method": "noop", "params": {}})
        request.headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-server-id": "srv-1",
            "x-contextforge-auth-context": base64.urlsafe_b64encode(json.dumps({"email": "user@example.com"}).encode()).decode().rstrip("="),
        }
        request.client = SimpleNamespace(host="127.0.0.1")
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate.side_effect = RuntimeError("invalidate failed")

        with (
            patch("mcpgateway.main.SessionLocal", return_value=mock_db),
            patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await handle_internal_mcp_resources_list_authz(request)

        mock_db.invalidate.assert_called_once()

    async def test_handle_rpc_uses_scoped_server_id_from_internal_auth_and_denies_wrong_server(self):
        request = self._make_request({"jsonrpc": "2.0", "id": "rpc-scoped", "method": "tools/list", "params": []})
        request.state._jwt_verified_payload = None
        request.state._mcp_internal_auth_context = {"scoped_server_id": "srv-1"}

        with (
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.tool_service.list_server_mcp_tool_definitions", new=AsyncMock(return_value=[])),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})

        assert result["result"]["tools"] == []

        denied_request = self._make_request({"jsonrpc": "2.0", "id": "rpc-denied", "method": "tools/list", "params": {"server_id": "srv-2"}})
        denied_request.state._jwt_verified_payload = ("fake", {"scopes": {"server_id": "srv-1"}})
        denied_request.state._mcp_internal_auth_context = None

        denied_result = await handle_rpc(denied_request, db=MagicMock(), user={"email": "user@example.com"})
        assert denied_result.status_code == 403

    async def test_handle_rpc_list_tools_with_cursor(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
        request = self._make_request(payload)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-2"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], "next-cursor"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["nextCursor"] == "next-cursor"

    async def test_handle_rpc_list_gateways(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "list_gateways", "params": {}}
        request = self._make_request(payload)

        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([gateway], None))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["gateways"][0]["id"] == "gw-1"

    async def test_handle_rpc_list_roots_requires_admin_permission(self):
        payload = {"jsonrpc": "2.0", "id": "roots-1", "method": "list_roots", "params": {}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=False)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32003
            assert "Access denied" in result["error"]["message"]

    async def test_handle_rpc_list_roots_short_circuits_permission_admin(self):
        payload = {"jsonrpc": "2.0", "id": "roots-admin", "method": "list_roots", "params": {}}
        request = self._make_request(payload)

        with (
            patch("mcpgateway.main.root_service.list_roots", new=AsyncMock(return_value=[])),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(side_effect=AssertionError("RBAC lookup should be skipped for admins"))),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "admin@example.com", "is_admin": True, "permission_is_admin": True})

        assert result["result"]["roots"] == []

    async def test_handle_rpc_roots_list_requires_admin_permission(self):
        payload = {"jsonrpc": "2.0", "id": "roots-2", "method": "roots/list", "params": {}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=False)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32003

    async def test_handle_rpc_admin_short_circuit_still_honors_token_scope_cap(self):
        payload = {"jsonrpc": "2.0", "id": "roots-scope", "method": "roots/list", "params": {}}
        request = self._make_request(payload)
        request.state._mcp_internal_auth_context = {"scoped_permissions": ["tools.read"]}

        with patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(side_effect=AssertionError("RBAC lookup should not run when token scope already denies"))):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "admin@example.com", "is_admin": True})

        assert result["error"]["code"] == -32003

    async def test_handle_rpc_resources_read_missing_uri(self):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "resources/read", "params": {}}
        request = self._make_request(payload)

        with patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result

    async def test_handle_rpc_resources_list_with_cursor(self):
        payload = {"jsonrpc": "2.0", "id": "2", "method": "resources/list", "params": {}}
        request = self._make_request(payload)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], "next-cursor"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["resources"][0]["id"] == "res-1"
            assert result["result"]["nextCursor"] == "next-cursor"

    async def test_handle_rpc_resources_read_success_and_error(self):
        payload = {"jsonrpc": "2.0", "id": "3", "method": "resources/read", "params": {"uri": "resource://one"}}
        request = self._make_request(payload)
        request.state = MagicMock()

        resource = MagicMock()
        resource.model_dump.return_value = {"uri": "resource://one"}

        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(return_value=resource)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["contents"][0]["uri"] == "resource://one"

        # Gateway forwarding is removed, so missing resource returns error
        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result
            assert result["error"]["code"] == -32002

    async def test_handle_rpc_resources_subscribe_unsubscribe(self):
        payload = {"jsonrpc": "2.0", "id": "4", "method": "resources/subscribe", "params": {"uri": "resource://two"}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request, db=MagicMock(), user="user")
            assert result["result"] == {}

        payload_unsub = {"jsonrpc": "2.0", "id": "5", "method": "resources/unsubscribe", "params": {"uri": "resource://two"}}
        request_unsub = self._make_request(payload_unsub)
        with patch("mcpgateway.main.resource_service.unsubscribe_resource", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request_unsub, db=MagicMock(), user="user")
            assert result["result"] == {}

    async def test_handle_rpc_resources_subscribe_permission_denied(self):
        payload = {"jsonrpc": "2.0", "id": "4a", "method": "resources/subscribe", "params": {"uri": "resource://two"}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(side_effect=PermissionError("denied"))):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32003

    async def test_handle_rpc_resources_subscribe_accepts_email_subscriber_id(self):
        payload = {"jsonrpc": "2.0", "id": "4b", "method": "resources/subscribe", "params": {"uri": "resource://two"}}
        request = self._make_request(payload)

        with patch("mcpgateway.main.resource_service.subscribe_resource", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user+alerts@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_prompts_list_and_get(self):
        payload = {"jsonrpc": "2.0", "id": "6", "method": "prompts/list", "params": {"server_id": "srv"}}
        request = self._make_request(payload)

        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-1"}
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.prompt_service.list_server_prompts", new=AsyncMock(return_value=[prompt])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["prompts"][0]["name"] == "prompt-1"

        payload_get = {"jsonrpc": "2.0", "id": "7", "method": "prompts/get", "params": {"name": "prompt-1"}}
        request_get = self._make_request(payload_get)
        request_get.state = MagicMock()
        prompt_payload = MagicMock()
        prompt_payload.model_dump.return_value = {"name": "prompt-1", "template": "hi"}

        with (
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=prompt_payload)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request_get, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["name"] == "prompt-1"

    async def test_handle_rpc_ping_and_resource_templates(self):
        payload = {"jsonrpc": "2.0", "id": "8", "method": "ping", "params": {}}
        request = self._make_request(payload)
        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

        payload_templates = {"jsonrpc": "2.0", "id": "9", "method": "resources/templates/list", "params": {}}
        request_templates = self._make_request(payload_templates)
        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}"}

        with (
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request_templates, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resourceTemplates"][0]["uriTemplate"] == "resource://{id}"

    async def test_handle_rpc_tools_call(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "10", "method": "tools/call", "params": {"name": "tool-1", "arguments": {"a": 1}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", False)

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

    async def test_handle_rpc_tools_call_requires_execute_permission(self):
        payload = {"jsonrpc": "2.0", "id": "10b", "method": "tools/call", "params": {"name": "tool-1", "arguments": {"a": 1}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=False)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value={"ok": True})) as invoke_tool,
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})

        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]
        invoke_tool.assert_not_awaited()

    async def test_handle_rpc_backward_compat_tool_requires_execute_permission(self):
        payload = {"jsonrpc": "2.0", "id": "10c", "method": "legacy-tool", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=False)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value={"ok": True})) as invoke_tool,
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})

        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]
        invoke_tool.assert_not_awaited()

    async def test_handle_rpc_backward_compat_tool_allows_when_authorized(self):
        payload = {"jsonrpc": "2.0", "id": "10d", "method": "legacy-tool", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", [], False)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value={"ok": True})) as invoke_tool,
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})

        assert result["result"]["ok"] is True
        assert invoke_tool.await_args.kwargs["name"] == "legacy-tool"
        assert invoke_tool.await_args.kwargs["arguments"] == {"a": 1}

    async def test_handle_rpc_notifications_and_sampling(self):
        payload_cancel = {"jsonrpc": "2.0", "id": "11", "method": "notifications/cancelled", "params": {"requestId": "r1", "reason": "stop"}}
        request_cancel = self._make_request(payload_cancel)

        with (
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"owner_email": "user@example.com", "owner_team_ids": []})),
            patch("mcpgateway.main.cancellation_service.cancel_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_cancel, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

        payload_msg = {"jsonrpc": "2.0", "id": "12", "method": "notifications/message", "params": {"data": "hello", "level": "info", "logger": "tests"}}
        request_msg = self._make_request(payload_msg)
        with patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)):
            result = await handle_rpc(request_msg, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

        payload_sampling = {"jsonrpc": "2.0", "id": "13", "method": "sampling/createMessage", "params": {"messages": []}}
        request_sampling = self._make_request(payload_sampling)
        with patch("mcpgateway.main.sampling_handler.create_message", new=AsyncMock(return_value={"text": "ok"})):
            result = await handle_rpc(request_sampling, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["text"] == "ok"

    async def test_handle_rpc_elicitation_completion_logging(self, monkeypatch):
        payload = {
            "jsonrpc": "2.0",
            "id": "14",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        }
        request = self._make_request(payload)
        request.state = MagicMock()

        class _Pending:
            def __init__(self, downstream_session_id: str, request_id: str):
                self.downstream_session_id = downstream_session_id
                self.request_id = request_id

        class _Result:
            def model_dump(self, **_kwargs):
                return {"status": "ok"}

        class _ElicitationService:
            def __init__(self):
                self._pending = {"p1": _Pending("sess-1", "req-1")}

            async def create_elicitation(self, **_kwargs):
                return _Result()

        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_ElicitationService()),
            patch("mcpgateway.main.session_registry.get_elicitation_capable_sessions", new=AsyncMock(return_value=["sess-1"])),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["status"] == "ok"

        payload_completion = {"jsonrpc": "2.0", "id": "15", "method": "completion/complete", "params": {"prompt": "hi"}}
        request_completion = self._make_request(payload_completion)
        with patch("mcpgateway.main.completion_service.handle_completion", new=AsyncMock(return_value={"text": "done"})):
            result = await handle_rpc(request_completion, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["text"] == "done"

        payload_logging = {"jsonrpc": "2.0", "id": "16", "method": "logging/setLevel", "params": {"level": "info"}}
        request_logging = self._make_request(payload_logging)
        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_logging, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_logging_set_level_requires_admin_permission(self):
        payload_logging = {"jsonrpc": "2.0", "id": "16", "method": "logging/setLevel", "params": {"level": "info"}}
        request_logging = self._make_request(payload_logging)

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=False)),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)) as set_level,
        ):
            result = await handle_rpc(request_logging, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32003
            assert "Access denied" in result["error"]["message"]
            set_level.assert_not_awaited()

    async def test_handle_rpc_logging_set_level_populates_email_when_missing(self):
        payload_logging = {"jsonrpc": "2.0", "id": "17", "method": "logging/setLevel", "params": {"level": "info"}}
        request_logging = self._make_request(payload_logging)

        with (
            patch("mcpgateway.main.get_user_email", return_value="fallback@example.com") as get_user_email,
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.logging_service.set_level", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_logging, db=MagicMock(), user={"sub": "user@example.com"})
            assert result["result"] == {}
            get_user_email.assert_called_once_with({"sub": "user@example.com"})

    async def test_handle_rpc_fallback_tool_error(self):
        payload = {"jsonrpc": "2.0", "id": "17", "method": "custom/tool", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

        # Gateway forwarding is removed, so missing tool returns error
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

    async def test_handle_rpc_user_object_and_auto_id(self):
        payload = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        request = self._make_request(payload)

        class _User:
            email = "user@example.com"

        result = await handle_rpc(request, db=MagicMock(), user=_User())
        assert result["result"] == {}
        assert result["id"] is not None

    async def test_handle_rpc_admin_bypass_variants(self):
        payload = {"jsonrpc": "2.0", "id": "18", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        mock_db = MagicMock()

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([], None))) as list_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            list_tools.assert_called_once()

        payload_legacy = {"jsonrpc": "2.0", "id": "19", "method": "list_tools", "params": {"server_id": "srv"}}
        request_legacy = self._make_request(payload_legacy)
        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-legacy"}

        with (
            patch("mcpgateway.main.tool_service.list_server_tools", new=AsyncMock(return_value=[tool])) as list_server_tools,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_legacy, db=MagicMock(), user={"email": "user@example.com"})
            list_server_tools.assert_called_once()
            assert result["result"]["tools"][0]["id"] == "tool-legacy"

    async def test_handle_rpc_resources_admin_bypass_and_missing_uri(self):
        payload_list = {"jsonrpc": "2.0", "id": "20", "method": "resources/list", "params": {}}
        request_list = self._make_request(payload_list)
        resource = MagicMock()
        resource.model_dump.return_value = {"id": "res-admin"}

        with (
            patch("mcpgateway.main.resource_service.list_resources", new=AsyncMock(return_value=([resource], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_list, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resources"][0]["id"] == "res-admin"

        payload_missing = {"jsonrpc": "2.0", "id": "21", "method": "resources/subscribe", "params": {}}
        request_missing = self._make_request(payload_missing)
        result = await handle_rpc(request_missing, db=MagicMock(), user="user")
        assert result["error"]["code"] == -32602

        payload_missing_unsub = {"jsonrpc": "2.0", "id": "22", "method": "resources/unsubscribe", "params": {}}
        request_missing_unsub = self._make_request(payload_missing_unsub)
        result = await handle_rpc(request_missing_unsub, db=MagicMock(), user="user")
        assert result["error"]["code"] == -32602

    async def test_handle_rpc_resources_read_admin_error_on_missing(self):
        payload = {"jsonrpc": "2.0", "id": "23", "method": "resources/read", "params": {"uri": "resource://admin"}}
        request = self._make_request(payload)
        request.state = MagicMock()

        # Gateway forwarding is removed, so missing resource returns error
        with (
            patch("mcpgateway.main.resource_service.read_resource", new=AsyncMock(side_effect=ValueError("no local"))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" in result
            assert result["error"]["code"] == -32002

    async def test_handle_rpc_prompts_admin_bypass_and_missing_name(self):
        payload_list = {"jsonrpc": "2.0", "id": "24", "method": "prompts/list", "params": {}}
        request_list = self._make_request(payload_list)
        prompt = MagicMock()
        prompt.model_dump.return_value = {"name": "prompt-admin"}

        with (
            patch("mcpgateway.main.prompt_service.list_prompts", new=AsyncMock(return_value=([prompt], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_list, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["prompts"][0]["name"] == "prompt-admin"

        payload_missing = {"jsonrpc": "2.0", "id": "25", "method": "prompts/get", "params": {}}
        request_missing = self._make_request(payload_missing)
        request_missing.state = MagicMock()
        result = await handle_rpc(request_missing, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload_get = {"jsonrpc": "2.0", "id": "26", "method": "prompts/get", "params": {"name": "prompt-admin"}}
        request_get = self._make_request(payload_get)
        request_get.state = MagicMock()
        prompt_payload = MagicMock()
        prompt_payload.model_dump.return_value = {"name": "prompt-admin"}

        with (
            patch("mcpgateway.main.prompt_service.get_prompt", new=AsyncMock(return_value=prompt_payload)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_get, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["name"] == "prompt-admin"

    async def test_handle_rpc_tools_call_missing_name_and_cancel(self, monkeypatch):
        payload_missing = {"jsonrpc": "2.0", "id": "27", "method": "tools/call", "params": {}}
        request_missing = self._make_request(payload_missing)
        request_missing.state = MagicMock()
        result = await handle_rpc(request_missing, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload = {"jsonrpc": "2.0", "id": "28", "method": "tools/call", "params": {"name": "tool-cancel", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"cancelled": True})),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value={"ok": True})),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32800

    async def test_handle_rpc_tools_call_cancel_after_creation(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "29", "method": "tools/call", "params": {"name": "tool-cancel", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        async def _slow_tool(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return {"ok": True}

        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(side_effect=[None, {"cancelled": True}])),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=_slow_tool)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32800

    async def test_handle_rpc_resource_templates_admin_and_notifications_other(self):
        payload_templates = {"jsonrpc": "2.0", "id": "30", "method": "resources/templates/list", "params": {}}
        request_templates = self._make_request(payload_templates)
        template = MagicMock()
        template.model_dump.return_value = {"uriTemplate": "resource://{id}"}

        with (
            patch("mcpgateway.main.resource_service.list_resource_templates", new=AsyncMock(return_value=[template])),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request_templates, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["resourceTemplates"][0]["uriTemplate"] == "resource://{id}"

        payload_other = {"jsonrpc": "2.0", "id": "31", "method": "notifications/other", "params": {}}
        request_other = self._make_request(payload_other)
        result = await handle_rpc(request_other, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_handle_rpc_elicitation_error_paths(self, monkeypatch):
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        payload_invalid = {"jsonrpc": "2.0", "id": "32", "method": "elicitation/create", "params": {}}
        request_invalid = self._make_request(payload_invalid)
        result = await handle_rpc(request_invalid, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32602

        payload_no_sessions = {
            "jsonrpc": "2.0",
            "id": "33",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        }
        request_no_sessions = self._make_request(payload_no_sessions)
        with patch("mcpgateway.main.session_registry.get_elicitation_capable_sessions", new=AsyncMock(return_value=[])):
            result = await handle_rpc(request_no_sessions, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_not_capable = {
            "jsonrpc": "2.0",
            "id": "34",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_not_capable = self._make_request(payload_not_capable)
        with patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=False)):
            result = await handle_rpc(request_not_capable, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        class _EmptyService:
            def __init__(self):
                self._pending = {}

            async def create_elicitation(self, **_kwargs):
                return SimpleNamespace()

        payload_empty_pending = {
            "jsonrpc": "2.0",
            "id": "35",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_empty_pending = self._make_request(payload_empty_pending)
        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_EmptyService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_empty_pending, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        class _TimeoutService:
            def __init__(self):
                self._pending = {"p1": SimpleNamespace(downstream_session_id="sess-1", request_id="req-1")}

            async def create_elicitation(self, **_kwargs):
                raise asyncio.TimeoutError()

        payload_timeout = {
            "jsonrpc": "2.0",
            "id": "36",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request_timeout = self._make_request(payload_timeout)
        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_TimeoutService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_timeout, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

    async def test_handle_rpc_fallback_admin_bypass_and_plugin_error(self):
        payload = {"jsonrpc": "2.0", "id": "37", "method": "custom/other", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        tool_result = MagicMock()
        tool_result.model_dump.return_value = {"ok": True}
        with (
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(return_value=tool_result)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["ok"] is True

        # First-Party
        from mcpgateway.plugins.framework.models import PluginErrorModel

        with (
            patch(
                "mcpgateway.main.tool_service.invoke_tool",
                new=AsyncMock(side_effect=PluginError(PluginErrorModel(message="nope", plugin_name="test-plugin"))),
            ),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            with pytest.raises(PluginError):
                await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})

    async def test_handle_rpc_session_affinity_invalid_session_executes_locally(self, monkeypatch):
        """Cover session affinity branch when the MCP session id is invalid."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-1", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "not-valid"}

        with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=False):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_session_affinity_forwarded_response_success_and_error(self, monkeypatch):
        """Cover forwarding path for session affinity (success and error responses)."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        payload = {"jsonrpc": "2.0", "id": "aff-2", "method": "tools/list", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        pool = MagicMock()
        pool.forward_request_to_owner = AsyncMock(return_value={"result": {"via": "other-worker"}})

        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["via"] == "other-worker"

        pool.forward_request_to_owner = AsyncMock(return_value={"error": {"code": -32001, "message": "nope"}})
        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32001

    async def test_handle_rpc_session_affinity_pool_not_initialized(self, monkeypatch):
        """Cover RuntimeError branch when pool isn't initialized."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-3", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        with (
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", return_value=True),
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=RuntimeError("no pool")),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"] == {}

    async def test_handle_rpc_session_affinity_internal_forwarded_executes_locally(self, monkeypatch):
        """Cover internally forwarded header branch."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-4", "method": "ping", "params": {}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123", "x-forwarded-internally": "true"}

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_maybe_forward_affinitized_rpc_request_internally_forwarded_branch(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        request = MagicMock(spec=Request)
        request.headers = {"mcp-session-id": "sess-123", "x-forwarded-internally": "true"}
        request.client = SimpleNamespace(host="127.0.0.1")

        forwarded = await main_mod._maybe_forward_affinitized_rpc_request(
            request,
            method="tools/call",
            params={"name": "echo"},
            req_id="aff-local",
            lowered_request_headers={"mcp-session-id": "sess-123"},
        )

        assert forwarded is None

    async def test_handle_rpc_initialize_registers_session_owner_success_and_failure(self, monkeypatch):
        """Cover initialize ownership claim paths."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        payload = {"jsonrpc": "2.0", "id": "aff-init", "method": "initialize", "params": {"session_id": "init-1"}}
        request = self._make_request(payload)
        request.headers = {"mcp-session-id": "sess-123"}

        init_result = MagicMock()
        init_result.model_dump.return_value = {"capabilities": {}}
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", AsyncMock(return_value=init_result))
        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", AsyncMock(return_value="user@example.com"))

        pool = MagicMock()
        pool.register_pool_session_owner = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["capabilities"] == {}
            pool.register_pool_session_owner.assert_awaited_once()

        pool.register_pool_session_owner = AsyncMock(side_effect=Exception("boom"))
        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=pool):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["capabilities"] == {}

    async def test_handle_rpc_initialize_rejects_session_owner_mismatch(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "aff-init-deny", "method": "initialize", "params": {"session_id": "init-1"}}
        request = self._make_request(payload)

        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", AsyncMock(return_value="other@example.com"))
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", AsyncMock(return_value=MagicMock()))

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert result["error"]["message"] == "Access denied"

    async def test_handle_rpc_initialize_claims_unowned_session(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "aff-init-claim", "method": "initialize", "params": {"session_id": "init-2"}}
        request = self._make_request(payload)

        init_result = MagicMock()
        init_result.model_dump.return_value = {"capabilities": {}}
        claim_owner = AsyncMock(return_value="user@example.com")
        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", claim_owner)
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", AsyncMock(return_value=init_result))

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"]["capabilities"] == {}
        claim_owner.assert_awaited_once_with("init-2", "user@example.com")

    async def test_handle_rpc_initialize_rejects_when_owner_claim_unavailable(self, monkeypatch):
        payload = {"jsonrpc": "2.0", "id": "aff-init-unavailable", "method": "initialize", "params": {"session_id": "init-3"}}
        request = self._make_request(payload)

        monkeypatch.setattr("mcpgateway.main.session_registry.claim_session_owner", AsyncMock(return_value=None))
        monkeypatch.setattr("mcpgateway.main.session_registry.handle_initialize_logic", AsyncMock(return_value=MagicMock()))

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert result["error"]["message"] == "Access denied"

    async def test_handle_rpc_list_tools_legacy_token_teams_none_becomes_public_only(self):
        """Cover legacy list_tools branch when token_teams is explicitly None for non-admin."""
        payload = {"jsonrpc": "2.0", "id": "legacy-1", "method": "list_tools", "params": {}}
        request = self._make_request(payload)
        request.state.token_teams = None

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["tools"][0]["id"] == "tool-1"

    async def test_handle_rpc_list_gateways_admin_bypass_and_next_cursor(self):
        """Cover list_gateways scoping branches and nextCursor injection."""
        payload = {"jsonrpc": "2.0", "id": "gw-1", "method": "list_gateways", "params": {}}
        request = self._make_request(payload)
        request.state._jwt_verified_payload = ("token", {"teams": None, "is_admin": True})

        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        mock_db = MagicMock()

        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([gateway], "next"))):
            result = await handle_rpc(request, db=mock_db, user={"email": "user@example.com"})
            assert result["result"]["gateways"][0]["id"] == "gw-1"
            assert result["result"]["nextCursor"] == "next"

        request2 = self._make_request(payload)
        request2.state.token_teams = None  # Explicitly None but no admin flag in token -> public-only
        with patch("mcpgateway.main.gateway_service.list_gateways", new=AsyncMock(return_value=([], None))) as list_gateways:
            result = await handle_rpc(request2, db=MagicMock(), user={"email": "user@example.com"})
            assert result["result"]["gateways"] == []
            assert list_gateways.await_count == 1

    async def test_handle_rpc_elicitation_value_error_and_catch_all(self, monkeypatch):
        """Cover elicitation ValueError mapping and method catch-all."""
        monkeypatch.setattr(settings, "mcpgateway_elicitation_enabled", True)

        class _Pending:
            def __init__(self, downstream_session_id: str, request_id: str):
                self.downstream_session_id = downstream_session_id
                self.request_id = request_id

        class _BadElicitationService:
            def __init__(self):
                self._pending = {"p1": _Pending("sess-1", "req-1")}

            async def create_elicitation(self, **_kwargs):
                raise ValueError("bad elicit")

        payload = {
            "jsonrpc": "2.0",
            "id": "elic-1",
            "method": "elicitation/create",
            "params": {"message": "Need input", "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}}, "session_id": "sess-1"},
        }
        request = self._make_request(payload)
        request.state = MagicMock()

        with (
            patch("mcpgateway.services.elicitation_service.get_elicitation_service", return_value=_BadElicitationService()),
            patch("mcpgateway.main.session_registry.has_elicitation_capability", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.session_registry.broadcast", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_other = {"jsonrpc": "2.0", "id": "elic-2", "method": "elicitation/other", "params": {}}
        request_other = self._make_request(payload_other)
        result = await handle_rpc(request_other, db=MagicMock(), user={"email": "user@example.com"})
        assert result["result"] == {}

    async def test_handle_rpc_fallback_method_not_found_and_internal_error(self):
        """Cover fallback error when tool not found (gateway forwarding removed) and generic internal error."""
        payload = {"jsonrpc": "2.0", "id": "fallback-1", "method": "custom/forward", "params": {"a": 1}}
        request = self._make_request(payload)
        request.state = MagicMock()

        # Gateway forwarding is removed, so missing tool returns error
        with patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=ValueError("no tool"))):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["error"]["code"] == -32000

        payload_missing_method = {"jsonrpc": "2.0", "id": "err-1", "params": {}}
        request_missing_method = self._make_request(payload_missing_method)
        result = await handle_rpc(request_missing_method, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["message"] == "Internal error"

    async def test_handle_rpc_tools_call_cancel_callback_cancels_task(self, monkeypatch):
        """Cover inner cancel_tool_task() callback cancelling a live asyncio task."""
        monkeypatch.setattr(settings, "mcpgateway_tool_cancellation_enabled", True)

        payload = {"jsonrpc": "2.0", "id": "cb-1", "method": "tools/call", "params": {"name": "tool-long", "arguments": {}}}
        request = self._make_request(payload)
        request.state = MagicMock()

        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_invoke(*_args, **_kwargs):
            started.set()
            await release.wait()
            return {"ok": True}

        cancel_callback_holder: dict[str, object] = {}

        async def _capture_register_run(run_id, *, name, cancel_callback, owner_email=None, owner_team_ids=None):  # noqa: ANN001, ARG001
            cancel_callback_holder["cb"] = cancel_callback

        with (
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
            patch("mcpgateway.main.cancellation_service.register_run", new=AsyncMock(side_effect=_capture_register_run)),
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"cancelled": False})),
            patch("mcpgateway.main.cancellation_service.unregister_run", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.tool_service.invoke_tool", new=AsyncMock(side_effect=_slow_invoke)),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            rpc_task = asyncio.create_task(handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"}))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            await cancel_callback_holder["cb"](reason="test")  # type: ignore[misc]
            release.set()

            result = await rpc_task
            assert result["error"]["code"] == -32800

    @pytest.mark.asyncio
    async def test_handle_rpc_notifications_cancelled_denies_non_owner(self):
        payload_cancel = {"jsonrpc": "2.0", "id": "32", "method": "notifications/cancelled", "params": {"requestId": "r1", "reason": "stop"}}
        request_cancel = self._make_request(payload_cancel)

        with (
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value={"owner_email": "owner@example.com", "owner_team_ids": []})),
            patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_cancel, db=MagicMock(), user={"email": "user@example.com"})

        assert result["error"]["message"] == "Not authorized to cancel this run"

    @pytest.mark.asyncio
    async def test_handle_rpc_notifications_cancelled_accepts_unknown_run_as_noop(self):
        payload_cancel = {"jsonrpc": "2.0", "id": "33", "method": "notifications/cancelled", "params": {"requestId": "unknown-run", "reason": "stop"}}
        request_cancel = self._make_request(payload_cancel)

        with (
            patch("mcpgateway.main.cancellation_service.get_status", new=AsyncMock(return_value=None)),
            patch("mcpgateway.main.cancellation_service.cancel_run", new=AsyncMock(return_value=False)) as cancel_run,
            patch("mcpgateway.main.logging_service.notify", new=AsyncMock(return_value=None)),
        ):
            result = await handle_rpc(request_cancel, db=MagicMock(), user={"email": "user@example.com", "is_admin": False})

        assert result["result"] == {}
        cancel_run.assert_awaited_once_with("unknown-run", reason="stop")


class TestA2AListAndGet:
    """Cover list/get A2A agent endpoints in main."""

    async def test_list_a2a_agents_with_pagination(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.team_id = None

        agent = MagicMock()
        agent.model_dump.return_value = {"id": "agent-1"}

        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            mock_service.list_agents = AsyncMock(return_value=([agent], "next-cursor"))
            result = await list_a2a_agents(request, include_pagination=True, db=MagicMock(), user={"email": "user@example.com"})
            assert result.agents == [agent]
            assert result.next_cursor == "next-cursor"

    async def test_list_a2a_agents_team_mismatch(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.team_id = "team-a"

        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", ["team-a"], False)),
        ):
            mock_service.list_agents = AsyncMock(return_value=([], None))
            response = await list_a2a_agents(request, team_id="team-b", db=MagicMock(), user={"email": "user@example.com"})
            assert response.status_code == 403

    async def test_get_a2a_agent_success(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()

        with (
            patch("mcpgateway.main.a2a_service") as mock_service,
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
        ):
            mock_service.get_agent = AsyncMock(return_value={"id": "agent-1"})
            result = await get_a2a_agent("agent-1", request, db=MagicMock(), user={"email": "user@example.com"})
            assert result["id"] == "agent-1"


class TestExportImportEndpoints:
    """Cover export/import API endpoints in main."""

    async def test_export_configuration_success(self):
        export_service = MagicMock()
        export_service.export_configuration = AsyncMock(return_value={"tools": []})

        with patch("mcpgateway.main.export_service", export_service):
            result = await export_configuration(MagicMock(spec=Request), types="tools", db=MagicMock(), user={"email": "user@example.com"})
            assert result["tools"] == []

    async def test_export_configuration_parsing_and_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.export_service import ExportError

        request = MagicMock(spec=Request)
        svc = MagicMock()
        svc.export_configuration = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "export_service", svc)

        user_obj = SimpleNamespace(email="user@example.com")
        result = await main_mod.export_configuration.__wrapped__(
            request,
            types="tools,gateways",
            exclude_types="servers",
            tags="a, b",
            include_inactive=True,
            include_dependencies=False,
            db=MagicMock(),
            user=user_obj,
        )
        assert result["ok"] is True
        kwargs = svc.export_configuration.await_args.kwargs
        assert kwargs["include_types"] == ["tools", "gateways"]
        assert kwargs["exclude_types"] == ["servers"]
        assert kwargs["tags"] == ["a", "b"]
        assert kwargs["exported_by"] == "user@example.com"

        svc.export_configuration = AsyncMock(side_effect=ExportError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_configuration.__wrapped__(request, types="tools", db=MagicMock(), user="basic-user")
        assert excinfo.value.status_code == 400

        svc.export_configuration = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_configuration.__wrapped__(request, types="tools", db=MagicMock(), user="basic-user")
        assert excinfo.value.status_code == 500

    async def test_export_selective_configuration_success(self):
        export_service = MagicMock()
        export_service.export_selective = AsyncMock(return_value={"tools": ["tool-1"]})
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(token_teams=[], _jwt_verified_payload=None)

        with patch("mcpgateway.main.export_service", export_service):
            result = await export_selective_configuration(request, {"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
            assert result["tools"] == ["tool-1"]
            kwargs = export_service.export_selective.await_args.kwargs
            assert kwargs["user_email"] == "user@example.com"
            assert kwargs["token_teams"] == []

    async def test_export_selective_configuration_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.export_service import ExportError

        svc = MagicMock()
        svc.export_selective = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "export_service", svc)
        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(token_teams=[], _jwt_verified_payload=None)

        result = await main_mod.export_selective_configuration.__wrapped__(
            request,
            {"tools": ["tool-1"]},
            include_dependencies=False,
            db=MagicMock(),
            user=SimpleNamespace(email="user@example.com"),
        )
        assert result["ok"] is True

        svc.export_selective = AsyncMock(side_effect=ExportError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_selective_configuration.__wrapped__(request, {"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        svc.export_selective = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.export_selective_configuration.__wrapped__(request, {"tools": ["tool-1"]}, include_dependencies=False, db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500

    async def test_import_configuration_missing_import_data(self):
        # First-Party
        import mcpgateway.main as main_mod

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400
        assert "import_data" in str(excinfo.value.detail).lower()

    async def test_import_configuration_invalid_strategy(self):
        # First-Party
        import mcpgateway.main as main_mod

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"version": "1"}, conflict_strategy="invalid", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400
        assert "Invalid conflict strategy" in str(excinfo.value.detail)

    async def test_import_configuration_success(self):
        status = MagicMock()
        status.to_dict.return_value = {"status": "ok"}
        import_service = MagicMock()
        import_service.import_configuration = AsyncMock(return_value=status)

        with patch("mcpgateway.main.import_service", import_service):
            result = await import_configuration(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
            assert result["status"] == "ok"

    async def test_import_configuration_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.import_service import ImportConflictError
        from mcpgateway.services.import_service import ImportError as ImportServiceError
        from mcpgateway.services.import_service import ImportValidationError

        request_import_status = MagicMock()
        request_import_status.to_dict.return_value = {"status": "ok"}

        svc = MagicMock()
        svc.import_configuration = AsyncMock(return_value=request_import_status)
        monkeypatch.setattr(main_mod, "import_service", svc)

        # Cover username=None branch by using non-dict user
        result = await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user="basic-user")
        assert result["status"] == "ok"

        svc.import_configuration = AsyncMock(side_effect=ImportValidationError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 422

        svc.import_configuration = AsyncMock(side_effect=ImportConflictError("conflict"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 409

        svc.import_configuration = AsyncMock(side_effect=ImportServiceError("bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

        svc.import_configuration = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.import_configuration.__wrapped__(import_data={"tools": []}, conflict_strategy="update", db=MagicMock(), user={"email": "user@example.com"})
        assert excinfo.value.status_code == 500


class TestMessageEndpointElicitation:
    """Cover elicitation response handling."""

    async def test_message_endpoint_elicitation_response(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": {"foo": "bar"}}}).encode())

        # Allow permission checks to pass for direct invocation
        # First-Party
        from mcpgateway.services.permission_service import PermissionService

        monkeypatch.setattr(PermissionService, "check_permission", AsyncMock(return_value=True))

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = True
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)
        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="user@example.com"))

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_not_called()

    async def test_message_endpoint_missing_session_id_raises_400(self):
        request = MagicMock(spec=Request)
        request.query_params = {}

        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoint_value_error_maps_to_400(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="user@example.com"))
        monkeypatch.setattr("mcpgateway.main._read_request_json", AsyncMock(side_effect=ValueError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoint_elicitation_processing_error_falls_back_to_broadcast(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": ["not-a-dict"]}}).encode())

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = True
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)
        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="user@example.com"))

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_awaited_once()

    async def test_message_endpoint_elicitation_complete_false_broadcasts(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        request.body = AsyncMock(return_value=json.dumps({"id": "req-1", "result": {"action": "accept", "content": {"foo": "bar"}}}).encode())

        elicitation_service = MagicMock()
        elicitation_service.complete_elicitation.return_value = False
        monkeypatch.setattr("mcpgateway.services.elicitation_service.get_elicitation_service", lambda: elicitation_service)
        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="user@example.com"))

        broadcast = AsyncMock()
        monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast)

        response = await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert response.status_code == 202
        broadcast.assert_awaited_once()

    async def test_message_endpoint_rejects_non_owner(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="other@example.com"))
        monkeypatch.setattr("mcpgateway.main._read_request_json", AsyncMock(return_value={"hello": "world"}))

        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403

    async def test_message_endpoint_rejects_unknown_owner_metadata(self, monkeypatch):
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value=None))
        monkeypatch.setattr("mcpgateway.main.session_registry.session_exists", AsyncMock(return_value=True))
        monkeypatch.setattr("mcpgateway.main._read_request_json", AsyncMock(return_value={"hello": "world"}))

        with pytest.raises(HTTPException) as excinfo:
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Session owner metadata unavailable"

    async def test_message_endpoint_sets_trace_session_id_before_authorization(self, monkeypatch):
        """message_endpoint should capture session_id even when the owner check fails."""
        # First-Party
        from mcpgateway.utils.trace_context import clear_trace_context, get_trace_session_id

        clear_trace_context()
        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-trace"}

        monkeypatch.setattr("mcpgateway.main.session_registry.get_session_owner", AsyncMock(return_value="other@example.com"))
        monkeypatch.setattr("mcpgateway.main._read_request_json", AsyncMock(return_value={"hello": "world"}))

        with pytest.raises(HTTPException):
            await message_endpoint(request, "server-1", user={"email": "user@example.com"})

        assert get_trace_session_id() == "session-trace"
        clear_trace_context()


class TestRemainingCoverageGaps:
    """Targeted unit tests for remaining uncovered main.py branches (per HTML coverage report)."""

    def test_get_db_invalidates_when_rollback_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def __init__(self):
                self.is_active = True
                self.committed = False
                self.rolled_back = False
                self.invalidated = False
                self.closed = False

            def commit(self):  # noqa: D401 - test helper
                self.committed = True

            def rollback(self):  # noqa: D401 - test helper
                self.rolled_back = True
                raise RuntimeError("rollback failed")

            def invalidate(self):  # noqa: D401 - test helper
                self.invalidated = True
                raise RuntimeError("invalidate failed")

            def close(self):  # noqa: D401 - test helper
                self.closed = True

        sess = FakeSession()
        monkeypatch.setattr(main_mod, "SessionLocal", lambda: sess)

        gen = main_mod.get_db()
        assert next(gen) is sess
        with pytest.raises(RuntimeError, match="boom"):
            gen.throw(RuntimeError("boom"))

        assert sess.rolled_back is True
        assert sess.invalidated is True
        assert sess.closed is True

    def test_healthcheck_invalidate_failure_is_best_effort(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def __init__(self):
                self.closed = False

            def execute(self, _stmt):  # noqa: ANN001
                raise RuntimeError("db down")

            def commit(self):
                return None

            def rollback(self):
                raise RuntimeError("rollback failed")

            def invalidate(self):
                raise RuntimeError("invalidate failed")

            def close(self):
                self.closed = True

        sess = FakeSession()
        monkeypatch.setattr(main_mod, "SessionLocal", lambda: sess)

        result = main_mod.healthcheck()
        assert result["status"] == "unhealthy"
        assert "db down" in result["error"]
        assert sess.closed is True

    def test_healthcheck_reports_runtime_mode_and_headers(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def execute(self, _stmt):  # noqa: ANN001
                return None

            def commit(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr(main_mod, "SessionLocal", FakeSession)
        monkeypatch.setenv("CONTEXTFORGE_ENABLE_RUST_BUILD", "true")
        monkeypatch.setenv("EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED", "false")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_enabled", False)

        response = FastAPIResponse()
        result = main_mod.healthcheck(response)

        assert result["status"] == "healthy"
        assert result["mcp_runtime"]["mode"] == "python-rust-built-disabled"
        assert result["mcp_runtime"]["mounted"] == "python"
        assert result["mcp_runtime"]["rust_build_included"] is True
        assert result["mcp_runtime"]["session_core_mode"] == "python"
        assert result["mcp_runtime"]["event_store_mode"] == "python"
        assert result["mcp_runtime"]["resume_core_mode"] == "python"
        assert result["mcp_runtime"]["live_stream_core_mode"] == "python"
        assert result["mcp_runtime"]["session_auth_reuse_mode"] == "python"
        assert response.headers["x-contextforge-mcp-runtime-mode"] == "python-rust-built-disabled"
        assert response.headers["x-contextforge-mcp-transport-mounted"] == "python"
        assert response.headers["x-contextforge-rust-build-included"] == "true"
        assert response.headers["x-contextforge-mcp-session-core-mode"] == "python"
        assert response.headers["x-contextforge-mcp-event-store-mode"] == "python"
        assert response.headers["x-contextforge-mcp-resume-core-mode"] == "python"
        assert response.headers["x-contextforge-mcp-live-stream-core-mode"] == "python"
        assert response.headers["x-contextforge-mcp-session-auth-reuse-mode"] == "python"

    async def test_readiness_check_invalidate_failure_is_best_effort(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def execute(self, _stmt):  # noqa: ANN001
                raise RuntimeError("db down")

            def commit(self):
                return None

            def rollback(self):
                raise RuntimeError("rollback failed")

            def invalidate(self):
                raise RuntimeError("invalidate failed")

            def close(self):
                return None

        monkeypatch.setattr(main_mod, "SessionLocal", FakeSession)

        async def _to_thread(func, *args, **kwargs):  # noqa: ANN001
            return func(*args, **kwargs)

        monkeypatch.setattr(main_mod.asyncio, "to_thread", _to_thread)

        response = await main_mod.readiness_check()
        assert response.status_code == 503
        payload = json.loads(response.body.decode())
        assert payload["status"] == "not ready"

    async def test_readiness_check_reports_runtime_mode_headers(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def execute(self, _stmt):  # noqa: ANN001
                return None

            def commit(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr(main_mod, "SessionLocal", FakeSession)

        async def _to_thread(func, *args, **kwargs):  # noqa: ANN001
            return func(*args, **kwargs)

        monkeypatch.setattr(main_mod.asyncio, "to_thread", _to_thread)
        monkeypatch.setenv("CONTEXTFORGE_ENABLE_RUST_BUILD", "true")
        monkeypatch.setenv("EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED", "true")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_uds", "/tmp/contextforge-mcp-rust.sock")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_session_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_event_store_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_resume_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_live_stream_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_session_auth_reuse_enabled", True)

        response = await main_mod.readiness_check()
        payload = json.loads(response.body.decode())

        assert response.status_code == 200
        assert payload["status"] == "ready"
        assert payload["mcp_runtime"]["mode"] == "rust-managed"
        assert payload["mcp_runtime"]["mounted"] == "rust"
        assert payload["mcp_runtime"]["sidecar_transport"] == "uds"
        assert payload["mcp_runtime"]["session_core_mode"] == "rust"
        assert payload["mcp_runtime"]["event_store_mode"] == "rust"
        assert payload["mcp_runtime"]["resume_core_mode"] == "rust"
        assert payload["mcp_runtime"]["live_stream_core_mode"] == "rust"
        assert payload["mcp_runtime"]["session_auth_reuse_mode"] == "rust"
        assert response.headers["x-contextforge-mcp-runtime-mode"] == "rust-managed"
        assert response.headers["x-contextforge-mcp-transport-mounted"] == "rust"
        assert response.headers["x-contextforge-rust-build-included"] == "true"
        assert response.headers["x-contextforge-mcp-session-core-mode"] == "rust"
        assert response.headers["x-contextforge-mcp-event-store-mode"] == "rust"
        assert response.headers["x-contextforge-mcp-resume-core-mode"] == "rust"
        assert response.headers["x-contextforge-mcp-live-stream-core-mode"] == "rust"
        assert response.headers["x-contextforge-mcp-session-auth-reuse-mode"] == "rust"

    def test_runtime_status_payload_reports_http_transport_and_rust_affinity_core(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setenv("CONTEXTFORGE_ENABLE_RUST_BUILD", "true")
        monkeypatch.setenv("EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED", "true")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_uds", None)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_affinity_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_session_auth_reuse_enabled", True)

        payload = main_mod._mcp_runtime_status_payload()

        assert main_mod._current_mcp_affinity_core_mode() == "rust"
        assert payload["sidecar_transport"] == "http"
        assert payload["sidecar_target"] == "http://127.0.0.1:8787"
        assert payload["affinity_core_mode"] == "rust"
        assert payload["session_auth_reuse_mode"] == "rust"

    def test_runtime_status_payload_reports_python_mount_without_session_auth_reuse(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setenv("CONTEXTFORGE_ENABLE_RUST_BUILD", "true")
        monkeypatch.setenv("EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED", "true")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_uds", "/tmp/contextforge-mcp-rust.sock")
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_session_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_event_store_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_resume_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_live_stream_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_affinity_core_enabled", True)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_session_auth_reuse_enabled", False)

        payload = main_mod._mcp_runtime_status_payload()

        assert payload["mode"] == "rust-managed"
        assert payload["mounted"] == "python"
        assert payload["session_core_mode"] == "python"
        assert payload["event_store_mode"] == "python"
        assert payload["resume_core_mode"] == "python"
        assert payload["live_stream_core_mode"] == "python"
        assert payload["affinity_core_mode"] == "python"
        assert payload["rust_session_core_enabled"] is False
        assert payload["rust_event_store_enabled"] is False
        assert payload["rust_resume_core_enabled"] is False
        assert payload["rust_live_stream_core_enabled"] is False
        assert payload["rust_affinity_core_enabled"] is False
        assert payload["session_auth_reuse_mode"] == "python"

    def test_healthcheck_unhealthy_applies_runtime_headers(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeSession:  # noqa: D401 - test helper
            def execute(self, _stmt):  # noqa: ANN001
                raise RuntimeError("db down")

            def rollback(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr(main_mod, "SessionLocal", FakeSession)
        monkeypatch.setattr(main_mod.settings, "experimental_rust_mcp_runtime_enabled", True)

        response = FastAPIResponse()
        result = main_mod.healthcheck(response)

        assert result["status"] == "unhealthy"
        assert response.headers["x-contextforge-mcp-runtime-mode"] == "rust-managed"

    async def test_sse_endpoint_cookie_auth_and_disconnect_cleanup(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}  # no bearer
        request.cookies = {"jwt_token": "cookie-token"}
        request.scope = {"root_path": ""}

        transport = MagicMock()
        transport.session_id = "session-1"
        transport.connect = AsyncMock()

        async def _create_sse_response(_req, on_disconnect_callback=None):  # noqa: ANN001
            if on_disconnect_callback:
                await on_disconnect_callback()
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=SimpleNamespace(id="server-1")))
        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        remove_session = AsyncMock(return_value=None)
        monkeypatch.setattr(main_mod.session_registry, "remove_session", remove_session)

        # Cover user.is_admin attribute branch (cookie-authenticated user object).
        user = SimpleNamespace(email="user@example.com", is_admin=True)
        response = await main_mod.sse_endpoint.__wrapped__(request, "server-1", db=MagicMock(), user=user)
        assert response.status_code == 200
        remove_session.assert_awaited_once()

    async def test_sse_endpoint_disconnect_cleanup_warns_on_failure(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}  # no bearer
        request.cookies = {"access_token": "cookie-token"}
        request.scope = {"root_path": ""}

        transport = MagicMock()
        transport.session_id = "session-2"
        transport.connect = AsyncMock()

        async def _create_sse_response(_req, on_disconnect_callback=None):  # noqa: ANN001
            if on_disconnect_callback:
                await on_disconnect_callback()
            return StarletteResponse("ok")

        transport.create_sse_response = AsyncMock(side_effect=_create_sse_response)

        monkeypatch.setattr(main_mod, "update_url_protocol", lambda _req: "http://example.com")
        monkeypatch.setattr(main_mod, "_get_token_teams_from_request", lambda _req: [])
        monkeypatch.setattr(main_mod, "SSETransport", MagicMock(return_value=transport))
        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=SimpleNamespace(id="server-1")))
        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main_mod.session_registry, "add_session", AsyncMock())
        monkeypatch.setattr(main_mod.session_registry, "respond", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.session_registry, "register_respond_task", MagicMock())
        monkeypatch.setattr(main_mod.session_registry, "remove_session", AsyncMock(side_effect=RuntimeError("fail")))

        user = SimpleNamespace(email="user@example.com", is_admin=False)
        response = await main_mod.sse_endpoint.__wrapped__(request, "server-1", db=MagicMock(), user=user)
        assert response.status_code == 200

    async def test_list_servers_tags_team_mismatch_and_pagination(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        # Team mismatch path
        response = await main_mod.list_servers.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id="team-2",
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        # Tags parsing + pagination payload
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])
        server = MagicMock()
        server.model_dump.return_value = {"id": "srv-1"}
        list_servers = AsyncMock(return_value=([server], "next"))
        monkeypatch.setattr(main_mod.server_service, "list_servers", list_servers)

        result = await main_mod.list_servers.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            tags=" a, b ,,",
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result.servers == [server]
        assert result.next_cursor == "next"
        assert list_servers.call_args.kwargs["tags"] == ["a", "b"]

    async def test_list_gateways_team_mismatch_and_pagination(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])

        response = await main_mod.list_gateways.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            team_id="team-2",
            visibility=None,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])
        gateway = MagicMock()
        gateway.model_dump.return_value = {"id": "gw-1"}
        list_gateways = AsyncMock(return_value=([gateway], "next"))
        monkeypatch.setattr(main_mod.gateway_service, "list_gateways", list_gateways)

        db = MagicMock()
        result = await main_mod.list_gateways.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            team_id=None,
            visibility=None,
            db=db,
            user={"email": "user@example.com"},
        )
        assert result.gateways == [gateway]
        assert result.next_cursor == "next"
        db.commit.assert_called()
        db.close.assert_called()

    async def test_read_resource_fallback_serialization_branches(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        db = MagicMock()

        class DummyContent:  # noqa: D401 - test helper
            def __init__(self, uri, text=None):  # noqa: ANN001
                self.uri = uri
                if text is not None:
                    self.text = text

            def __str__(self):
                return "dummy"

        # Force ResourceContent/TextContent import to fail to hit fallback block.
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name == "mcpgateway.common.models":
                raise ImportError("forced")
            return original_import(name, globals, locals, fromlist, level)

        # 1) hasattr(content, "text") branch
        monkeypatch.setattr(builtins, "__import__", guarded_import)
        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=DummyContent("uri:1", text="hi")))
        result = await main_mod.read_resource.__wrapped__("res-1", request, db=db, user={"email": "user@example.com"})
        assert result["text"] == "hi"

        # 2) final fallback branch
        monkeypatch.setattr(main_mod.resource_service, "read_resource", AsyncMock(return_value=DummyContent("uri:2")))
        result = await main_mod.read_resource.__wrapped__("res-2", request, db=db, user={"email": "user@example.com"})
        assert result["text"] == "dummy"

    async def test_get_resource_info_success_and_not_found(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.resource_service import ResourceNotFoundError

        ok = MagicMock()
        request = MagicMock(spec=Request)
        enforce_scope = MagicMock(return_value=None)
        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", enforce_scope)
        monkeypatch.setattr(main_mod.resource_service, "get_resource_by_id", AsyncMock(return_value=ok))
        result = await main_mod.get_resource_info.__wrapped__(
            "res-1",
            request=request,
            include_inactive=False,
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert result is ok
        enforce_scope.assert_called_once()

        monkeypatch.setattr(main_mod.resource_service, "get_resource_by_id", AsyncMock(side_effect=ResourceNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_resource_info.__wrapped__(
                "res-1",
                request=request,
                include_inactive=False,
                db=MagicMock(),
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 404

    async def test_get_resource_info_denies_when_scope_enforcement_fails(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(main_mod.resource_service, "get_resource_by_id", AsyncMock(return_value=MagicMock()))

        def _deny(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(main_mod, "_enforce_scoped_resource_access", _deny)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_resource_info.__wrapped__(
                "res-1",
                request=request,
                include_inactive=False,
                db=MagicMock(),
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 403

    async def test_get_import_status_found_and_not_found(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        status_obj = MagicMock()
        status_obj.to_dict.return_value = {"status": "ok"}
        monkeypatch.setattr(main_mod.import_service, "get_import_status", MagicMock(return_value=status_obj))
        result = await main_mod.get_import_status.__wrapped__("import-1", user={"email": "user@example.com"})
        assert result["status"] == "ok"

        monkeypatch.setattr(main_mod.import_service, "get_import_status", MagicMock(return_value=None))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_import_status.__wrapped__("import-2", user={"email": "user@example.com"})
        assert excinfo.value.status_code == 404

    async def test_list_and_cleanup_import_statuses(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        s1 = MagicMock()
        s1.to_dict.return_value = {"id": "1"}
        s2 = MagicMock()
        s2.to_dict.return_value = {"id": "2"}
        monkeypatch.setattr(main_mod.import_service, "list_import_statuses", MagicMock(return_value=[s1, s2]))
        result = await main_mod.list_import_statuses.__wrapped__(user={"email": "user@example.com"})
        assert result == [{"id": "1"}, {"id": "2"}]

        monkeypatch.setattr(main_mod.import_service, "cleanup_completed_imports", MagicMock(return_value=2))
        result = await main_mod.cleanup_import_statuses.__wrapped__(max_age_hours=1, user={"email": "user@example.com"})
        assert result["removed_count"] == 2

    async def test_create_server_public_only_restrictions_and_team_id(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/servers")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        server_obj = MagicMock()

        response = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id=None,
            visibility="team",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        response = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id="team-2",
            visibility="team",
            db=MagicMock(),
            user={"email": "user@example.com"},
        )
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "user",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        register = AsyncMock(return_value=server_obj)
        monkeypatch.setattr(main_mod.server_service, "register_server", register)
        db = MagicMock()
        _ = await main_mod.create_server.__wrapped__(
            server_obj,
            request,
            team_id="team-1",
            visibility="public",
            db=db,
            user={"email": "user@example.com"},
        )
        assert register.call_args.kwargs["team_id"] is None

    async def test_register_gateway_public_only_restrictions_and_validation_error(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/gateways")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        gateway_obj = SimpleNamespace(team_id="team-1", visibility="team")
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=["team-1"])
        gateway_obj = SimpleNamespace(team_id="team-2", visibility="team")
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 403

        request.state = SimpleNamespace(team_id="team-1", token_teams=[])
        gateway_obj = SimpleNamespace(team_id="team-1", visibility="public")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {"created_by": "user", "created_from_ip": "127.0.0.1", "created_via": "api", "created_user_agent": "test"},
        )
        register = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod.gateway_service, "register_gateway", register)
        _ = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert register.call_args.kwargs["team_id"] is None

        class FakeValidationError(Exception):
            """ValidationError branch in register_gateway is unreachable for pydantic.ValidationError (subclasses ValueError)."""

        monkeypatch.setattr(main_mod, "ValidationError", FakeValidationError)
        monkeypatch.setattr(main_mod.gateway_service, "register_gateway", AsyncMock(side_effect=FakeValidationError("bad")))
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value={"detail": "bad"}))
        response = await main_mod.register_gateway.__wrapped__(gateway_obj, request, db=MagicMock(), user={"email": "user@example.com"})
        assert response.status_code == 422
        assert json.loads(response.body.decode()) == {"detail": "bad"}

    async def test_state_endpoints_error_branches(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.gateway_service import GatewayNotFoundError
        from mcpgateway.services.prompt_service import PromptLockConflictError
        from mcpgateway.services.resource_service import ResourceLockConflictError
        from mcpgateway.services.server_service import ServerError, ServerLockConflictError

        monkeypatch.setattr(main_mod.server_service, "set_server_state", AsyncMock(side_effect=ServerLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_server_state.__wrapped__("s1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.server_service, "set_server_state", AsyncMock(side_effect=ServerError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_server_state.__wrapped__("s1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.resource_service, "set_resource_state", AsyncMock(side_effect=ResourceLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_resource_state.__wrapped__("r1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.resource_service, "set_resource_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_resource_state.__wrapped__("r1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.prompt_service, "set_prompt_state", AsyncMock(side_effect=PromptLockConflictError("locked")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_prompt_state.__wrapped__("p1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

        monkeypatch.setattr(main_mod.prompt_service, "set_prompt_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_prompt_state.__wrapped__("p1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

        monkeypatch.setattr(main_mod.gateway_service, "get_gateway", AsyncMock(side_effect=GatewayNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_gateway.__wrapped__("gw-1", request=MagicMock(spec=Request), db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.gateway_service, "set_gateway_state", AsyncMock(side_effect=RuntimeError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_gateway_state.__wrapped__("gw-1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_delete_server_error_mappings(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.server_service import ServerError

        monkeypatch.setattr(main_mod.server_service, "get_server", AsyncMock(return_value=None))
        monkeypatch.setattr(main_mod.server_service, "delete_server", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_server.__wrapped__("s1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 403

        monkeypatch.setattr(main_mod.server_service, "delete_server", AsyncMock(side_effect=ServerError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_server.__wrapped__("s1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_message_endpoints_generic_exception_mapping(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}

        monkeypatch.setattr(main_mod.session_registry, "get_session_owner", AsyncMock(return_value="u"))
        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value={"hello": "world"}))
        monkeypatch.setattr(main_mod.session_registry, "broadcast", AsyncMock(side_effect=RuntimeError("boom")))

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.message_endpoint.__wrapped__(request, "server-1", user={"email": "u"})
        assert excinfo.value.status_code == 500

        request = MagicMock(spec=Request)
        request.query_params = {"session_id": "session-1"}
        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value={"hello": "world"}))
        monkeypatch.setattr(main_mod.session_registry, "broadcast", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.utility_message_endpoint.__wrapped__(request, user={"email": "u"})
        assert excinfo.value.status_code == 500

    async def test_list_tools_and_get_tool_jsonpath_modifier(self, monkeypatch):
        # Third-Party
        import orjson

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier
        from mcpgateway.utils.orjson_response import ORJSONResponse

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(return_value={"filtered": True}))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=apijsonpath,
            user={"email": "user@example.com"},
        )
        assert isinstance(result, ORJSONResponse)
        assert orjson.loads(result.body) == {"filtered": True}

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))
        result = await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=apijsonpath)
        assert isinstance(result, ORJSONResponse)
        assert orjson.loads(result.body) == {"filtered": True}

    async def test_list_tools_apijsonpath_with_pagination(self, monkeypatch):
        """Test list_tools with apijsonpath and pagination returns cursor (lines 4100-4109)."""
        # Third-Party
        import orjson

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier
        from mcpgateway.utils.orjson_response import ORJSONResponse

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool1 = MagicMock()
        tool1.to_dict.return_value = {"id": "t1", "name": "Tool 1"}
        tool2 = MagicMock()
        tool2.to_dict.return_value = {"id": "t2", "name": "Tool 2"}

        # Mock list_tools to return tools with a next_cursor
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool1, tool2], "cursor123")))

        # Mock jsonpath_modifier to return transformed data
        def mock_jsonpath_modifier(data, jsonpath, mapping):
            # Simulate transformation: extract just id and name
            return [{"toolId": d["id"], "toolName": d["name"]} for d in data]

        monkeypatch.setattr(main_mod, "jsonpath_modifier", mock_jsonpath_modifier)

        apijsonpath = JsonPathModifier(jsonpath="$[*]", mapping={"toolId": "$.id", "toolName": "$.name"})

        # Test with pagination enabled
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=2,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=apijsonpath,
            user={"email": "user@example.com"},
        )

        assert isinstance(result, ORJSONResponse)
        response_data = orjson.loads(result.body)

        # Should have both tools and nextCursor (camelCase matches CursorPaginatedToolsResponse alias)
        assert "tools" in response_data
        assert "nextCursor" in response_data
        assert response_data["nextCursor"] == "cursor123"
        assert len(response_data["tools"]) == 2
        assert response_data["tools"][0] == {"toolId": "t1", "toolName": "Tool 1"}
        assert response_data["tools"][1] == {"toolId": "t2", "toolName": "Tool 2"}

    async def test_list_tools_apijsonpath_pagination_last_page(self, monkeypatch):
        """Test list_tools with apijsonpath on last page returns null cursor (lines 4100-4109)."""
        # Third-Party
        import orjson

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier
        from mcpgateway.utils.orjson_response import ORJSONResponse

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool1 = MagicMock()
        tool1.to_dict.return_value = {"id": "t1", "name": "Tool 1"}

        # Mock list_tools to return tools with None as next_cursor (last page)
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool1], None)))

        def mock_jsonpath_modifier(data, jsonpath, mapping):
            return [{"toolId": d["id"], "toolName": d["name"]} for d in data]

        monkeypatch.setattr(main_mod, "jsonpath_modifier", mock_jsonpath_modifier)

        apijsonpath = JsonPathModifier(jsonpath="$[*]", mapping={"toolId": "$.id", "toolName": "$.name"})

        # Test with pagination enabled on last page
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor="somecursor",
            include_pagination=True,
            limit=2,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=apijsonpath,
            user={"email": "user@example.com"},
        )

        assert isinstance(result, ORJSONResponse)
        response_data = orjson.loads(result.body)

        # Should have tools and nextCursor as null (last page, camelCase matches alias)
        assert "tools" in response_data
        assert "nextCursor" in response_data
        assert response_data["nextCursor"] is None
        assert len(response_data["tools"]) == 1
        assert response_data["tools"][0] == {"toolId": "t1", "toolName": "Tool 1"}

    async def test_list_tools_apijsonpath_string_parsing_error(self, monkeypatch):
        """Test list_tools with invalid apijsonpath string (lines 3668-3671)."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))

        # Invalid JSON string for apijsonpath
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_tools.__wrapped__(
                request,
                cursor=None,
                include_pagination=False,
                limit=None,
                include_inactive=False,
                tags=None,
                team_id=None,
                visibility=None,
                gateway_id=None,
                db=MagicMock(),
                apijsonpath="{invalid json",
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 400
        # Generic error message in non-DEBUG mode (security improvement)
        assert "Invalid apijsonpath" in str(excinfo.value.detail)

    async def test_list_tools_apijsonpath_none_with_pagination(self, monkeypatch):
        """Test list_tools with parsed_apijsonpath=None and include_pagination=True (lines 3674-3681)."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "t1", "name": "test"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], "next_cursor_123")))

        # Pass JsonPathModifier instance but with None jsonpath to trigger parsed_apijsonpath=None path
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=None,  # This will trigger the None path
            user={"email": "user@example.com"},
        )
        # Result can be either a dict or Pydantic model depending on environment
        if isinstance(result, dict):
            assert "tools" in result
            assert "nextCursor" in result
            assert result["nextCursor"] == "next_cursor_123"
        else:
            assert hasattr(result, "tools")
            assert hasattr(result, "next_cursor")
            assert result.next_cursor == "next_cursor_123"

    async def test_list_tools_apijsonpath_exception_handling(self, monkeypatch):
        """Test list_tools jsonpath_modifier exception (lines 3684-3685, 3690-3692)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))

        # Make jsonpath_modifier raise an exception
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(side_effect=RuntimeError("jsonpath error")))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_tools.__wrapped__(
                request,
                cursor=None,
                include_pagination=False,
                limit=None,
                include_inactive=False,
                tags=None,
                team_id=None,
                visibility=None,
                gateway_id=None,
                db=MagicMock(),
                apijsonpath=apijsonpath,
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 500
        assert "JSONPath modifier error" in str(excinfo.value.detail)

    async def test_list_tools_apijsonpath_with_empty_tools_list(self, monkeypatch):
        """Test list_tools with empty tools list and jsonpath (line 3684-3685 branch)."""
        # Third-Party
        import orjson

        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier
        from mcpgateway.utils.orjson_response import ORJSONResponse

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        # Empty tools list
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([], None)))
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(return_value={"filtered": []}))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=apijsonpath,
            user={"email": "user@example.com"},
        )
        assert isinstance(result, ORJSONResponse)
        assert orjson.loads(result.body) == {"filtered": []}

    async def test_get_tool_apijsonpath_none(self, monkeypatch):
        """Test get_tool with parsed_apijsonpath=None (lines 3833-3834)."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1", "name": "test"}

        async def mock_get_tool(*args, **kwargs):
            return data

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", mock_get_tool)

        result = await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=None)
        assert result == data

    async def test_get_tool_apijsonpath_string_parsing_error(self, monkeypatch):
        """Test get_tool with invalid apijsonpath string (lines 3827-3830)."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))

        # Invalid JSON string for apijsonpath - should raise 400 Bad Request
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath="{invalid json")
        # Should be 400 (not 404) for invalid apijsonpath JSON
        assert excinfo.value.status_code == 400
        # Generic error message in non-DEBUG mode (security improvement)
        assert "Invalid apijsonpath" in str(excinfo.value.detail)

    async def test_get_tool_jsonpath_modifier_exception(self, monkeypatch):
        """Test get_tool jsonpath_modifier exception (lines 3841-3843)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))

        # Make jsonpath_modifier raise an exception
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(side_effect=RuntimeError("jsonpath error")))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=apijsonpath)
        # Should be 500 (not 404) for JSONPath modifier errors
        assert excinfo.value.status_code == 500
        assert "JSONPath modifier error" in str(excinfo.value.detail)

    async def test_list_tools_apijsonpath_httpexception_reraise(self, monkeypatch):
        """Test list_tools re-raises HTTPException from jsonpath_modifier (line 3695)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))

        # Make jsonpath_modifier raise HTTPException (e.g., from invalid JSONPath)
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(side_effect=HTTPException(status_code=400, detail="Invalid JSONPath")))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_tools.__wrapped__(
                request,
                cursor=None,
                include_pagination=False,
                limit=None,
                include_inactive=False,
                tags=None,
                team_id=None,
                visibility=None,
                gateway_id=None,
                db=MagicMock(),
                apijsonpath=apijsonpath,
                user={"email": "user@example.com"},
            )
        # Should preserve the original HTTPException status and detail
        assert excinfo.value.status_code == 400
        assert "Invalid JSONPath" in str(excinfo.value.detail)

    async def test_get_tool_apijsonpath_httpexception_reraise(self, monkeypatch):
        """Test get_tool re-raises HTTPException from jsonpath_modifier (line 3844)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))

        # Make jsonpath_modifier raise HTTPException (e.g., from invalid JSONPath)
        monkeypatch.setattr(main_mod, "jsonpath_modifier", MagicMock(side_effect=HTTPException(status_code=400, detail="Invalid JSONPath expression")))

        apijsonpath = JsonPathModifier(jsonpath="$", mapping={})
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=apijsonpath)
        # Should preserve the original HTTPException status and detail
        assert excinfo.value.status_code == 400
        assert "Invalid JSONPath expression" in str(excinfo.value.detail)

    async def test_list_tools_jsonpath_none_returns_pagination(self, monkeypatch):
        """Test list_tools returns paginated response when jsonpath is None."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "t1", "name": "test"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], "cursor_abc")))

        # Pass apijsonpath=None to trigger pagination path
        result = await main_mod.list_tools.__wrapped__(
            request,
            cursor=None,
            include_pagination=True,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            gateway_id=None,
            db=MagicMock(),
            apijsonpath=None,  # Explicitly None to trigger pagination path
            user={"email": "user@example.com"},
        )

        # Should return pagination format when parsed_apijsonpath is None and include_pagination is True
        # Result can be either a dict or Pydantic model depending on environment
        if isinstance(result, dict):
            assert "tools" in result
            assert "nextCursor" in result
            assert result["nextCursor"] == "cursor_abc"
        else:
            assert hasattr(result, "tools")
            assert hasattr(result, "next_cursor")
            assert result.next_cursor == "cursor_abc"

    async def test_list_tools_apijsonpath_invalid_type(self, monkeypatch):
        """Test list_tools with invalid apijsonpath type raises clear error."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))

        # Pass invalid type (integer) - should raise 400 with clear message
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_tools.__wrapped__(
                request,
                cursor=None,
                include_pagination=False,
                limit=None,
                include_inactive=False,
                tags=None,
                team_id=None,
                visibility=None,
                gateway_id=None,
                db=MagicMock(),
                apijsonpath=123,  # Invalid type
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 400
        # Generic error message in non-DEBUG mode (security improvement)
        assert "Invalid apijsonpath type" in str(excinfo.value.detail)
        # Type name not disclosed in production (non-DEBUG) mode

    async def test_get_tool_apijsonpath_invalid_type(self, monkeypatch):
        """Test get_tool with invalid apijsonpath type raises clear error."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))

        # Pass invalid type (list) - should raise 400 with clear message
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=["invalid", "type"])  # Invalid type
        assert excinfo.value.status_code == 400
        # Generic error message in non-DEBUG mode (security improvement)
        assert "Invalid apijsonpath type" in str(excinfo.value.detail)
        # Type name not disclosed in production (non-DEBUG) mode

    async def test_list_tools_empty_jsonpath_string(self, monkeypatch):
        """Test list_tools rejects empty jsonpath string."""
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.to_dict.return_value = {"id": "t1"}
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("user@example.com", [], False))
        monkeypatch.setattr(main_mod.tool_service, "list_tools", AsyncMock(return_value=([tool], None)))

        # Empty jsonpath string - should raise 400
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.list_tools.__wrapped__(
                request,
                cursor=None,
                include_pagination=False,
                limit=None,
                include_inactive=False,
                tags=None,
                team_id=None,
                visibility=None,
                gateway_id=None,
                db=MagicMock(),
                apijsonpath='{"jsonpath":"  ","mapping":null}',  # Empty/whitespace jsonpath
                user={"email": "user@example.com"},
            )
        assert excinfo.value.status_code == 400
        assert "JSONPath expression cannot be empty" in str(excinfo.value.detail)

    async def test_get_tool_empty_jsonpath_model(self, monkeypatch):
        """Test get_tool rejects JsonPathModifier with empty jsonpath."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import JsonPathModifier

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        data = MagicMock()
        data.to_dict.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", [], False))
        monkeypatch.setattr(main_mod, "get_user_team_roles", lambda _db, _email: None)
        monkeypatch.setattr(main_mod.tool_service, "get_tool", AsyncMock(return_value=data))

        # JsonPathModifier with empty jsonpath
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_tool.__wrapped__("tool-1", request=request, db=MagicMock(), user={"email": "u"}, apijsonpath=JsonPathModifier(jsonpath="", mapping=None))
        assert excinfo.value.status_code == 400
        assert "JSONPath expression cannot be empty" in str(excinfo.value.detail)

    async def test_create_tool_endpoint_coverage(self, monkeypatch):
        """Test create_tool endpoint (lines 3695-3698)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import ToolCreate
        from mcpgateway.utils.metadata_capture import MetadataCapture

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None, token_teams=None)

        tool_data = ToolCreate(name="test_tool", url="http://example.com", description="Test", integration_type="REST", request_type="GET")

        created_tool = MagicMock()
        created_tool.id = "tool-123"

        # Mock all the dependencies
        monkeypatch.setattr(
            MetadataCapture,
            "extract_creation_metadata",
            lambda *args: {"created_by": "user@example.com", "created_from_ip": "127.0.0.1", "created_via": "api", "created_user_agent": "test", "import_batch_id": None, "federation_source": None},
        )
        monkeypatch.setattr(main_mod, "get_user_email", lambda user: "user@example.com")
        monkeypatch.setattr(main_mod.tool_service, "register_tool", AsyncMock(return_value=created_tool))

        mock_db = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        result = await main_mod.create_tool.__wrapped__(tool=tool_data, request=request, team_id=None, db=mock_db, user={"email": "user@example.com"})
        assert result == created_tool

    async def test_update_tool_endpoint_coverage(self, monkeypatch):
        """Test update_tool endpoint (lines 3848-3851)."""
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.schemas import ToolUpdate
        from mcpgateway.utils.metadata_capture import MetadataCapture

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool_update = ToolUpdate(description="Updated description")

        updated_tool = MagicMock()
        updated_tool.id = "tool-123"

        current_tool = MagicMock()
        current_tool.version = 1

        mock_db = MagicMock()
        mock_db.get = MagicMock(return_value=current_tool)
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        # Mock dependencies
        monkeypatch.setattr(
            MetadataCapture, "extract_modification_metadata", lambda *args: {"modified_by": "user@example.com", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"}
        )
        monkeypatch.setattr(main_mod.tool_service, "update_tool", AsyncMock(return_value=updated_tool))

        result = await main_mod.update_tool.__wrapped__(tool_id="tool-123", tool=tool_update, request=request, db=mock_db, user={"email": "user@example.com"})
        assert result == updated_tool

    async def test_deprecated_toggle_endpoints(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod, "set_server_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_server_status.__wrapped__("s1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_tool_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_tool_status.__wrapped__("t1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_resource_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_resource_status.__wrapped__("r1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_prompt_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_prompt_status.__wrapped__("p1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_gateway_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_gateway_status.__wrapped__("gw1", True, MagicMock(), {"email": "u"}) == {"ok": True}

        monkeypatch.setattr(main_mod, "set_a2a_agent_state", AsyncMock(return_value={"ok": True}))
        with pytest.warns(DeprecationWarning):
            assert await main_mod.toggle_a2a_agent_status.__wrapped__("a1", True, MagicMock(), {"email": "u"}) == {"ok": True}

    async def test_reset_metrics_a2a_agent_enabled_and_disabled(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        a2a = MagicMock()
        a2a.reset_metrics = AsyncMock()
        monkeypatch.setattr(main_mod, "a2a_service", a2a)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_a2a_metrics_enabled", True)
        result = await main_mod.reset_metrics.__wrapped__(entity="a2a_agent", entity_id=123, db=MagicMock(), user={"email": "u"})
        assert result["status"] == "success"
        a2a.reset_metrics.assert_awaited_once()

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.reset_metrics.__wrapped__(entity="a2a_agent", entity_id=123, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_get_prompt_no_args_not_found_and_permission(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.prompt_service import PromptNotFoundError

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PromptNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_prompt_no_args.__wrapped__(request, "p1", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=PermissionError("nope")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_prompt_no_args.__wrapped__(request, "p1", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 403

    async def test_list_resource_templates_token_teams_normalization(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        monkeypatch.setattr(main_mod.resource_service, "list_resource_templates", AsyncMock(return_value=[]))

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        result = await main_mod.list_resource_templates.__wrapped__(request, db=MagicMock(), include_inactive=False, tags="a, b", visibility=None, user={"email": "u"})
        assert result.resource_templates == []

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        result = await main_mod.list_resource_templates.__wrapped__(request, db=MagicMock(), include_inactive=False, tags=None, visibility=None, user={"email": "u"})
        assert result.resource_templates == []

    async def test_list_prompts_token_teams_normalization(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        list_prompts = AsyncMock(return_value=([], None))
        monkeypatch.setattr(main_mod.prompt_service, "list_prompts", list_prompts)

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        await main_mod.list_prompts.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "u"},
        )
        assert list_prompts.call_args.kwargs["user_email"] is None
        assert list_prompts.call_args.kwargs["token_teams"] is None

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        await main_mod.list_prompts.__wrapped__(
            request,
            cursor=None,
            include_pagination=False,
            limit=None,
            include_inactive=False,
            tags=None,
            team_id=None,
            visibility=None,
            db=MagicMock(),
            user={"email": "u"},
        )
        assert list_prompts.call_args.kwargs["token_teams"] == []

    async def test_server_get_resources_and_prompts_admin_bypass(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        resource = MagicMock()
        resource.model_dump.return_value = {"id": "r1"}
        monkeypatch.setattr(main_mod.resource_service, "list_server_resources", AsyncMock(return_value=[resource]))

        prompt = MagicMock()
        prompt.model_dump.return_value = {"id": "p1"}
        monkeypatch.setattr(main_mod.prompt_service, "list_server_prompts", AsyncMock(return_value=[prompt]))

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, True))
        result = await main_mod.server_get_resources.__wrapped__(request, "srv", include_inactive=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "r1"}]

        result = await main_mod.server_get_prompts.__wrapped__(request, "srv", include_inactive=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "p1"}]

    async def test_update_a2a_agent_service_unavailable_and_validation(self, monkeypatch):
        # Third-Party
        from pydantic import ValidationError

        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/a2a/a1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_a2a_agent.__wrapped__("a1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

        validation = ValidationError.from_exception_data("A2AAgentUpdate", [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}])
        svc = MagicMock()
        svc.update_agent = AsyncMock(side_effect=validation)
        monkeypatch.setattr(main_mod, "a2a_service", svc)
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value="bad"))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_a2a_agent.__wrapped__("a1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 422

    async def test_module_level_router_registration_branches(self, monkeypatch):
        """Import main.py under unique name to cover module-level wiring branches."""
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        # Provide lightweight router modules to avoid importing heavy optional dependencies.
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.observability", ModuleType("mcpgateway.routers.observability"))
        sys.modules["mcpgateway.routers.observability"].router = APIRouter()

        # Force ImportError branches for optional routers.
        force_error = {
            "mcpgateway.routers.oauth_router",
            "mcpgateway.routers.reverse_proxy",
            "mcpgateway.routers.llmchat_router",
            "mcpgateway.routers.llm_admin_router",
            "mcpgateway.routers.llm_config_router",
            "mcpgateway.routers.llm_proxy_router",
            "mcpgateway.routers.toolops_router",
        }

        overrides = {
            "environment": "production",
            "allowed_origins": [],
            "compression_enabled": False,
            "validation_middleware_enabled": False,
            "email_auth_enabled": False,
            "security_logging_enabled": True,
            "observability_enabled": True,
            "db_query_log_enabled": True,
            "cache_type": "redis",
            "redis_url": "redis://localhost:6379",
            "structured_logging_enabled": False,
            "mcpgateway_a2a_enabled": False,
            "mcpgateway_tool_cancellation_enabled": False,
            "mcpgateway_admin_api_enabled": False,
            "mcpgateway_ui_enabled": False,
            "llmchat_enabled": True,
            "toolops_enabled": True,
        }

        mod = _import_fresh_main_module(monkeypatch, overrides=overrides, env={"PLUGINS_ENABLED": "true"}, force_import_error=force_error)

        # Allow the import-time bootstrap_db create_task (running-loop branch) to complete.
        await asyncio.sleep(0)

        # root_info exists only when UI is disabled (no version/admin status exposed).
        info = await mod.root_info()
        assert "name" in info
        assert "version" not in info
        assert "admin_api_enabled" not in info

    def test_jsonpath_modifier_defaults_when_jsonpath_missing(self):
        # jsonpath_modifier(None/""/0) should fall back to default "$[*]".
        assert jsonpath_modifier([{"a": 1}], jsonpath="") == {"a": 1}

    async def test_import_configuration_uses_user_email_attribute(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        status_obj = MagicMock()
        status_obj.to_dict.return_value = {"status": "ok"}
        svc = MagicMock()
        svc.import_configuration = AsyncMock(return_value=status_obj)
        monkeypatch.setattr(main_mod, "import_service", svc)

        user = SimpleNamespace(email="obj@example.com")
        result = await main_mod.import_configuration.__wrapped__(
            import_data={"tools": []},
            conflict_strategy="update",
            dry_run=False,
            rekey_secret=None,
            selected_entities=None,
            db=MagicMock(),
            user=user,
        )
        assert result["status"] == "ok"
        assert svc.import_configuration.call_args.kwargs["imported_by"] == "obj@example.com"

    async def test_initialize_maps_orjson_decode_error(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(side_effect=main_mod.orjson.JSONDecodeError("bad", "{}", 1)))

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.initialize(request, user="user@example.com")
        assert excinfo.value.status_code == 400

    async def test_update_server_name_conflict_maps_to_409(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.server_service import ServerNameConflictError

        request = _make_request("/servers/s1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )
        monkeypatch.setattr(main_mod.server_service, "update_server", AsyncMock(side_effect=ServerNameConflictError("conflict")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.update_server.__wrapped__("s1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 409

    async def test_server_get_tools_public_only_default(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(team_id=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "t1"}

        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("u", None, False))
        monkeypatch.setattr(main_mod.tool_service, "list_server_tools", AsyncMock(return_value=[tool]))

        result = await main_mod.server_get_tools.__wrapped__(request, "srv", include_inactive=False, include_metrics=False, db=MagicMock(), user={"email": "u"})
        assert result == [{"id": "t1"}]

    async def test_tag_endpoints_parse_entity_types(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/tags")
        monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _request, _user: ("u", [], False))

        monkeypatch.setattr(main_mod.tag_service, "get_all_tags", AsyncMock(return_value=[]))
        _ = await main_mod.list_tags.__wrapped__(request, "Tools, Servers", include_entities=False, db=MagicMock(), user={"email": "u"})

        monkeypatch.setattr(main_mod.tag_service, "get_entities_by_tag", AsyncMock(return_value=[]))
        _ = await main_mod.get_entities_by_tag.__wrapped__(request, "tag-1", entity_types="Tools", db=MagicMock(), user={"email": "u"})

    async def test_get_a2a_agent_service_unavailable(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/a2a/a1")
        monkeypatch.setattr(main_mod, "a2a_service", None)

        with pytest.raises(HTTPException) as excinfo:
            await main_mod.get_a2a_agent.__wrapped__("a1", request, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

    async def test_create_a2a_agent_public_only_sets_team_id_none(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = _make_request("/a2a")
        request.state = SimpleNamespace(team_id="team-1", token_teams=[])

        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "u",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        svc = MagicMock()
        svc.register_agent = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(main_mod, "a2a_service", svc)

        _ = await main_mod.create_a2a_agent.__wrapped__(
            MagicMock(),
            request,
            team_id="team-1",
            visibility="public",
            db=MagicMock(),
            user={"email": "u"},
        )
        assert svc.register_agent.call_args.kwargs["team_id"] is None

    async def test_set_a2a_agent_state_service_unavailable(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod, "a2a_service", None)
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.set_a2a_agent_state.__wrapped__("a1", activate=True, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 503

    async def test_delete_tool_not_found_maps_to_404(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.tool_service import ToolNotFoundError

        monkeypatch.setattr(main_mod.tool_service, "delete_tool", AsyncMock(side_effect=ToolNotFoundError("missing")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.delete_tool.__wrapped__("t1", purge_metrics=False, db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 404

    async def test_create_resource_resource_error_maps_to_400(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod
        from mcpgateway.services.resource_service import ResourceError

        request = _make_request("/resources")
        request.state = SimpleNamespace(team_id=None, token_teams=["team-1"])

        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_creation_metadata",
            lambda *_a, **_k: {
                "created_by": "u",
                "created_from_ip": "127.0.0.1",
                "created_via": "api",
                "created_user_agent": "test",
                "import_batch_id": None,
                "federation_source": None,
            },
        )
        monkeypatch.setattr(main_mod.resource_service, "register_resource", AsyncMock(side_effect=ResourceError("bad")))
        with pytest.raises(HTTPException) as excinfo:
            await main_mod.create_resource.__wrapped__(MagicMock(), request, team_id=None, visibility="public", db=MagicMock(), user={"email": "u"})
        assert excinfo.value.status_code == 400

    async def test_get_prompt_reraises_unhandled_exception(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

        monkeypatch.setattr(main_mod.prompt_service, "get_prompt", AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            await main_mod.get_prompt.__wrapped__(request, "p1", args={}, db=MagicMock(), user={"email": "u"})

    def test_log_security_recommendations_skip_ssl_verify_line(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        monkeypatch.setattr(main_mod.settings, "skip_ssl_verify", True, raising=False)
        main_mod.log_security_recommendations({"secure_secrets": False, "auth_enabled": False})

    async def test_request_validation_exception_handler_ctx_non_dict(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.url = SimpleNamespace(path="/tools")

        exc = MagicMock()
        exc.errors.return_value = [{"loc": ["body"], "msg": "bad", "ctx": "ctx-not-a-dict", "type": "value_error"}]

        response = await main_mod.request_validation_exception_handler(request, exc)
        assert response.status_code == 422

    async def test_update_gateway_validation_error_branch(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        class FakeValidationError(Exception):
            """ValidationError branch in update_gateway is unreachable for pydantic.ValidationError (subclasses ValueError)."""

        request = _make_request("/gateways/gw1")
        monkeypatch.setattr(
            main_mod.MetadataCapture,
            "extract_modification_metadata",
            lambda *_a, **_k: {"modified_by": "u", "modified_from_ip": "127.0.0.1", "modified_via": "api", "modified_user_agent": "test"},
        )
        monkeypatch.setattr(main_mod, "ValidationError", FakeValidationError)
        monkeypatch.setattr(main_mod.gateway_service, "update_gateway", AsyncMock(side_effect=FakeValidationError("bad")))
        monkeypatch.setattr(main_mod.ErrorFormatter, "format_validation_error", MagicMock(return_value={"detail": "bad"}))

        response = await main_mod.update_gateway.__wrapped__("gw1", MagicMock(), request, db=MagicMock(), user={"email": "u"})
        assert response.status_code == 422
        assert json.loads(response.body.decode()) == {"detail": "bad"}

    async def test_lifespan_log_aggregation_timeout_and_cancellation(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        # Minimal startup config: only metrics aggregation auto-start.
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 0)  # triggers early return in run_log_backfill
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)

        # Patch services to keep startup/shutdown lightweight.
        monkeypatch.setattr(main_mod, "logging_service", make_service())
        monkeypatch.setattr(main_mod.logging_service, "configure_uvicorn_after_startup", MagicMock())
        for attr in (
            "tool_service",
            "resource_service",
            "prompt_service",
            "gateway_service",
            "root_service",
            "completion_service",
            "sampling_handler",
            "resource_cache",
            "streamable_http_session",
            "session_registry",
            "export_service",
            "import_service",
        ):
            monkeypatch.setattr(main_mod, attr, make_service())
        monkeypatch.setattr(main_mod, "a2a_service", None)

        # External dependencies
        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        # Cache invalidation subscriber
        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        # First-Party
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        # Log aggregator
        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        # Force TimeoutError in wait_for and ensure the coroutine is closed to avoid warnings.
        async def fake_wait_for(awaitable, timeout=None):  # noqa: ANN001
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError()

        async def fake_to_thread(_func, *args, **kwargs):  # noqa: ANN001
            # Yield control so task cancellation hits an await point.
            await asyncio.sleep(0.05)

        monkeypatch.setattr(main_mod.asyncio, "wait_for", fake_wait_for)
        monkeypatch.setattr(main_mod.asyncio, "to_thread", fake_to_thread)

        async with main_mod.lifespan(main_mod.app):
            await asyncio.sleep(0)

    async def test_lifespan_log_aggregation_timeout_branch(self, monkeypatch):
        """Specifically hit the TimeoutError -> continue branch in run_log_aggregation_loop."""
        # First-Party
        import mcpgateway.main as main_mod

        def make_service():  # noqa: ANN001 - local test helper
            service = MagicMock()
            service.initialize = AsyncMock()
            service.shutdown = AsyncMock()
            return service

        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr(main_mod.settings, "enable_header_passthrough", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_elicitation_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_buffer_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_cleanup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_rollup_enabled", False)
        monkeypatch.setattr(main_mod.settings, "sso_enabled", False)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_enabled", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_auto_start", True)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_backfill_hours", 0)
        monkeypatch.setattr(main_mod.settings, "metrics_aggregation_window_minutes", 0)

        monkeypatch.setattr(main_mod, "logging_service", make_service())
        monkeypatch.setattr(main_mod.logging_service, "configure_uvicorn_after_startup", MagicMock())
        for attr in (
            "tool_service",
            "resource_service",
            "prompt_service",
            "gateway_service",
            "root_service",
            "completion_service",
            "sampling_handler",
            "resource_cache",
            "streamable_http_session",
            "session_registry",
            "export_service",
            "import_service",
        ):
            monkeypatch.setattr(main_mod, attr, make_service())
        monkeypatch.setattr(main_mod, "a2a_service", None)

        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())
        monkeypatch.setattr(main_mod, "refresh_slugs_on_startup", MagicMock())
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        subscriber = MagicMock()
        subscriber.start = AsyncMock()
        subscriber.stop = AsyncMock()
        # First-Party
        import mcpgateway.cache.registry_cache as registry_cache_mod

        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        log_aggregator = MagicMock()
        log_aggregator.aggregation_window_minutes = 1
        log_aggregator.backfill = MagicMock()
        log_aggregator.aggregate_all_components = MagicMock()
        monkeypatch.setattr(main_mod, "get_log_aggregator", MagicMock(return_value=log_aggregator))

        monkeypatch.setattr(main_mod.asyncio, "to_thread", AsyncMock(return_value=None))

        state = {"calls": 0}

        async def fake_wait_for(awaitable, timeout=None):  # noqa: ANN001
            state["calls"] += 1
            if hasattr(awaitable, "close"):
                awaitable.close()
            if state["calls"] == 1:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.01)

        monkeypatch.setattr(main_mod.asyncio, "wait_for", fake_wait_for)

        async with main_mod.lifespan(main_mod.app):
            # Give the aggregation loop a chance to hit wait_for at least once.
            await asyncio.sleep(0.05)

    async def test_lifespan_reraises_unexpected_startup_error(self, monkeypatch):
        # First-Party
        import mcpgateway.main as main_mod

        # Keep startup/shutdown lightweight.
        monkeypatch.setattr(main_mod, "logging_service", MagicMock(initialize=AsyncMock(), shutdown=AsyncMock(), configure_uvicorn_after_startup=MagicMock()))
        monkeypatch.setattr(main_mod, "get_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod, "close_redis_client", AsyncMock())
        monkeypatch.setattr(main_mod.settings, "mcp_session_pool_enabled", False)
        monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr("mcpgateway.routers.llmchat_router.init_redis", AsyncMock())
        monkeypatch.setattr(main_mod, "init_telemetry", MagicMock())

        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", AsyncMock())
        monkeypatch.setattr("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", AsyncMock())

        # First-Party
        import mcpgateway.cache.registry_cache as registry_cache_mod

        subscriber = MagicMock()
        subscriber.stop = AsyncMock()
        monkeypatch.setattr(registry_cache_mod, "get_cache_invalidation_subscriber", MagicMock(return_value=subscriber))

        monkeypatch.setattr(main_mod, "shutdown_services", AsyncMock())
        monkeypatch.setattr(main_mod, "validate_security_configuration", MagicMock(side_effect=RuntimeError("boom")))

        with pytest.raises(RuntimeError, match="boom"):
            async with main_mod.lifespan(main_mod.app):
                pass

    async def test_module_level_structured_logging_and_static_mount_errors(self, monkeypatch):
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        # Keep router imports light.
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.observability", ModuleType("mcpgateway.routers.observability"))
        sys.modules["mcpgateway.routers.observability"].router = APIRouter()

        overrides = {
            "structured_logging_enabled": True,
            "mcpgateway_tool_cancellation_enabled": True,
            "mcpgateway_ui_enabled": True,
            "static_dir": "/tmp/definitely-missing-static-dir",
        }
        force_error = {
            "mcpgateway.routers.log_search",
            "mcpgateway.routers.cancellation_router",
        }

        mod = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error=force_error)
        await asyncio.sleep(0)

        # Cover favicon redirect logic (only registered when UI is enabled).
        resp = await mod.favicon_redirect()
        assert resp.status_code == 301

    async def test_module_level_llm_and_toolops_router_success_paths(self, monkeypatch):
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        # Stub router modules so include_router executes without importing heavy deps.
        llmchat_mod = ModuleType("mcpgateway.routers.llmchat_router")
        llmchat_mod.llmchat_router = APIRouter()
        llmchat_mod.init_redis = AsyncMock()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llmchat_router", llmchat_mod)

        llm_admin_mod = ModuleType("mcpgateway.routers.llm_admin_router")
        llm_admin_mod.llm_admin_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_admin_router", llm_admin_mod)

        llm_config_mod = ModuleType("mcpgateway.routers.llm_config_router")
        llm_config_mod.llm_config_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_config_router", llm_config_mod)

        llm_proxy_mod = ModuleType("mcpgateway.routers.llm_proxy_router")
        llm_proxy_mod.llm_proxy_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.llm_proxy_router", llm_proxy_mod)

        toolops_mod = ModuleType("mcpgateway.routers.toolops_router")
        toolops_mod.toolops_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.toolops_router", toolops_mod)

        overrides = {
            "llmchat_enabled": True,
            "toolops_enabled": True,
        }
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides)

    async def test_module_level_email_auth_and_sso_success(self, monkeypatch):
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        auth_mod = ModuleType("mcpgateway.routers.auth")
        auth_mod.auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.auth", auth_mod)

        email_auth_mod = ModuleType("mcpgateway.routers.email_auth")
        email_auth_mod.email_auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.email_auth", email_auth_mod)

        sso_mod = ModuleType("mcpgateway.routers.sso")
        sso_mod.sso_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.sso", sso_mod)

        overrides = {"email_auth_enabled": True, "sso_enabled": True}
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides)

    async def test_module_level_email_auth_and_sso_import_error(self, monkeypatch):
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        auth_mod = ModuleType("mcpgateway.routers.auth")
        auth_mod.auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.auth", auth_mod)

        email_auth_mod = ModuleType("mcpgateway.routers.email_auth")
        email_auth_mod.email_auth_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.email_auth", email_auth_mod)

        sso_mod = ModuleType("mcpgateway.routers.sso")
        sso_mod.sso_router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.sso", sso_mod)

        overrides = {"email_auth_enabled": True, "sso_enabled": True}
        # Force ImportError for SSO router to hit error logging branch.
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error={"mcpgateway.routers.sso"})

    async def test_module_level_auth_and_team_token_rbac_import_errors(self, monkeypatch):
        overrides = {"email_auth_enabled": True}
        force_error = {
            "mcpgateway.routers.auth",
            "mcpgateway.routers.teams",
            "mcpgateway.routers.tokens",
            "mcpgateway.routers.rbac",
        }
        _ = _import_fresh_main_module(monkeypatch, overrides=overrides, force_import_error=force_error)

    async def test_module_level_reverse_proxy_router_success(self, monkeypatch):
        # Standard
        from types import ModuleType

        # Third-Party
        from fastapi import APIRouter

        reverse_proxy_mod = ModuleType("mcpgateway.routers.reverse_proxy")
        reverse_proxy_mod.router = APIRouter()
        monkeypatch.setitem(sys.modules, "mcpgateway.routers.reverse_proxy", reverse_proxy_mod)

        _ = _import_fresh_main_module(monkeypatch, overrides={"mcpgateway_reverse_proxy_enabled": True})

    async def test_module_level_reverse_proxy_router_import_error(self, monkeypatch):
        _ = _import_fresh_main_module(
            monkeypatch,
            overrides={"mcpgateway_reverse_proxy_enabled": True},
            force_import_error={"mcpgateway.routers.reverse_proxy"},
        )

    async def test_module_level_skips_plugin_settings_validation_when_plugins_disabled(self, monkeypatch):
        # First-Party
        import mcpgateway.plugins.framework as plugin_framework

        # Reset plugin state before test
        plugin_framework.enable_plugins(False)
        plugin_framework.reset_plugin_manager_factory()

        _import_fresh_main_module(
            monkeypatch,
            env={
                "PLUGINS_ENABLED": "false",
                "PLUGINS_SERVER_PORT": "abc",
            },
        )
        # settings.enabled is False → get_plugin_manager() short-circuits to None
        result = await plugin_framework.get_plugin_manager()
        assert result is None

    async def test_module_level_uses_settings_backed_plugin_enablement(self, monkeypatch):
        # First-Party
        import mcpgateway.plugins.framework as plugin_framework
        import mcpgateway.plugins.framework.settings as plugin_settings_mod

        monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
        monkeypatch.setattr(
            plugin_settings_mod,
            "get_enabled_settings",
            lambda **_kwargs: SimpleNamespace(enabled=True),
        )
        monkeypatch.setattr(
            plugin_settings_mod,
            "get_startup_settings",
            lambda **_kwargs: SimpleNamespace(config_file="plugins/config.yaml", plugin_timeout=30),
        )

        class _DummyFactory:
            def __init__(self, *_a, **_k):
                pass

            async def get_manager(self, server_id=None):
                return SimpleNamespace(plugin_count=0)

        monkeypatch.setattr(plugin_framework, "TenantPluginManagerFactory", _DummyFactory)
        plugin_framework.reset_plugin_manager_factory()
        plugin_framework.enable_plugins(True)

        # Create the factory instance
        plugin_framework._plugin_manager_factory = _DummyFactory()

        _import_fresh_main_module(monkeypatch)
        # settings.enabled is True → get_plugin_manager() returns a manager
        result = await plugin_framework.get_plugin_manager()
        assert result is not None
        # Clean up the global factory to avoid polluting subsequent tests
        plugin_framework.reset_plugin_manager_factory()


class TestHardeningHelperCoverage:
    """Target helper branches added for hardening paths."""

    def test_get_request_identity_prefers_verified_payload_context(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(_jwt_verified_payload=("tok", {"sub": "u"}))

        with patch.object(main_mod, "_get_rpc_filter_context", return_value=("user@example.com", ["team-1"], True)):
            email, is_admin = main_mod._get_request_identity(request, {"email": "user@example.com", "is_admin": False})

        assert email == "user@example.com"
        assert is_admin is True

    def test_get_request_identity_uses_user_attribute_admin_fallback(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace()
        user = SimpleNamespace(is_admin=True)

        with (
            patch.object(main_mod, "_get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch.object(main_mod, "get_user_email", return_value="user@example.com"),
        ):
            email, is_admin = main_mod._get_request_identity(request, user)

        assert email == "user@example.com"
        assert is_admin is True

    def test_get_scoped_resource_access_context_admin_and_public_only(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace(_jwt_verified_payload=("tok", {"sub": "u"}))

        with patch.object(main_mod, "_get_rpc_filter_context", return_value=("user@example.com", None, True)):
            assert main_mod._get_scoped_resource_access_context(request, {"email": "user@example.com"}) == (None, None)

        with patch.object(main_mod, "_get_rpc_filter_context", return_value=("user@example.com", None, False)):
            assert main_mod._get_scoped_resource_access_context(request, {"email": "user@example.com"}) == ("user@example.com", [])

    @pytest.mark.asyncio
    async def test_assert_session_owner_or_admin_returns_404_for_missing_session(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        request.state = SimpleNamespace()

        with (
            patch.object(main_mod.session_registry, "get_session_owner", AsyncMock(return_value=None)),
            patch.object(main_mod.session_registry, "session_exists", AsyncMock(return_value=False)),
        ):
            with pytest.raises(HTTPException) as excinfo:
                await main_mod._assert_session_owner_or_admin(request, {"email": "user@example.com"}, "missing-session")

        assert excinfo.value.status_code == 404

    def test_enforce_scoped_resource_access_denies_on_failed_ownership_check(self):
        # First-Party
        import mcpgateway.main as main_mod

        request = MagicMock(spec=Request)
        db = MagicMock()

        with (
            patch.object(main_mod, "_get_scoped_resource_access_context", return_value=("user@example.com", ["team-1"])),
            patch.object(main_mod.token_scoping_middleware, "_check_resource_team_ownership", return_value=False),
        ):
            with pytest.raises(HTTPException) as excinfo:
                main_mod._enforce_scoped_resource_access(request, db, {"email": "user@example.com"}, "/servers/server-1")

        assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_protocol_completion_endpoint_direct_admin_null_teams_preserves_bypass(monkeypatch):
    """Direct call should preserve admin bypass semantics for completion endpoint."""
    # First-Party
    import mcpgateway.main as main_mod

    request = MagicMock(spec=Request)
    payload = {"ref": {"type": "ref/prompt", "name": "test"}}
    db = object()

    monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value=payload))
    monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("admin@example.com", None, True))
    completion_mock = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(main_mod.completion_service, "handle_completion", completion_mock)

    result = await main_mod.handle_completion(request=request, db=db, user={"email": "admin@example.com"})
    assert result == {"result": "ok"}
    assert completion_mock.await_args.args[0] is db
    assert completion_mock.await_args.args[1] == payload
    assert completion_mock.await_args.kwargs["user_email"] is None
    assert completion_mock.await_args.kwargs["token_teams"] is None


@pytest.mark.asyncio
async def test_protocol_completion_endpoint_direct_non_admin_none_teams_becomes_public_only(monkeypatch):
    """Direct call should normalize non-admin teams=None to public-only scope."""
    # First-Party
    import mcpgateway.main as main_mod

    request = MagicMock(spec=Request)
    payload = {"ref": {"type": "ref/prompt", "name": "test"}}
    db = object()

    monkeypatch.setattr(main_mod, "_read_request_json", AsyncMock(return_value=payload))
    monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("viewer@example.com", None, False))
    completion_mock = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(main_mod.completion_service, "handle_completion", completion_mock)

    result = await main_mod.handle_completion(request=request, db=db, user={"email": "viewer@example.com"})
    assert result == {"result": "ok"}
    assert completion_mock.await_args.args[0] is db
    assert completion_mock.await_args.args[1] == payload
    assert completion_mock.await_args.kwargs["user_email"] == "viewer@example.com"
    assert completion_mock.await_args.kwargs["token_teams"] == []


@pytest.mark.asyncio
async def test_handle_rpc_completion_direct_admin_null_teams_preserves_bypass(monkeypatch):
    """RPC completion direct path should preserve admin bypass context."""
    # First-Party
    import mcpgateway.main as main_mod

    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps({"jsonrpc": "2.0", "id": "rpc-id", "method": "completion/complete", "params": {"ref": {"type": "ref/prompt", "name": "p1"}}}).encode())
    request.headers = {}
    request.query_params = {}
    db = MagicMock()

    monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("admin@example.com", None, True))
    completion_mock = AsyncMock(return_value={"done": True})
    monkeypatch.setattr(main_mod.completion_service, "handle_completion", completion_mock)

    result = await main_mod.handle_rpc(request=request, db=db, user={"email": "admin@example.com"})
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "rpc-id"
    assert result["result"] == {"done": True}
    assert completion_mock.await_args.kwargs["user_email"] is None
    assert completion_mock.await_args.kwargs["token_teams"] is None


@pytest.mark.asyncio
async def test_handle_rpc_completion_direct_non_admin_none_teams_becomes_public_only(monkeypatch):
    """RPC completion direct path should normalize teams=None for non-admin callers."""
    # First-Party
    import mcpgateway.main as main_mod

    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps({"jsonrpc": "2.0", "id": "rpc-id", "method": "completion/complete", "params": {"ref": {"type": "ref/prompt", "name": "p1"}}}).encode())
    request.headers = {}
    request.query_params = {}
    db = MagicMock()

    monkeypatch.setattr(main_mod.settings, "mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr(main_mod, "_get_rpc_filter_context", lambda _req, _user: ("viewer@example.com", None, False))
    completion_mock = AsyncMock(return_value={"done": True})
    monkeypatch.setattr(main_mod.completion_service, "handle_completion", completion_mock)

    result = await main_mod.handle_rpc(request=request, db=db, user={"email": "viewer@example.com"})
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "rpc-id"
    assert result["result"] == {"done": True}
    assert completion_mock.await_args.kwargs["user_email"] == "viewer@example.com"
    assert completion_mock.await_args.kwargs["token_teams"] == []


class TestRpcScopedPermissions:
    """Verify token scopes.permissions are enforced per RPC method (#3422)."""

    @staticmethod
    def _make_request(payload: dict, scoped_permissions: list | None = None) -> MagicMock:
        """Build mock request with optional scoped permissions in JWT payload."""
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.headers = {}
        request.query_params = {}
        request.state = MagicMock()
        # Simulate JWT payload cached by verify_credentials middleware
        if scoped_permissions is not None:
            jwt_payload = {
                "sub": "user@example.com",
                "scopes": {"permissions": scoped_permissions},
            }
            request.state._jwt_verified_payload = ("fake-token", jwt_payload)
        else:
            request.state._jwt_verified_payload = None
        return request

    async def test_tools_list_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied tools/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_tools_list_allowed_with_tools_read_scope(self):
        """Token with tools.read scope should be allowed tools/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use", "tools.read"])

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_tools_list_allowed_with_wildcard_scope(self):
        """Token with wildcard scope should be allowed everything."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["*"])

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_tools_list_allowed_with_no_scoped_permissions(self):
        """Token with empty scopes (defer to RBAC) should be allowed."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=[])

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_tools_list_allowed_with_no_jwt_payload(self):
        """Session tokens without cached JWT payload should defer to RBAC."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=None)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_resources_list_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied resources/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_resources_read_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied resources/read."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "resource://x"}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_prompts_list_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied prompts/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_prompts_get_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied prompts/get."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "test"}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_list_gateways_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied list_gateways."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "list_gateways", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_tools_call_denied_with_tools_read_only(self):
        """Token with tools.read but not tools.execute should be denied tools/call."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "test", "arguments": {}}}
        request = self._make_request(payload, scoped_permissions=["servers.use", "tools.read"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_resources_templates_list_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied resources/templates/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "resources/templates/list", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_completion_complete_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied completion/complete."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "completion/complete", "params": {"ref": {}, "argument": {}}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_tools_list_allowed_with_non_dict_jwt_payload(self):
        """Cached JWT payload that is not a dict should defer to RBAC."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.headers = {}
        request.query_params = {}
        request.state = MagicMock()
        # Simulate a non-dict payload (e.g. a string or None)
        request.state._jwt_verified_payload = ("fake-token", "not-a-dict")

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_tools_list_allowed_with_empty_scopes_dict(self):
        """JWT payload where scopes is an empty dict should defer to RBAC."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        request = MagicMock(spec=Request)
        request.body = AsyncMock(return_value=json.dumps(payload).encode())
        request.headers = {}
        request.query_params = {}
        request.state = MagicMock()
        # Simulate JWT with empty scopes dict (no permissions key)
        jwt_payload = {"sub": "user@example.com", "scopes": {}}
        request.state._jwt_verified_payload = ("fake-token", jwt_payload)

        tool = MagicMock()
        tool.model_dump.return_value = {"id": "tool-1"}

        with (
            patch("mcpgateway.main.tool_service.list_tools", new=AsyncMock(return_value=([tool], None))),
            patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@example.com", None, False)),
            patch("mcpgateway.main.PermissionChecker.has_permission", new=AsyncMock(return_value=True)),
        ):
            result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
            assert "error" not in result

    async def test_list_roots_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied list_roots."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "list_roots", "params": {}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_resources_subscribe_denied_with_servers_use_only(self):
        """Token scoped to servers.use only should be denied resources/subscribe."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "resources/subscribe", "params": {"uri": "resource://x"}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]

    async def test_logging_set_level_allowed_with_admin_system_config(self):
        """Token scoped to admin.system_config should be allowed logging/setLevel."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "logging/setLevel", "params": {"level": "error"}}
        request = self._make_request(payload, scoped_permissions=["admin.system_config"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert "error" not in result

    async def test_logging_set_level_denied_without_admin_system_config(self):
        """Token scoped without admin.system_config should be denied logging/setLevel."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "logging/setLevel", "params": {"level": "error"}}
        request = self._make_request(payload, scoped_permissions=["servers.use"])

        result = await handle_rpc(request, db=MagicMock(), user={"email": "user@example.com"})
        assert result["error"]["code"] == -32003
        assert "Access denied" in result["error"]["message"]


@pytest.fixture
def auth_headers():
    """Default auth headers for testing."""
    return {"Authorization": "Bearer test_token"}
