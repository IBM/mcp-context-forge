# -*- coding: utf-8 -*-
"""Location: ./tests/e2e_rust/test_mcp_session_isolation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Compose-backed MCP session/auth isolation tests for the Rust transport path.

These tests focus on security and correctness, not throughput. They validate
that MCP session ownership stays bound to the original caller context and does
not leak across:

- another user in the same team with otherwise-valid access
- a user outside the team
- the same email presenting a different, narrower token

The suite uses the live docker-compose stack and real REST setup calls so it
exercises PostgreSQL, Redis, nginx, Python auth/RBAC, and the Rust MCP runtime
end to end.
"""

# Future
from __future__ import annotations

# Standard
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime
import json
import os
import time
from typing import Any, Generator
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, TEST_PASSWORD, skip_no_gateway, skip_no_rust_mcp_gateway, skip_no_rust_mcp_session_core

pytestmark = [pytest.mark.e2e, skip_no_gateway, skip_no_rust_mcp_gateway, skip_no_rust_mcp_session_core]

MCP_PROTOCOL_VERSION = "2025-11-25"
ISOLATION_PREFIX = "mcp-iso"
SESSION_AUTH_REUSE_TTL_SECONDS = int(os.getenv("MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS", "30"))
SESSION_AUTH_REUSE_GRACE_SECONDS = int(os.getenv("MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS", "15"))


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    """Create a JWT suitable for compose-backed E2E tests."""
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
        secret=JWT_SECRET,
    )


def _json_headers(token: str) -> dict[str, str]:
    """Build standard JSON API headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> Any:
    """Send an API request and return the JSON payload."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
    return response.json() if response.content else None


def _resolve_role_id(admin_client: httpx.Client, role_name: str) -> str:
    """Resolve an RBAC role name to its UUID."""
    roles = _request_json(admin_client, "GET", "/rbac/roles")
    for role in roles:
        if role.get("name") == role_name:
            return role["id"]
    raise AssertionError(f"RBAC role '{role_name}' not found")


def _create_user(
    admin_client: httpx.Client,
    *,
    email: str,
    team_id: str | None = None,
    role_name: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    """Create a user, optionally add team membership/role, and mint an API token."""
    _request_json(
        admin_client,
        "POST",
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": f"Isolation Test {email.split('@', maxsplit=1)[0]}",
            "is_admin": is_admin,
            "is_active": True,
            "password_change_required": False,
        },
    )

    if team_id:
        _request_json(
            admin_client,
            "POST",
            f"/teams/{team_id}/members",
            json={"email": email, "role": "member"},
        )

    role_id = None
    if role_name and team_id:
        role_id = _resolve_role_id(admin_client, role_name)
        _request_json(
            admin_client,
            "POST",
            f"/rbac/users/{email}/roles",
            json={"role_id": role_id, "scope": "team", "scope_id": team_id},
        )

    user_jwt = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    with httpx.Client(base_url=BASE_URL, headers=_json_headers(user_jwt), timeout=20.0) as user_client:
        token_payload: dict[str, Any] = {
            "name": f"{ISOLATION_PREFIX}-token-{uuid.uuid4().hex[:8]}",
            "expires_in_days": 1,
        }
        if team_id:
            token_payload["team_id"] = team_id
        token_response = _request_json(
            user_client,
            "POST",
            "/tokens",
            json=token_payload,
        )

    token_obj = token_response.get("token", token_response)
    return {
        "email": email,
        "access_token": token_response["access_token"],
        "token_id": token_obj.get("id") or token_obj.get("token_id"),
        "team_id": team_id,
        "role": role_name,
        "role_id": role_id,
        "is_admin": is_admin,
    }


def _cleanup_user(admin_client: httpx.Client, user_info: dict[str, Any]) -> None:
    """Best-effort cleanup for a created test user and token."""
    token_id = user_info.get("token_id")
    if token_id:
        with suppress(Exception):
            admin_client.delete(f"/tokens/admin/{token_id}")
    with suppress(Exception):
        admin_client.delete(f"/auth/email/admin/users/{user_info['email']}")


