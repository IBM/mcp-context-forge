# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tool_preview.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for the tool preview (dry-run) endpoint, exercised through
the real HTTP endpoints (auth, RBAC, routing) rather than mocked handler
internals.

Covers:
  - POST /tools/preview/{name:path}          (legacy prefix)
  - POST /v1/tools/preview/{name:path}       (canonical v1 prefix)
  - Deny paths: unauthenticated (401), missing tools.preview permission (403),
    tool not found (404), feature flag disabled (404) -- required by #5629's
    acceptance criteria.
  - Leak-check: the response body for a federated tool never contains the
    remote gateway's URL, transport, or credentials.

Mirrors the patterns established in tests/integration/test_resource_management.py
(TestResourceByUriIntegration) for the sibling GET /resources/test/{uri} endpoint.
"""

# Future
from __future__ import annotations

# Standard
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
from fastapi import HTTPException, status as http_status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.main import app
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db, get_permission_service
from mcpgateway.schemas import ToolAnnotations, ToolPreviewResponse, ToolPreviewTarget
from mcpgateway.services.tool_service import ToolNotFoundError
from mcpgateway.utils.verify_credentials import require_auth

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


class _PermissionServiceAlwaysGrant:
    """Minimal permission-service stand-in that grants every check.

    `require_permission` instantiates `PermissionService(db)` directly inside
    its wrapper rather than resolving it via FastAPI DI, so the class itself
    must be patched -- overriding the `get_permission_service` dependency
    alone is not enough.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, *args, **kwargs) -> bool:
        return True

    async def check_admin_permission(self, *args, **kwargs) -> bool:
        return True


class _PermissionServiceDenyPreview:
    """Grants every permission except tools.preview -- for the 403 deny-path test."""

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, *args, **kwargs) -> bool:
        return kwargs.get("permission") != "tools.preview"

    async def check_admin_permission(self, *args, **kwargs) -> bool:
        return True


def _sample_local_response() -> ToolPreviewResponse:
    return ToolPreviewResponse(
        validated=True,
        resolved_arguments={"city": "London"},
        target=ToolPreviewTarget(kind="local"),
        annotations=ToolAnnotations(),
        pre_hooks_run=[],
        warnings=[],
    )


