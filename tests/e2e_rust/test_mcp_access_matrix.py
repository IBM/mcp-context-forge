# -*- coding: utf-8 -*-
"""Location: ./tests/e2e_rust/test_mcp_access_matrix.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Compose-backed MCP role/access matrix tests for the Rust public transport path.

These tests validate the live server-scoped MCP endpoint with strong sentinels:

- exact tool, resource, and prompt discovery for a scoped virtual server
- structured `resources/read` payload verification
- structured `prompts/get` verification
- expected `tools/call` allow/deny behavior across scoped admin and non-admin users

The goal is correctness and access-matrix coverage, not throughput.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
import json
from typing import Any, Generator
import uuid

import httpx
import pytest

from mcpgateway.utils.create_jwt_token import _create_jwt_token

from tests.e2e.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, TEST_PASSWORD, skip_no_gateway, skip_no_rust_mcp_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway, skip_no_rust_mcp_gateway]

MCP_PROTOCOL_VERSION = "2025-11-25"
ACCESS_PREFIX = "mcp-access"
EXPECTED_TOOL_NAMES = {"fast-time-get-system-time", "fast-time-convert-time"}
EXPECTED_RESOURCE_URIS = {"time://formats", "timezone://info", "time://business-hours", "time://current/world"}
REQUIRED_PROMPT_NAMES = {"fast-time-schedule-meeting", "fast-time-convert-time-detailed", "fast-time-compare-timezones"}


def _make_jwt(email: str, *, is_admin: bool = False, teams: list[str] | None = None) -> str:
    """Create a JWT for compose-backed E2E tests."""
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
        secret=JWT_SECRET,
    )


def _api_headers(token: str) -> dict[str, str]:
    """Build standard JSON API headers."""
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _mcp_headers(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """Build headers for direct MCP JSON-RPC POSTs."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> Any:
    """Send a JSON API request and return the parsed payload."""
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


def _create_user_token(
    admin_client: httpx.Client,
    *,
    email: str,
    is_admin: bool,
    team_id: str | None,
    role_name: str | None,
    permissions: list[str],
) -> dict[str, Any]:
    """Create a user, optional team membership/role, and a scoped API token."""
    _request_json(
        admin_client,
        "POST",
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": f"Access Matrix {email.split('@', maxsplit=1)[0]}",
            "is_admin": is_admin,
            "is_active": True,
            "password_change_required": False,
        },
    )

    role_id = None
    if team_id:
        _request_json(
            admin_client,
            "POST",
            f"/teams/{team_id}/members",
            json={"email": email, "role": "member"},
        )
    if role_name and team_id:
        role_id = _resolve_role_id(admin_client, role_name)
        _request_json(
            admin_client,
            "POST",
            f"/rbac/users/{email}/roles",
            json={"role_id": role_id, "scope": "team", "scope_id": team_id},
        )

    user_jwt = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    with httpx.Client(base_url=BASE_URL, headers=_api_headers(user_jwt), timeout=20.0) as user_client:
        payload: dict[str, Any] = {
            "name": f"{ACCESS_PREFIX}-token-{uuid.uuid4().hex[:8]}",
            "expires_in_days": 1,
            "scope": {"permissions": permissions},
        }
        if team_id:
            payload["team_id"] = team_id
        token_response = _request_json(user_client, "POST", "/tokens", json=payload)

    token_obj = token_response.get("token", token_response)
    return {
        "email": email,
        "access_token": token_response["access_token"],
        "token_id": token_obj.get("id") or token_obj.get("token_id"),
        "team_id": team_id,
        "role_id": role_id,
    }


def _cleanup_user(admin_client: httpx.Client, user_info: dict[str, Any]) -> None:
    """Best-effort cleanup for a created test user and token."""
    token_id = user_info.get("token_id")
    if token_id:
        with suppress(Exception):
            admin_client.delete(f"/tokens/admin/{token_id}")
    with suppress(Exception):
        admin_client.delete(f"/auth/email/admin/users/{user_info['email']}")