def _mcp_url(server_id: str) -> str:
    """Return the server-scoped MCP endpoint path."""
    return f"/servers/{server_id}/mcp/"


def _mcp_headers(token: str, *, session_id: str | None = None, accept: str = "application/json, text/event-stream") -> dict[str, str]:
    """Build MCP transport headers."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def _initialize_session(
    token: str,
    server_id: str,
) -> tuple[httpx.Response, dict[str, Any], str]:
    """Initialize a live MCP session and return the response, payload, and session id."""
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        response = client.post(
            _mcp_url(server_id),
            headers=_mcp_headers(token),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-session-isolation", "version": "1.0.0"},
                },
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    session_id = response.headers.get("mcp-session-id")
    assert session_id, f"Missing mcp-session-id header: {response.headers}"
    assert response.headers.get("x-contextforge-mcp-runtime") == "rust"
    return response, payload, session_id


def _mcp_post(
    token: str,
    server_id: str,
    *,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    request_id: int | str = 1,
) -> httpx.Response:
    """Send a direct JSON-RPC POST to the MCP endpoint."""
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        return client.post(
            _mcp_url(server_id),
            headers=_mcp_headers(token, session_id=session_id),
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            },
        )


def _assert_denied(response: httpx.Response) -> None:
    """Assert that a transport or JSON-RPC request was denied without leaking data."""
    if response.status_code in (401, 403, 404):
        if response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
            body_text = json.dumps(body).lower()
            assert "denied" in body_text or "not found" in body_text or "access" in body_text or "revoked" in body_text or "invalid" in body_text, body
        return

    assert response.status_code == 200, response.text
    body = response.json()
    if "error" in body:
        error = body["error"]
        assert error.get("code") in (-32003, -32600), body
        error_message = str(error.get("message", "")).lower()
        assert "denied" in error_message or "not found" in error_message or "revoked" in error_message or "invalid" in error_message, body
        return

    result = body.get("result", {})
    assert result.get("isError", False), body
    content = result.get("content", [{}])
    message = str(content[0].get("text", "")).lower() if content else ""
    assert "denied" in message or "not found" in message or "revoked" in message or "invalid" in message, body


def _extract_tool_names(response: httpx.Response) -> list[str]:
    """Extract tool names from a successful tools/list response."""
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    tools = payload["result"].get("tools", [])
    return [tool["name"] for tool in tools]


def _select_time_gateway(gateways: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Select a compose-backed streamable HTTP gateway with live time tools.

    Prefer the canonical ``fast_time`` gateway when available, but fall back
    to ``fast_test`` on clean rebuilds where the ``register_fast_time`` helper
    has not yet succeeded. The isolation suite validates session/auth binding,
    so any live MCP gateway with a time tool is sufficient.
    """
    tool_counts_by_gateway: dict[str, int] = {}
    for tool in tools:
        gateway_id = tool.get("gatewayId")
        if gateway_id:
            tool_counts_by_gateway[gateway_id] = tool_counts_by_gateway.get(gateway_id, 0) + 1

    preferred_names = ("fast_time", "fast_test")
    for preferred_name in preferred_names:
        for candidate in gateways:
            if candidate.get("name") == preferred_name and candidate.get("transport") == "STREAMABLEHTTP" and tool_counts_by_gateway.get(candidate.get("id"), 0) > 0:
                return candidate

    for candidate in gateways:
        url = str(candidate.get("url", ""))
        if candidate.get("transport") == "STREAMABLEHTTP" and tool_counts_by_gateway.get(candidate.get("id"), 0) > 0 and ("fast_time_server:8080/http" in url or "fast_test_server:8880/mcp" in url):
            return candidate

    raise AssertionError("No compose-backed time-capable STREAMABLEHTTP gateway with synced tools found")


