# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_mcp_plugin_parity.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Compose-backed MCP plugin parity tests.

These tests run against the current live stack and assert that a test-specific
plugin configuration still takes effect on the public MCP path. Run the same
file against both Python mode and Rust full mode to prove parity.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any, Generator
import os
import uuid

import httpx
import pytest

from mcpgateway.utils.create_jwt_token import _create_jwt_token

from tests.e2e.mcp_test_helpers import BASE_URL, skip_no_gateway

MCP_PROTOCOL_VERSION = "2025-11-25"
PLUGIN_PARITY_PREFIX = "mcp-plugin-parity"
RESOURCE_LICENSE_PREFIX = "# SPDX-License-Identifier: Apache-2.0"
TOOL_OUTPUT_SENTINEL = "[TOOL-POST-INVOKE-SENTINEL]"
PROMPT_OUTPUT_SENTINEL = "[PROMPT-POST-FETCH-SENTINEL]"
EXPECTED_RUNTIME = os.getenv("MCP_PLUGIN_PARITY_EXPECTED_RUNTIME")
pytestmark = [
    pytest.mark.e2e,
    skip_no_gateway,
    pytest.mark.skipif(
        not EXPECTED_RUNTIME,
        reason=(
            "requires the dedicated plugin parity stack; run via "
            "MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=<python|rust> make test-mcp-plugin-parity"
        ),
    ),
]

# This suite targets the standard compose-backed test stack, which uses the
# fixed local JWT secret below. Do not source this from mutable process env,
# because broad-suite tests may patch JWT_SECRET_KEY before this module loads.
COMPOSE_TEST_JWT_SECRET = "my-test-key"


def _make_admin_jwt() -> str:
    """Create a platform-admin JWT for compose-backed parity tests.

    Returns:
        A signed admin JWT.
    """
    return _create_jwt_token(
        {"sub": "admin@example.com"},
        user_data={"email": "admin@example.com", "is_admin": True, "auth_provider": "local"},
        teams=None,
        secret=COMPOSE_TEST_JWT_SECRET,
    )


def _api_headers(token: str) -> dict[str, str]:
    """Build JSON API headers.

    Args:
        token: Bearer token to send.

    Returns:
        Standard API headers.
    """
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _mcp_headers(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """Build MCP JSON-RPC headers.

    Args:
        token: Bearer token to send.
        session_id: Optional MCP session identifier.

    Returns:
        Standard MCP headers.
    """
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
    """Send a JSON API request and return the parsed body.

    Args:
        client: Configured HTTP client.
        method: HTTP method.
        path: Relative API path.
        expected: Allowed status codes.
        **kwargs: Request options forwarded to `httpx`.

    Returns:
        Parsed JSON response body, or `None` for an empty body.
    """
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, (
        f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
    )
    return response.json() if response.content else None


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
    """Send a direct server-scoped MCP request.

    Args:
        client: Configured HTTP client.
        server_id: Target virtual server id.
        token: Bearer token to send.
        method: JSON-RPC method.
        params: Optional method parameters.
        session_id: Optional MCP session id.
        request_id: JSON-RPC request id.

    Returns:
        Raw HTTP response.
    """
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


def _assert_runtime_header(response: httpx.Response) -> None:
    """Assert the runtime header when an expected runtime is configured.

    Args:
        response: MCP HTTP response.
    """
    if EXPECTED_RUNTIME:
        assert response.headers.get("x-contextforge-mcp-runtime") == EXPECTED_RUNTIME, response.headers


def _initialize_session(client: httpx.Client, *, server_id: str, token: str) -> str | None:
    """Initialize an MCP session and return its session id when present.

    Args:
        client: Configured HTTP client.
        server_id: Target virtual server id.
        token: Bearer token to send.

    Returns:
        The allocated MCP session id when the runtime exposes one, otherwise
        `None`.
    """
    response = _mcp_post(
        client,
        server_id=server_id,
        token=token,
        method="initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcp-plugin-parity", "version": "1.0.0"},
        },
    )
    assert response.status_code == 200, response.text
    _assert_runtime_header(response)
    payload = response.json()
    assert "result" in payload, payload
    return response.headers.get("mcp-session-id")


def _extract_result(response: httpx.Response) -> dict[str, Any]:
    """Extract the JSON-RPC result payload from a successful response.

    Args:
        response: MCP HTTP response.

    Returns:
        JSON-RPC `result` payload.
    """
    assert response.status_code == 200, response.text
    _assert_runtime_header(response)
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


@pytest.fixture(scope="module")
def admin_client() -> Generator[httpx.Client, None, None]:
    """Module-scoped admin client.

    Yields:
        Authenticated admin HTTP client.
    """
    token = _make_admin_jwt()
    # This suite only talks to the local plain-HTTP test stack. Passing
    # verify=False avoids unrelated TLS env leakage from other tests.
    with httpx.Client(base_url=BASE_URL, headers=_api_headers(token), timeout=20.0, verify=False) as client:
        yield client