def _mcp_post(
    client: httpx.Client,
    *,
    server_id: str,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    request_id: int = 1,
) -> httpx.Response:
    """Send a direct MCP JSON-RPC POST to the server-scoped endpoint."""
    return client.post(
        f"/servers/{server_id}/mcp/",
        headers=_mcp_headers(token, session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )


def _initialize_session(client: httpx.Client, *, server_id: str, token: str) -> str | None:
    """Initialize an MCP session and return the session id when the transport issues one."""
    response = _mcp_post(
        client,
        server_id=server_id,
        token=token,
        method="initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcp-access-matrix", "version": "1.0.0"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    assert response.headers.get("x-contextforge-mcp-runtime") == "rust"
    return response.headers.get("mcp-session-id")


def _extract_result(response: httpx.Response) -> dict[str, Any]:
    """Return the JSON-RPC result payload from a successful response."""
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


def _extract_error(response: httpx.Response, *, expected_status: int) -> dict[str, Any]:
    """Return the JSON-RPC error payload from a failed response."""
    assert response.status_code == expected_status, response.text
    payload = response.json()
    assert "error" in payload, payload
    return payload["error"]


def _assert_access_denied(response: httpx.Response) -> None:
    """Assert the MCP request was denied without leaking resource data."""
    assert response.status_code == 200, response.text
    payload = response.json()
    error = payload.get("error")
    assert error, payload
    assert error.get("code") == -32003, payload
    assert "access denied" in str(error.get("message", "")).lower(), payload


def _assert_tools_list(result: dict[str, Any]) -> None:
    """Assert the expected fast-time tools are exposed by the scoped server."""
    tools = result.get("tools", [])
    names = {tool["name"] for tool in tools}
    assert names == EXPECTED_TOOL_NAMES, tools

    tools_by_name = {tool["name"]: tool for tool in tools}
    get_time = tools_by_name["fast-time-get-system-time"]
    assert get_time["annotations"]["title"] == "Get System Time"
    assert set(get_time["inputSchema"]["properties"]) == {"timezone"}
    assert get_time["inputSchema"].get("required", []) == []

    convert_time = tools_by_name["fast-time-convert-time"]
    assert set(convert_time["inputSchema"]["required"]) == {"time", "source_timezone", "target_timezone"}


def _assert_resources_list(result: dict[str, Any]) -> None:
    """Assert the expected static resources are exposed by the scoped server."""
    resources = result.get("resources", [])
    uris = {resource["uri"] for resource in resources}
    assert uris == EXPECTED_RESOURCE_URIS, resources


def _assert_prompts_list(result: dict[str, Any]) -> None:
    """Assert the expected prompt names and argument schemas are exposed."""
    prompts = result.get("prompts", [])
    names = {prompt["name"] for prompt in prompts}
    assert REQUIRED_PROMPT_NAMES <= names, prompts

    prompts_by_name = {prompt["name"]: prompt for prompt in prompts}
    convert_prompt = prompts_by_name["fast-time-convert-time-detailed"]
    args = {arg["name"]: arg for arg in convert_prompt["arguments"]}
    assert set(args) == {"time", "from_timezone", "to_timezones", "include_context"}
    assert args["time"]["required"] is True
    assert args["from_timezone"]["required"] is True
    assert args["to_timezones"]["required"] is True
    assert args["include_context"]["required"] is False


def _assert_formats_resource(result: dict[str, Any]) -> None:
    """Assert the `time://formats` resource returns the expected structured payload."""
    contents = result.get("contents", [])
    assert len(contents) == 1, contents
    content = contents[0]
    assert content["uri"] == "time://formats"

    text = content["text"]
    json_start = min(index for index in (text.find("{"), text.find("[")) if index != -1)
    payload = json.loads(text[json_start:])
    assert set(payload["output_formats"]) >= {"iso8601", "rfc3339", "unix"}
    example_formats = {example["format"] for example in payload["examples"]}
    assert {"ISO 8601", "RFC 3339", "Unix Timestamp"} <= example_formats
    assert "2006-01-02T15:04:05Z" in payload["input_formats"]


def _assert_prompt_get(result: dict[str, Any]) -> None:
    """Assert prompt retrieval returns the expected structured prompt shape."""
    assert result["description"] == "Detailed time conversion"
    messages = result.get("messages", [])
    assert len(messages) == 1, messages
    message = messages[0]
    assert message["role"] == "user"
    assert message["content"]["type"] == "text"
    text = message["content"]["text"]
    assert isinstance(text, str)
    assert text.strip(), result
    assert "America/New_York" in text, text
    assert "Europe/Dublin" in text, text


def _assert_tool_call_success(result: dict[str, Any]) -> None:
    """Assert tool execution returned a fresh RFC3339 timestamp."""
    assert not result.get("isError", False), result
    content = result.get("content", [])
    assert len(content) == 1, content
    text = content[0]["text"].splitlines()[0]
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


@pytest.fixture(scope="module")
def admin_client() -> Generator[httpx.Client, None, None]:
    """Module-scoped admin API client."""
    token = _make_jwt("admin@example.com", is_admin=True, teams=None)
    with httpx.Client(base_url=BASE_URL, headers=_api_headers(token), timeout=20.0) as client:
        yield client


@pytest.fixture(scope="module")
def access_matrix_env(admin_client: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Provision a team-scoped virtual server plus scoped admin and non-admin users."""
    team = _request_json(
        admin_client,
        "POST",
        "/teams/",
        json={
            "name": f"{ACCESS_PREFIX}-team-{uuid.uuid4().hex[:8]}",
            "description": "Rust MCP access matrix team",
            "visibility": "private",
        },
    )
    team_id = team["id"]

    tools = _request_json(admin_client, "GET", "/tools")
    resources = _request_json(admin_client, "GET", "/resources")
    prompts = _request_json(admin_client, "GET", "/prompts")
    gateways = _request_json(admin_client, "GET", "/gateways")
    gateway = next(g for g in gateways if g["name"] == "fast_time")
    gateway_id = gateway["id"]
    tool_ids = [tool["id"] for tool in tools if (tool.get("gatewayId") or tool.get("gateway_id")) == gateway_id]
    resource_ids = [resource["id"] for resource in resources if resource.get("federationSource") == "fast_time"]
    prompt_ids = [prompt["id"] for prompt in prompts if prompt.get("gatewaySlug") == "fast-time"]

    server = _request_json(
        admin_client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": f"{ACCESS_PREFIX}-server-{uuid.uuid4().hex[:8]}",
                "description": "Rust MCP access matrix virtual server",
                "associated_tools": tool_ids,
                "associated_resources": resource_ids,
                "associated_prompts": prompt_ids,
            },
            "team_id": team_id,
            "visibility": "team",
        },
    )
    server_id = server["id"]

    users = {
        "admin_scoped": _create_user_token(
            admin_client,
            email=f"{ACCESS_PREFIX}-admin-{uuid.uuid4().hex[:8]}@test.com",
            is_admin=True,
            team_id=team_id,
            role_name=None,
            permissions=["tools.read", "tools.execute", "resources.read", "prompts.read"],
        ),
        "developer_read_only": _create_user_token(
            admin_client,
            email=f"{ACCESS_PREFIX}-ro-{uuid.uuid4().hex[:8]}@test.com",
            is_admin=False,
            team_id=team_id,
            role_name="developer",
            permissions=["tools.read", "resources.read", "prompts.read"],
        ),
        "developer_read_execute": _create_user_token(
            admin_client,
            email=f"{ACCESS_PREFIX}-rw-{uuid.uuid4().hex[:8]}@test.com",
            is_admin=False,
            team_id=team_id,
            role_name="developer",
            permissions=["tools.read", "tools.execute", "resources.read", "prompts.read"],
        ),
        "outsider_read_only": _create_user_token(
            admin_client,
            email=f"{ACCESS_PREFIX}-outsider-{uuid.uuid4().hex[:8]}@test.com",
            is_admin=False,
            team_id=None,
            role_name=None,
            permissions=["tools.read", "resources.read", "prompts.read"],
        ),
    }

    yield {"server_id": server_id, "users": users}

    for user in users.values():
        _cleanup_user(admin_client, user)
    with suppress(Exception):
        admin_client.delete(f"/servers/{server_id}")
    with suppress(Exception):
        admin_client.delete(f"/teams/{team_id}")


class TestMcpAccessMatrix:
    """Role and token-scope access matrix for the Rust public transport path."""

    def test_admin_scoped_token_has_full_server_scoped_access(self, access_matrix_env: dict[str, Any]) -> None:
        """Scoped admin token should discover and execute with strong output sentinels."""
        server_id = access_matrix_env["server_id"]
        token = access_matrix_env["users"]["admin_scoped"]["access_token"]

        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            session_id = _initialize_session(client, server_id=server_id, token=token)

            _assert_tools_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="tools/list", request_id=2)))
            _assert_resources_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="resources/list", request_id=3)))
            _assert_prompts_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="prompts/list", request_id=4)))
            _assert_formats_resource(
                _extract_result(
                    _mcp_post(
                        client,
                        server_id=server_id,
                        token=token,
                        session_id=session_id,
                        method="resources/read",
                        params={"uri": "time://formats"},
                        request_id=5,
                    )
                )
            )
            _assert_prompt_get(
                _extract_result(
                    _mcp_post(
                        client,
                        server_id=server_id,
                        token=token,
                        session_id=session_id,
                        method="prompts/get",
                        params={
                            "name": "fast-time-convert-time-detailed",
                            "arguments": {
                                "time": "2025-01-15T12:00:00Z",
                                "from_timezone": "UTC",
                                "to_timezones": "America/New_York,Europe/Dublin",
                                "include_context": "true",
                            },
                        },
                        request_id=6,
                    )
                )
            )
            _assert_tool_call_success(
                _extract_result(
                    _mcp_post(
                        client,
                        server_id=server_id,
                        token=token,
                        session_id=session_id,
                        method="tools/call",
                        params={"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}},
                        request_id=7,
                    )
                )
            )

    def test_admin_prompt_invalid_arguments_return_structured_error(self, access_matrix_env: dict[str, Any]) -> None:
        """Prompt bridge errors should surface as MCP errors, not Rust decode failures."""
        server_id = access_matrix_env["server_id"]
        token = access_matrix_env["users"]["admin_scoped"]["access_token"]

        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            session_id = _initialize_session(client, server_id=server_id, token=token)
            error = _extract_error(
                _mcp_post(
                    client,
                    server_id=server_id,
                    token=token,
                    session_id=session_id,
                    method="prompts/get",
                    params={
                        "name": "fast-time-convert-time-detailed",
                        "arguments": {
                            "time": "2025-01-15T12:00:00Z",
                            "source_timezone": "UTC",
                            "target_timezones": ["America/New_York", "Europe/Dublin"],
                        },
                    },
                    request_id=8,
                ),
                expected_status=200,
            )

        assert error["code"] == -32602
        assert "decode failed" not in error["message"].lower()
        assert error["message"] == "Prompt argument 'target_timezones' must be a string value"

    def test_non_admin_read_only_token_has_read_access_with_strong_sentinels(self, access_matrix_env: dict[str, Any]) -> None:
        """Non-admin read-only token should initialize and verify tools/resources/prompts output shapes."""
        server_id = access_matrix_env["server_id"]
        token = access_matrix_env["users"]["developer_read_only"]["access_token"]

        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            session_id = _initialize_session(client, server_id=server_id, token=token)

            _assert_tools_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="tools/list", request_id=2)))
            _assert_resources_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="resources/list", request_id=3)))
            _assert_prompts_list(_extract_result(_mcp_post(client, server_id=server_id, token=token, session_id=session_id, method="prompts/list", request_id=4)))
            _assert_formats_resource(
                _extract_result(
                    _mcp_post(
                        client,
                        server_id=server_id,
                        token=token,
                        session_id=session_id,
                        method="resources/read",
                        params={"uri": "time://formats"},
                        request_id=5,
                    )
                )
            )
            _assert_prompt_get(
                _extract_result(
                    _mcp_post(
                        client,
                        server_id=server_id,
                        token=token,
                        session_id=session_id,
                        method="prompts/get",
                        params={
                            "name": "fast-time-convert-time-detailed",
                            "arguments": {
                                "time": "2025-01-15T12:00:00Z",
                                "from_timezone": "UTC",
                                "to_timezones": "America/New_York,Europe/Dublin",
                                "include_context": "true",
                            },
                        },
                        request_id=6,
                    )
                )
            )
            _assert_access_denied(
                _mcp_post(
                    client,
                    server_id=server_id,
                    token=token,
                    session_id=session_id,
                    method="tools/call",
                    params={"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}},
                    request_id=7,
                )
            )

    def test_non_admin_read_execute_token_still_denied_tools_call(self, access_matrix_env: dict[str, Any]) -> None:
        """Document the current MCP behavior for non-admin scoped execute tokens on the Rust path."""
        server_id = access_matrix_env["server_id"]
        token = access_matrix_env["users"]["developer_read_execute"]["access_token"]

        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            session_id = _initialize_session(client, server_id=server_id, token=token)
            _assert_access_denied(
                _mcp_post(
                    client,
                    server_id=server_id,
                    token=token,
                    session_id=session_id,
                    method="tools/call",
                    params={"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}},
                    request_id=2,
                )
            )

    def test_outsider_scoped_token_cannot_initialize_team_server(self, access_matrix_env: dict[str, Any]) -> None:
        """Outsider token should be denied before any team-scoped MCP interaction occurs."""
        server_id = access_matrix_env["server_id"]
        token = access_matrix_env["users"]["outsider_read_only"]["access_token"]

        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            response = _mcp_post(
                client,
                server_id=server_id,
                token=token,
                method="initialize",
                params={
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-access-matrix", "version": "1.0.0"},
                },
            )

        assert response.status_code in (401, 403), response.text