def _find_tool_name(tool_names: list[str], fragment: str) -> str:
    """Find a tool name by substring match."""
    for name in tool_names:
        if fragment in name:
            return name
    raise AssertionError(f"Expected a tool containing '{fragment}', got {tool_names}")


def _request_denied(response: httpx.Response) -> bool:
    """Return True when a transport or JSON-RPC response clearly denies access."""
    if response.status_code in (401, 403, 404):
        return True
    if response.status_code != 200:
        return False
    payload = response.json()
    if "error" in payload:
        message = str(payload["error"].get("message", "")).lower()
        return "denied" in message or "not found" in message or "revoked" in message
    result = payload.get("result", {})
    if result.get("isError", False):
        content = result.get("content", [{}])
        message = str(content[0].get("text", "")).lower() if content else ""
        return "denied" in message or "not found" in message or "revoked" in message
    return False


def _wait_for_session_denial(
    token: str,
    server_id: str,
    *,
    session_id: str,
    method: str,
    params: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
) -> httpx.Response:
    """Poll until a session-bound request is denied or the bounded TTL contract is violated."""
    deadline = time.time() + float(timeout_seconds if timeout_seconds is not None else SESSION_AUTH_REUSE_TTL_SECONDS + SESSION_AUTH_REUSE_GRACE_SECONDS)
    last_response = None
    while time.time() < deadline:
        last_response = _mcp_post(
            token,
            server_id,
            method=method,
            params=params,
            session_id=session_id,
            request_id=f"wait-{uuid.uuid4().hex[:8]}",
        )
        if _request_denied(last_response):
            return last_response
        time.sleep(1.0)

    raise AssertionError("Session remained usable beyond the bounded auth-reuse TTL contract: " f"status={getattr(last_response, 'status_code', None)} " f"body={getattr(last_response, 'text', None)}")


def _revoke_team_role(admin_client: httpx.Client, user_info: dict[str, Any]) -> None:
    """Revoke a team-scoped RBAC role from a test user."""
    role_id = user_info.get("role_id")
    team_id = user_info.get("team_id")
    assert role_id and team_id, f"User is missing role assignment details: {user_info}"
    response = admin_client.delete(
        f"/rbac/users/{user_info['email']}/roles/{role_id}",
        params={"scope": "team", "scope_id": team_id},
    )
    assert response.status_code == 200, response.text


def _extract_text_result(response: httpx.Response) -> str:
    """Extract the first text content item from a successful tools/call response."""
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    result = payload["result"]
    assert not result.get("isError", False), payload
    return result.get("content", [{}])[0].get("text", "")


def _extract_primary_text_line(response: httpx.Response) -> str:
    """Extract the primary first line from a successful text response.

    Plugin parity stacks may append deterministic sentinels after the primary
    tool output; session-isolation freshness checks only care about the leading
    timestamp payload.
    """
    return _extract_text_result(response).splitlines()[0]


@pytest.fixture(scope="module")
def admin_client() -> Generator[httpx.Client, None, None]:
    """Admin-authenticated API client for test setup and cleanup."""
    token = _make_jwt("admin@example.com", is_admin=True, teams=None)
    with httpx.Client(base_url=BASE_URL, headers=_json_headers(token), timeout=20.0) as client:
        yield client