@pytest.fixture(scope="module")
def plugin_parity_server(admin_client: httpx.Client) -> Generator[dict[str, str], None, None]:
    """Provision a server-scoped MCP endpoint for plugin parity checks.

    Args:
        admin_client: Module-scoped admin client.

    Yields:
        Dict containing the server id and admin token.
    """
    team = _request_json(
        admin_client,
        "POST",
        "/teams/",
        json={
            "name": f"{PLUGIN_PARITY_PREFIX}-team-{uuid.uuid4().hex[:8]}",
            "description": "Plugin parity MCP team",
            "visibility": "private",
        },
    )
    team_id = team["id"]

    tools = _request_json(admin_client, "GET", "/tools")
    resources = _request_json(admin_client, "GET", "/resources")
    prompts = _request_json(admin_client, "GET", "/prompts")
    time_tool = next(tool for tool in tools if tool["name"] == "fast-time-get-system-time")
    formats_resource = next(resource for resource in resources if resource["uri"] == "time://formats")
    detailed_prompt = next(prompt for prompt in prompts if prompt["name"] == "fast-time-convert-time-detailed")

    server = _request_json(
        admin_client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": f"{PLUGIN_PARITY_PREFIX}-server-{uuid.uuid4().hex[:8]}",
                "description": "Plugin parity virtual server",
                "associated_tools": [time_tool["id"]],
                "associated_resources": [formats_resource["id"]],
                "associated_prompts": [detailed_prompt["id"]],
            },
            "team_id": team_id,
            "visibility": "team",
        },
    )
    server_id = server["id"]

    yield {"server_id": server_id, "token": _make_admin_jwt()}

    with suppress(Exception):
        admin_client.delete(f"/servers/{server_id}")
    with suppress(Exception):
        admin_client.delete(f"/teams/{team_id}")


class TestMcpPluginParity:
    """Live plugin parity assertions for the public MCP path."""

    def test_resources_read_applies_license_header(self, plugin_parity_server: dict[str, str]) -> None:
        """`resources/read` should still run `resource_post_fetch` hooks.

        Args:
            plugin_parity_server: Provisioned server fixture.
        """
        with httpx.Client(base_url=BASE_URL, timeout=20.0, verify=False) as client:
            session_id = _initialize_session(client, server_id=plugin_parity_server["server_id"], token=plugin_parity_server["token"])
            result = _extract_result(
                _mcp_post(
                    client,
                    server_id=plugin_parity_server["server_id"],
                    token=plugin_parity_server["token"],
                    session_id=session_id,
                    method="resources/read",
                    params={"uri": "time://formats"},
                    request_id=2,
                )
            )

        contents = result.get("contents", [])
        assert len(contents) == 1, contents
        content = contents[0]
        assert content["uri"] == "time://formats"
        assert "mime_type" not in content, content
        assert isinstance(content.get("text"), str), content
        assert content["text"].startswith(RESOURCE_LICENSE_PREFIX), content["text"]
        assert '"output_formats"' in content["text"], content["text"]

    def test_tools_call_appends_sentinel(self, plugin_parity_server: dict[str, str]) -> None:
        """`tools/call` should still run the test-only `tool_post_invoke` hook.

        Args:
            plugin_parity_server: Provisioned server fixture.
        """
        with httpx.Client(base_url=BASE_URL, timeout=20.0, verify=False) as client:
            session_id = _initialize_session(client, server_id=plugin_parity_server["server_id"], token=plugin_parity_server["token"])
            result = _extract_result(
                _mcp_post(
                    client,
                    server_id=plugin_parity_server["server_id"],
                    token=plugin_parity_server["token"],
                    session_id=session_id,
                    method="tools/call",
                    params={"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}},
                    request_id=3,
                )
            )

        assert not result.get("isError", False), result
        content = result.get("content", [])
        assert len(content) == 1, content
        text = content[0]["text"]
        lines = text.splitlines()
        assert lines[-1] == TOOL_OUTPUT_SENTINEL, text
        parsed = datetime.fromisoformat(lines[0].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_prompts_get_appends_sentinel(self, plugin_parity_server: dict[str, str]) -> None:
        """`prompts/get` should still run `prompt_post_fetch` hooks.

        Args:
            plugin_parity_server: Provisioned server fixture.
        """
        with httpx.Client(base_url=BASE_URL, timeout=20.0, verify=False) as client:
            session_id = _initialize_session(client, server_id=plugin_parity_server["server_id"], token=plugin_parity_server["token"])
            result = _extract_result(
                _mcp_post(
                    client,
                    server_id=plugin_parity_server["server_id"],
                    token=plugin_parity_server["token"],
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
                    request_id=4,
                )
            )

        assert result["description"] == "Detailed time conversion"
        messages = result.get("messages", [])
        assert len(messages) == 1, messages
        text = messages[0]["content"]["text"]
        assert isinstance(text, str) and text, result
        lines = text.splitlines()
        assert lines[-1] == PROMPT_OUTPUT_SENTINEL, text
        assert "America/New_York" in text, text
        assert "Europe/Dublin" in text, text