def _sample_federated_response() -> ToolPreviewResponse:
    return ToolPreviewResponse(
        validated=True,
        resolved_arguments={"city": "London"},
        target=ToolPreviewTarget(kind="federated", gateway_name="remote-gw"),
        annotations=ToolAnnotations(),
        pre_hooks_run=[],
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _auth_client():
    """FastAPI TestClient backed by a real SQLite DB with auth fully mocked out
    and every permission granted. Mirrors test_resource_management.py's fixture
    of the same name for the sibling GET /resources/test/{uri} endpoint."""
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # First-Party
    from mcpgateway.config import settings as _settings
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    mp.setattr(_settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    mock_email_user = MagicMock()
    mock_email_user.email = "integration-test-user@example.com"
    mock_email_user.full_name = "Integration Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def _mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "integration-test-user@example.com",
                "full_name": "Integration Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def _mock_get_permission_service(*args, **kwargs):
        return _PermissionServiceAlwaysGrant()

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceAlwaysGrant):
        app.dependency_overrides[require_auth] = lambda: "integration-test-user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = _mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = _mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = _override_get_db

        client = TestClient(app, raise_server_exceptions=False)
        auth_headers = {"Authorization": "Bearer integration.test.token"}  # pragma: allowlist secret
        yield client, auth_headers

        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


# ---------------------------------------------------------------------------
# Integration test class: POST /[v1/]tools/preview/{name:path}
# ---------------------------------------------------------------------------


class TestToolPreviewIntegration:
    """Integration tests for POST /[v1/]tools/preview/{name:path} (#5629).

    These tests exercise the full ASGI middleware stack -- authentication,
    RBAC, routing, and the service call -- rather than mocking individual
    handler internals as the unit tests in
    tests/unit/mcpgateway/services/test_tool_service_preview.py do.
    """

    # ------------------------------------------------------------------
    # Authenticated success paths
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_authenticated_success_returns_200(self, mock_preview, _auth_client):
        """Authenticated POST /tools/preview/{name} returns 200 wrapping service output."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_local_response()

        response = client.post("/tools/preview/get_weather", json={"arguments": {"city": "London"}}, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["validated"] is True
        assert body["target"]["kind"] == "local"
        mock_preview.assert_awaited_once()

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_v1_prefix_authenticated_success_returns_200(self, mock_preview, _auth_client):
        """Authenticated POST /v1/tools/preview/{name} routes to the same handler."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_local_response()

        response = client.post("/v1/tools/preview/get_weather", json={"arguments": {"city": "London"}}, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["validated"] is True

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_empty_body_defaults_to_no_arguments(self, mock_preview, _auth_client):
        """Omitting the request body must not 422 -- arguments defaults to {}."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_local_response()

        response = client.post("/tools/preview/get_weather", headers=auth_headers)

        assert response.status_code == 200
        call_kwargs = mock_preview.call_args.kwargs
        assert call_kwargs["arguments"] == {}

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_tool_name_with_path_segments_preserved(self, mock_preview, _auth_client):
        """The {name:path} converter passes multi-segment tool names through verbatim."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_local_response()

        client.post("/tools/preview/gateway-slug/tool-name", json={"arguments": {}}, headers=auth_headers)

        assert mock_preview.call_args.kwargs["name"] == "gateway-slug/tool-name"

    # ------------------------------------------------------------------
    # Federation policy / leak-check (#5629)
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_federated_tool_response_never_leaks_gateway_internals(self, mock_preview, _auth_client):
        """A federated tool's preview response must carry the gateway name only --
        never its URL, transport, or credentials, regardless of what the service
        might (incorrectly) be asked to return elsewhere in the stack."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_federated_response()

        response = client.post("/tools/preview/remote_tool", json={"arguments": {"city": "London"}}, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["target"]["kind"] == "federated"
        # BaseModelWithConfigDict serializes with by_alias=True -> camelCase over the wire.
        assert body["target"]["gatewayName"] == "remote-gw"

        raw_body = response.text
        for leaked in ("http://", "https://", "auth_value", "client_key", "oauth_config", "Bearer ", "password"):
            assert leaked not in raw_body, f"preview response leaked a gateway-internal marker: {leaked!r}"

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_tool_not_found_returns_404(self, mock_preview, _auth_client):
        """Service raising ToolNotFoundError -> HTTP 404 (same mapping as invoke_tool)."""
        client, auth_headers = _auth_client
        mock_preview.side_effect = ToolNotFoundError("Tool not found: missing_tool")

        response = client.post("/tools/preview/missing_tool", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_v1_prefix_tool_not_found_returns_404(self, mock_preview, _auth_client):
        """Same 404 behaviour via the /v1 prefix."""
        client, auth_headers = _auth_client
        mock_preview.side_effect = ToolNotFoundError("Tool not found: missing_tool")

        response = client.post("/v1/tools/preview/missing_tool", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 404

    # ------------------------------------------------------------------
    # Authorisation rejection (missing tools.preview permission)
    # ------------------------------------------------------------------

    def test_authenticated_but_missing_tools_preview_permission_returns_403(self, _auth_client):
        """Authenticated caller whose role lacks tools.preview must get 403, not 200/404 --
        tools.preview is a distinct permission from tools.read/tools.execute (#5629).

        Nests a stricter PermissionService patch inside `_auth_client`'s own (module-scoped,
        always-grant) patch rather than using a second override-fixture: two fixtures both
        mutating the shared, global `app.dependency_overrides` dict for the whole module
        would clobber each other depending on pytest's fixture-teardown ordering.
        """
        client, auth_headers = _auth_client

        with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceDenyPreview):
            response = client.post("/tools/preview/get_weather", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 403

    def test_v1_authenticated_but_missing_tools_preview_permission_returns_403(self, _auth_client):
        """Same 403 behaviour via the /v1 prefix."""
        client, auth_headers = _auth_client

        with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceDenyPreview):
            response = client.post("/v1/tools/preview/get_weather", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 403

    # ------------------------------------------------------------------
    # Feature flag
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_feature_disabled_returns_404(self, mock_preview, _auth_client):
        """MCPGATEWAY_TOOL_PREVIEW_ENABLED=false must 404 before the service is ever called."""
        client, auth_headers = _auth_client

        with patch.object(settings, "mcpgateway_tool_preview_enabled", False):
            response = client.post("/tools/preview/get_weather", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 404
        assert "disabled" in response.json()["detail"].lower()
        mock_preview.assert_not_awaited()

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_v1_feature_disabled_returns_404(self, mock_preview, _auth_client):
        """Same 404-when-disabled behaviour via the /v1 prefix."""
        client, auth_headers = _auth_client

        with patch.object(settings, "mcpgateway_tool_preview_enabled", False):
            response = client.post("/v1/tools/preview/get_weather", json={"arguments": {}}, headers=auth_headers)

        assert response.status_code == 404
        mock_preview.assert_not_awaited()


# ---------------------------------------------------------------------------
# Legacy / v1 parity (POST-specific; the shared GET-only ROUTE_PAIRS list in
# tests/integration/test_token_scoping_v1.py can't exercise a POST-only route
# meaningfully -- a GET against it 405s identically regardless of auth).
# ---------------------------------------------------------------------------


class TestToolPreviewLegacyV1Parity:
    """Both mounts of the preview route must behave identically for the same request.

    `_auth_client`-based parity check only -- the unauthenticated variant lives in
    TestToolPreviewUnauthenticated at the end of this module (see that class's
    docstring for why: `app_with_temp_db`-based tests and `_auth_client`-based tests
    share the same global `app.dependency_overrides` dict, and only the latter's
    generator-fixture teardown restores it correctly).
    """

    @patch("mcpgateway.main.tool_service.preview_tool_invocation", new_callable=AsyncMock)
    def test_authenticated_success_parity(self, mock_preview, _auth_client):
        """Legacy and /v1 must return the same status and body shape for the same request."""
        client, auth_headers = _auth_client
        mock_preview.return_value = _sample_local_response()

        legacy_resp = client.post("/tools/preview/get_weather", json={"arguments": {"city": "London"}}, headers=auth_headers)
        v1_resp = client.post("/v1/tools/preview/get_weather", json={"arguments": {"city": "London"}}, headers=auth_headers)

        assert legacy_resp.status_code == v1_resp.status_code == 200
        assert legacy_resp.json() == v1_resp.json()


# ---------------------------------------------------------------------------
# Unauthenticated deny-path tests -- deliberately last in this module.
#
# `app_with_temp_db` and `_auth_client` both mutate FastAPI's global, shared
# `app.dependency_overrides` dict for the same `app` singleton. `_auth_client`
# is a module-scoped generator fixture that sets its overrides once and restores
# them only when its `yield` resumes at module teardown; a test using
# `app_with_temp_db` that does `app_with_temp_db.dependency_overrides[key] = ...`
# then `.pop(key, None)` in a `finally` block does not know about (or restore)
# whatever `_auth_client` had put there -- it just deletes the key outright. Any
# `_auth_client`-based test that ran *after* one of these would silently lose its
# auth override and start hitting the real, unmocked auth path (401 instead of
# whatever it expected). Keeping every `app_with_temp_db`-based test in one class
# at the end of the module sidesteps this without needing a real fix upstream.
# ---------------------------------------------------------------------------


class TestToolPreviewUnauthenticated:
    """Deny-path coverage for a caller with no credentials at all."""

    def test_unauthenticated_request_returns_401(self, app_with_temp_db):
        """POST /tools/preview/{name} without credentials must be rejected with 401."""

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            unauthenticated_client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            response = unauthenticated_client.post("/tools/preview/get_weather", json={"arguments": {}})
            assert response.status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)

    def test_v1_unauthenticated_request_returns_401(self, app_with_temp_db):
        """POST /v1/tools/preview/{name} without credentials must also return 401."""

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            unauthenticated_client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            response = unauthenticated_client.post("/v1/tools/preview/get_weather", json={"arguments": {}})
            assert response.status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)

    def test_unauthenticated_parity(self, app_with_temp_db):
        """Legacy and /v1 must reject an unauthenticated POST identically."""

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            legacy_resp = client.post("/tools/preview/get_weather", json={"arguments": {}})
            v1_resp = client.post("/v1/tools/preview/get_weather", json={"arguments": {}})
            assert legacy_resp.status_code == v1_resp.status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