@pytest.fixture(scope="module")
def isolation_environment(admin_client: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Create a dedicated team-scoped MCP server and the users needed for isolation checks."""
    team_name = f"{ISOLATION_PREFIX}-team-{uuid.uuid4().hex[:8]}"
    team = _request_json(
        admin_client,
        "POST",
        "/teams/",
        json={"name": team_name, "description": "Rust MCP session isolation team", "visibility": "private"},
    )
    team_id = team["id"]

    tools = _request_json(admin_client, "GET", "/tools")
    gateways = _request_json(admin_client, "GET", "/gateways")
    gateway = _select_time_gateway(gateways, tools)
    gateway_id = gateway["id"]

    tool_ids = [tool["id"] for tool in tools if tool.get("gatewayId") == gateway_id]
    assert tool_ids, f"No tools found for gateway {gateway_id}"

    server = _request_json(
        admin_client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": f"{ISOLATION_PREFIX}-server-{uuid.uuid4().hex[:8]}",
                "description": "Rust MCP session isolation virtual server",
                "associated_tools": tool_ids,
                "associated_resources": [],
                "associated_prompts": [],
            },
            "team_id": team_id,
            "visibility": "team",
        },
    )
    server_id = server["id"]

    users = {
        "owner": _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-owner-{uuid.uuid4().hex[:8]}@test.com",
            team_id=team_id,
            role_name="developer",
        ),
        "peer": _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-peer-{uuid.uuid4().hex[:8]}@test.com",
            team_id=team_id,
            role_name="developer",
        ),
        "outsider": _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-outsider-{uuid.uuid4().hex[:8]}@test.com",
        ),
    }

    try:
        yield {
            "team_id": team_id,
            "server_id": server_id,
            "users": users,
        }
    finally:
        with suppress(Exception):
            admin_client.delete(f"/servers/{server_id}")
        for user in users.values():
            _cleanup_user(admin_client, user)
        with suppress(Exception):
            admin_client.delete(f"/teams/{team_id}")


class TestMcpSessionIsolation:
    """End-to-end MCP session ownership and auth-binding isolation tests."""

    def test_same_team_peer_can_access_server_but_not_owner_session(self, isolation_environment: dict[str, Any]) -> None:
        """A same-team user may use the server, but not another user's session."""
        server_id = isolation_environment["server_id"]
        owner = isolation_environment["users"]["owner"]
        peer = isolation_environment["users"]["peer"]

        _, _, owner_session_id = _initialize_session(owner["access_token"], server_id)
        peer_init_response, _, _ = _initialize_session(peer["access_token"], server_id)
        assert peer_init_response.headers.get("x-contextforge-mcp-runtime") == "rust"

        owner_tools = _extract_tool_names(_mcp_post(owner["access_token"], server_id, method="tools/list", session_id=owner_session_id, request_id=2))
        assert owner_tools, "Owner should see team-scoped tools"

        peer_hijack = _mcp_post(
            peer["access_token"],
            server_id,
            method="tools/list",
            session_id=owner_session_id,
            request_id=3,
        )
        _assert_denied(peer_hijack)

    def test_same_email_public_only_token_cannot_reuse_owner_session(self, isolation_environment: dict[str, Any]) -> None:
        """A narrower same-email session token must not inherit a team-scoped MCP session."""
        server_id = isolation_environment["server_id"]
        owner = isolation_environment["users"]["owner"]
        _, _, owner_session_id = _initialize_session(owner["access_token"], server_id)

        public_only_token = _make_jwt(owner["email"], is_admin=False, teams=[])
        response = _mcp_post(
            public_only_token,
            server_id,
            method="tools/list",
            session_id=owner_session_id,
            request_id=4,
        )
        _assert_denied(response)

    def test_cross_user_live_stream_hijack_denied(self, isolation_environment: dict[str, Any]) -> None:
        """A second user must not attach to another user's live GET /mcp session."""
        server_id = isolation_environment["server_id"]
        owner = isolation_environment["users"]["owner"]
        outsider = isolation_environment["users"]["outsider"]
        _, _, owner_session_id = _initialize_session(owner["access_token"], server_id)

        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                _mcp_url(server_id),
                headers=_mcp_headers(outsider["access_token"], session_id=owner_session_id, accept="text/event-stream"),
            )
        _assert_denied(response)

    def test_cross_user_resume_hijack_denied(self, isolation_environment: dict[str, Any]) -> None:
        """A second user must not replay another user's resumable stream."""
        server_id = isolation_environment["server_id"]
        owner = isolation_environment["users"]["owner"]
        outsider = isolation_environment["users"]["outsider"]
        _, _, owner_session_id = _initialize_session(owner["access_token"], server_id)

        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            response = client.get(
                _mcp_url(server_id),
                params={"session_id": owner_session_id},
                headers={
                    **_mcp_headers(outsider["access_token"], accept="text/event-stream"),
                    "Last-Event-ID": "evt-1",
                },
            )
        _assert_denied(response)

    def test_cross_user_delete_denied_and_owner_session_survives(self, isolation_environment: dict[str, Any]) -> None:
        """A second user cannot delete another user's MCP session."""
        server_id = isolation_environment["server_id"]
        owner = isolation_environment["users"]["owner"]
        peer = isolation_environment["users"]["peer"]
        _, _, owner_session_id = _initialize_session(owner["access_token"], server_id)

        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            delete_response = client.request(
                "DELETE",
                _mcp_url(server_id),
                params={"session_id": owner_session_id},
                headers={
                    "Authorization": f"Bearer {peer['access_token']}",
                    "Accept": "application/json, text/event-stream",
                },
            )
        _assert_denied(delete_response)

        owner_follow_up = _mcp_post(
            owner["access_token"],
            server_id,
            method="tools/list",
            session_id=owner_session_id,
            request_id=5,
        )
        assert owner_follow_up.status_code == 200, owner_follow_up.text
        assert _extract_tool_names(owner_follow_up)

    def test_owner_session_tool_results_are_fresh(self, isolation_environment: dict[str, Any]) -> None:
        """Repeated owner calls within the same session should return live, changing tool output."""
        server_id = isolation_environment["server_id"]
        admin_token = _make_jwt("admin@example.com", is_admin=True, teams=None)
        _, _, owner_session_id = _initialize_session(admin_token, server_id)

        tool_names = _extract_tool_names(_mcp_post(admin_token, server_id, method="tools/list", session_id=owner_session_id, request_id=6))
        time_tool = _find_tool_name(tool_names, "get-system-time")

        first = _extract_primary_text_line(
            _mcp_post(
                admin_token,
                server_id,
                method="tools/call",
                params={"name": time_tool, "arguments": {"timezone": "UTC"}},
                session_id=owner_session_id,
                request_id=7,
            )
        )
        time.sleep(1.2)
        second = _extract_primary_text_line(
            _mcp_post(
                admin_token,
                server_id,
                method="tools/call",
                params={"name": time_tool, "arguments": {"timezone": "UTC"}},
                session_id=owner_session_id,
                request_id=8,
            )
        )

        first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
        second_dt = datetime.fromisoformat(second.replace("Z", "+00:00"))
        assert second_dt > first_dt, (first, second)

    def test_concurrent_owner_requests_and_peer_hijacks_do_not_leak(self, isolation_environment: dict[str, Any]) -> None:
        """Concurrent valid and hijack traffic must not leak one caller's session to another."""
        server_id = isolation_environment["server_id"]
        peer = isolation_environment["users"]["peer"]
        admin_token = _make_jwt("admin@example.com", is_admin=True, teams=None)
        _, _, owner_session_id = _initialize_session(admin_token, server_id)

        tool_names = _extract_tool_names(_mcp_post(admin_token, server_id, method="tools/list", session_id=owner_session_id, request_id=9))
        time_tool = _find_tool_name(tool_names, "get-system-time")

        def owner_call(index: int) -> tuple[str, int, str]:
            response = _mcp_post(
                admin_token,
                server_id,
                method="tools/call",
                params={"name": time_tool, "arguments": {"timezone": "UTC"}},
                session_id=owner_session_id,
                request_id=f"owner-{index}",
            )
            return ("owner", response.status_code, _extract_text_result(response))

        def peer_hijack(index: int) -> tuple[str, int, str]:
            response = _mcp_post(
                peer["access_token"],
                server_id,
                method="tools/call",
                params={"name": time_tool, "arguments": {"timezone": "UTC"}},
                session_id=owner_session_id,
                request_id=f"peer-{index}",
            )
            return ("peer", response.status_code, response.text)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(owner_call, i) for i in range(8)] + [executor.submit(peer_hijack, i) for i in range(8)]
            results = [future.result() for future in futures]

        owner_results = [result for result in results if result[0] == "owner"]
        peer_results = [result for result in results if result[0] == "peer"]

        assert len(owner_results) == 8
        assert len(peer_results) == 8
        assert all(status == 200 for _, status, _ in owner_results), owner_results
        assert all(text for _, _, text in owner_results), owner_results

        for _, status, text in peer_results:
            assert status in (200, 403, 404), peer_results
            if status == 200:
                payload = json.loads(text)
                if "result" in payload and not payload["result"].get("isError", False):
                    raise AssertionError(f"Peer hijack unexpectedly succeeded: {payload}")

    def test_revoked_token_session_is_denied_within_bounded_reuse_ttl(
        self,
        isolation_environment: dict[str, Any],
        admin_client: httpx.Client,
    ) -> None:
        """Revoking the owner token must deny the session no later than the documented reuse TTL."""
        server_id = isolation_environment["server_id"]
        team_id = isolation_environment["team_id"]
        user = _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-revoke-{uuid.uuid4().hex[:8]}@test.com",
            team_id=team_id,
            role_name="developer",
        )

        try:
            _, _, session_id = _initialize_session(user["access_token"], server_id)

            revoke_response = admin_client.delete(f"/tokens/admin/{user['token_id']}")
            assert revoke_response.status_code == 204, revoke_response.text

            denied = _wait_for_session_denial(
                user["access_token"],
                server_id,
                session_id=session_id,
                method="tools/list",
            )
            _assert_denied(denied)
        finally:
            _cleanup_user(admin_client, user)

    def test_removed_team_member_session_is_denied_within_bounded_reuse_ttl(
        self,
        isolation_environment: dict[str, Any],
        admin_client: httpx.Client,
    ) -> None:
        """Removing a member from the team must invalidate the existing MCP session within the bounded TTL."""
        server_id = isolation_environment["server_id"]
        team_id = isolation_environment["team_id"]
        user = _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-member-{uuid.uuid4().hex[:8]}@test.com",
            team_id=team_id,
            role_name="developer",
        )

        try:
            _, _, session_id = _initialize_session(user["access_token"], server_id)

            remove_response = admin_client.delete(f"/teams/{team_id}/members/{user['email']}")
            assert remove_response.status_code == 200, remove_response.text

            denied = _wait_for_session_denial(
                user["access_token"],
                server_id,
                session_id=session_id,
                method="tools/list",
            )
            _assert_denied(denied)
        finally:
            _cleanup_user(admin_client, user)

    def test_revoked_team_role_session_is_denied_within_bounded_reuse_ttl(
        self,
        isolation_environment: dict[str, Any],
        admin_client: httpx.Client,
    ) -> None:
        """Revoking the team RBAC role must deny tool execution on the existing session within the bounded TTL."""
        server_id = isolation_environment["server_id"]
        team_id = isolation_environment["team_id"]
        user = _create_user(
            admin_client,
            email=f"{ISOLATION_PREFIX}-role-{uuid.uuid4().hex[:8]}@test.com",
            team_id=team_id,
            role_name="developer",
        )

        try:
            _, _, session_id = _initialize_session(user["access_token"], server_id)

            tool_names = _extract_tool_names(_mcp_post(user["access_token"], server_id, method="tools/list", session_id=session_id, request_id=10))
            time_tool = _find_tool_name(tool_names, "get-system-time")

            _revoke_team_role(admin_client, user)

            denied = _wait_for_session_denial(
                user["access_token"],
                server_id,
                session_id=session_id,
                method="tools/call",
                params={"name": time_tool, "arguments": {"timezone": "UTC"}},
            )
            _assert_denied(denied)
        finally:
            _cleanup_user(admin_client, user)
