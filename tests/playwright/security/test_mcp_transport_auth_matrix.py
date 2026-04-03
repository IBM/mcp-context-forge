# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Transport authentication matrix for Streamable HTTP, SSE paths, and WebSocket."""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
from urllib.parse import urlparse
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from .conftest import BASE_URL


def _make_admin_jwt() -> str:
    return _create_jwt_token(
        {"sub": "admin@example.com"},
        user_data={"email": "admin@example.com", "is_admin": True, "auth_provider": "local"},
    )


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def _ws_url(path: str) -> str:
    parsed = urlparse(BASE_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{path}"


@pytest.fixture
def public_server_id(admin_api: APIRequestContext) -> str:
    response = admin_api.post(
        "/servers",
        data={
            "server": {"name": f"transport-public-{uuid.uuid4().hex[:8]}", "description": "transport auth matrix"},
            "team_id": None,
            "visibility": "public",
        },
    )
    if response.status == 404:
        pytest.skip("/servers endpoint unavailable in this environment")
    assert response.status in (200, 201), f"Failed to create public server: {response.status} {response.text()}"
    server_id = response.json()["id"]
    yield server_id
    with suppress(Exception):
        admin_api.delete(f"/servers/{server_id}")


class TestMCPTransportAuthMatrix:
    """Transport-level auth matrix aligned to MCP auth-mode manual testing."""

    def test_streamable_http_unauthenticated_behavior_matches_mode(self, anon_api: APIRequestContext, public_server_id: str):
        response = anon_api.post(
            f"/servers/{public_server_id}/mcp",
            data={"jsonrpc": "2.0", "id": "1", "method": "ping", "params": {}},
        )

        if response.status == 404:
            pytest.skip("Streamable HTTP endpoint unavailable in this environment")

        if settings.mcp_require_auth:
            assert response.status == 401, f"Strict mode must reject unauthenticated MCP calls, got {response.status}: {response.text()}"
            assert "authentication required" in response.text().lower()
        else:
            assert response.status != 401, f"Permissive mode should not return 401, got {response.status}: {response.text()}"

    def test_streamable_http_authenticated_not_rejected(self, playwright: Playwright, public_server_id: str):
        ctx = _api_context(playwright, _make_admin_jwt())
        try:
            response = ctx.post(
                f"/servers/{public_server_id}/mcp",
                data={"jsonrpc": "2.0", "id": "2", "method": "ping", "params": {}},
            )
        finally:
            ctx.dispose()

        if response.status == 404:
            pytest.skip("Streamable HTTP endpoint unavailable in this environment")
        assert response.status != 401, f"Authenticated MCP call unexpectedly rejected: {response.status} {response.text()}"

    def test_sse_message_endpoint_requires_auth(self, playwright: Playwright, anon_api: APIRequestContext, public_server_id: str):
        unauth_resp = anon_api.post(
            f"/servers/{public_server_id}/message?session_id=security-test",
            data={"jsonrpc": "2.0", "id": "1", "method": "ping", "params": {}},
        )
        assert unauth_resp.status in (401, 403), f"SSE message endpoint should require auth, got {unauth_resp.status}: {unauth_resp.text()}"

        auth_ctx = _api_context(playwright, _make_admin_jwt())
        try:
            auth_resp = auth_ctx.post(
                f"/servers/{public_server_id}/message?session_id=security-test",
                data={"jsonrpc": "2.0", "id": "2", "method": "ping", "params": {}},
            )
        finally:
            auth_ctx.dispose()

        assert auth_resp.status not in (401, 403), f"Authenticated SSE message call should not fail auth, got {auth_resp.status}: {auth_resp.text()}"

    def test_websocket_auth_handshake_behavior(self):
        ws_path = "/ws"
        unauth_url = _ws_url(ws_path)
        relay_enabled = settings.mcpgateway_ws_relay_enabled
        auth_is_enforced = settings.mcp_client_auth_enabled or settings.auth_required

        # /ws relay is feature-flagged and disabled by default in secure deployments.
        if not relay_enabled:
            auth_url = f"{unauth_url}?token={_make_admin_jwt()}"
            blocked = False
            try:
                with connect(auth_url, open_timeout=5, close_timeout=2) as websocket:
                    try:
                        websocket.recv(timeout=2)
                    except ConnectionClosed as close_error:
                        blocked = close_error.code == 1008
            except InvalidStatus as status_error:
                status_code = status_error.response.status_code
                if status_code == 404:
                    pytest.skip("WebSocket endpoint unavailable in this environment")
                blocked = status_code >= 400
            except OSError as exc:
                pytest.skip(f"WebSocket endpoint unavailable: {exc}")

            assert blocked, "WebSocket relay should reject connections when MCPGATEWAY_WS_RELAY_ENABLED=false"
            return

        if auth_is_enforced:
            blocked = False
            try:
                with connect(unauth_url, open_timeout=5, close_timeout=2) as websocket:
                    try:
                        websocket.recv(timeout=2)
                    except ConnectionClosed as close_error:
                        blocked = close_error.code == 1008
            except InvalidStatus as status_error:
                status_code = status_error.response.status_code
                if status_code == 404:
                    pytest.skip("WebSocket endpoint unavailable in this environment")
                blocked = status_code >= 400
            except OSError as exc:
                pytest.skip(f"WebSocket endpoint unavailable: {exc}")

            assert blocked, "Unauthenticated WebSocket should be blocked when auth is enforced"

        auth_url = f"{unauth_url}?token={_make_admin_jwt()}"
        try:
            with connect(auth_url, open_timeout=5, close_timeout=2) as websocket:
                websocket.send("not-json")
                response = websocket.recv(timeout=5)
        except OSError as exc:
            pytest.skip(f"WebSocket endpoint unavailable: {exc}")

        assert isinstance(response, str)
        assert "Parse error" in response or "jsonrpc" in response


class TestApiTokenLastUsedViaMCP:
    """Verify API token last_used is updated when accessing virtual servers via MCP Streamable HTTP."""

    @pytest.fixture(autouse=True)
    def _api_token(self, admin_api: APIRequestContext, playwright: Playwright):
        """Create an API token via session JWT and expose its access_token and id."""
        # admin_api uses a session JWT, which CAN create tokens
        resp = admin_api.post("/tokens", data={"name": f"last-used-test-{uuid.uuid4().hex[:8]}", "expires_in_days": 1})
        if resp.status == 404:
            pytest.skip("/tokens endpoint unavailable")
        assert resp.status in (200, 201), f"Failed to create token: {resp.status} {resp.text()}"
        payload = resp.json()
        self._access_token = payload["access_token"]
        token_obj = payload.get("token", payload)
        self._token_id = token_obj.get("id") or token_obj.get("token_id")
        yield
        # cleanup: revoke the token
        with suppress(Exception):
            admin_api.delete(f"/tokens/{self._token_id}")

    def test_mcp_streamable_http_updates_last_used(self, admin_api: APIRequestContext, playwright: Playwright, public_server_id: str):
        """Accessing /servers/{id}/mcp with an API token should update last_used."""
        # 1. Check initial last_used (should be None for new token)
        detail = admin_api.get(f"/tokens/{self._token_id}")
        if detail.status == 404:
            pytest.skip("Token detail endpoint unavailable")
        initial_last_used = detail.json().get("last_used")

        # 2. Make MCP Streamable HTTP request with the API token
        token_ctx = _api_context(playwright, self._access_token)
        try:
            mcp_resp = token_ctx.post(
                f"/servers/{public_server_id}/mcp",
                data={"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "e2e-test", "version": "1.0.0"}}},
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
        finally:
            token_ctx.dispose()

        if mcp_resp.status == 404:
            pytest.skip("Streamable HTTP endpoint unavailable")
        assert mcp_resp.status != 401, f"API token auth rejected: {mcp_resp.text()}"

        # 3. Verify last_used was updated
        # Standard
        import time

        time.sleep(2)  # Allow async update to complete
        detail2 = admin_api.get(f"/tokens/{self._token_id}")
        updated_last_used = detail2.json().get("last_used")

        assert updated_last_used is not None, f"last_used not updated after MCP access. Initial: {initial_last_used}, After: {updated_last_used}"

    def test_mcp_request_records_token_usage_log(self, admin_api: APIRequestContext, playwright: Playwright, public_server_id: str):
        """MCP requests with API tokens should appear in the token usage log."""
        token_ctx = _api_context(playwright, self._access_token)
        try:
            token_ctx.post(
                f"/servers/{public_server_id}/mcp",
                data={"jsonrpc": "2.0", "id": "2", "method": "ping", "params": {}},
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
        finally:
            token_ctx.dispose()

        # Standard
        import time

        time.sleep(2)
        usage_resp = admin_api.get(f"/tokens/{self._token_id}/usage")
        if usage_resp.status == 404:
            pytest.skip("Token usage endpoint unavailable")
        assert usage_resp.status == 200, f"Usage stats failed: {usage_resp.status}"
        total = usage_resp.json().get("total_requests", 0)
        assert total > 0, f"Token usage log should have entries after MCP access, got {total}"
