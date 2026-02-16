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
        auth_is_enforced = settings.mcp_client_auth_enabled or settings.auth_required

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
