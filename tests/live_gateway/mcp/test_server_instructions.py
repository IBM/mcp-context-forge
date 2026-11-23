# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_server_instructions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for the ``instructions`` text that a virtual server sends to clients.

Each scenario runs in both protocol eras:

- Legacy (``2025-11-25`` and earlier): the ``initialize`` result carries ``instructions``.
- Modern (``2026-07-28``): the ``server/discover`` result carries ``instructions``.

Resolution order, as served on the wire:

1. An operator override on the virtual server, when it is not NULL. An empty override sends no field.
2. The text of the upstream server, when every tool of the virtual server comes from one upstream server.
3. The default text.

The ``fast_time`` upstream server is the compose ``fast_time_server`` service, which
``register_fast_time`` registers as the gateway named ``fast_time``. Scenarios that need
it skip when that gateway is absent.

The ``fast-time-server`` image pinned in ``docker-compose.yml`` sends the text
``FAST_TIME_DEFAULT_INSTRUCTIONS`` (contextforge-examples#57). A single-upstream virtual
server must send the same text. To test another image, set ``FAST_TIME_INSTRUCTIONS`` to
the text that image sends. An empty value means that the image sends no ``instructions`` field.

Environment variables consumed:
    MCP_CLI_BASE_URL        Gateway URL (default: http://127.0.0.1:8080)
    JWT_SECRET_KEY          JWT signing secret of the target gateway.
    PLATFORM_ADMIN_EMAIL    Bootstrap admin email.
    FAST_TIME_INSTRUCTIONS  Text that the ``fast_time`` upstream server sends (default: the text of the pinned image).

Usage:
    pytest tests/live_gateway/mcp/test_server_instructions.py -v
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import json
import os
from typing import Any, Callable, Generator
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.common.models import DEFAULT_SERVER_INSTRUCTIONS
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, build_initialize, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

MODERN_PROTOCOL_VERSION = "2026-07-28"
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}
FAST_TIME_GATEWAY_NAME = "fast_time"
FAST_TIME_DEFAULT_INSTRUCTIONS = "Fast Time Server. Use get_system_time for the current time. Use convert_time to convert a time between timezones."
FAST_TIME_INSTRUCTIONS = os.getenv("FAST_TIME_INSTRUCTIONS", FAST_TIME_DEFAULT_INSTRUCTIONS) or None
OVERRIDE_TEXT = "Use only the tools of this server. Ask the operator before you call a tool twice."
ERAS = ["legacy", "modern"]


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    """Build the authentication headers for REST and MCP requests.

    Returns:
        Header dict for httpx.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _jsonrpc_payload(response: httpx.Response) -> dict[str, Any]:
    """Parse a JSON or SSE Streamable HTTP response into its JSON-RPC envelope.

    Args:
        response: A Streamable HTTP response.

    Returns:
        The decoded JSON-RPC message.

    Raises:
        AssertionError: If the body carries no JSON-RPC envelope.
    """
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no JSON-RPC envelope in response: {response.text[:300]}")


def _handshake_result(path: str, era: str) -> dict[str, Any]:
    """Run the handshake of one protocol era and return its result object.

    Args:
        path: Endpoint path, for example ``/mcp/`` or ``/servers/<id>/mcp/``.
        era: ``legacy`` sends ``initialize``. ``modern`` sends ``server/discover``.

    Returns:
        The ``result`` member of the JSON-RPC response.
    """
    headers = _headers()
    if era == "legacy":
        body = build_initialize()
    else:
        headers.update({"MCP-Protocol-Version": MODERN_PROTOCOL_VERSION, "Mcp-Method": "server/discover"})
        body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN_META}}
    response = httpx.post(f"{BASE_URL}{path}", headers=headers, json=body, timeout=15.0)
    if era == "modern" and response.status_code == 400 and "Unsupported protocol version" in response.text:
        pytest.skip("gateway runs with MCP_INBOUND_PROTOCOL_MODE=legacy")
    assert response.status_code == 200, f"{era} handshake failed: {response.status_code} {response.text[:300]}"
    payload = _jsonrpc_payload(response)
    assert "result" in payload, payload
    return payload["result"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def api() -> Generator[httpx.Client, None, None]:
    """Admin-authenticated REST client.

    Yields:
        An httpx client bound to the gateway.
    """
    with httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=30.0) as client:
        yield client


@pytest.fixture(scope="module")
def fast_time_tool_ids(api: httpx.Client) -> list[str]:
    """Return the identifiers of the tools that the ``fast_time`` gateway federates.

    Args:
        api: Admin REST client.

    Returns:
        Tool identifiers. The fixture skips the test when the gateway is not registered.
    """
    response = api.get("/gateways")
    response.raise_for_status()
    gateway_ids = [gw["id"] for gw in response.json() if gw.get("name") == FAST_TIME_GATEWAY_NAME]
    if not gateway_ids:
        pytest.skip(f"gateway {FAST_TIME_GATEWAY_NAME!r} is not registered")
    response = api.get("/tools", params={"gateway_id": gateway_ids[0], "limit": 0})
    response.raise_for_status()
    tool_ids = [tool["id"] for tool in response.json()]
    if not tool_ids:
        pytest.skip(f"gateway {FAST_TIME_GATEWAY_NAME!r} federates no tools")
    return tool_ids


@pytest.fixture(scope="module")
def local_tool_id(api: httpx.Client) -> Generator[str, None, None]:
    """Create a tool that no upstream server owns.

    Args:
        api: Admin REST client.

    Yields:
        The tool identifier. The fixture deletes the tool at teardown.
    """
    name = f"instructions-local-{uuid.uuid4().hex[:8]}"
    tool = {"name": name, "url": "http://127.0.0.1:9/never-called", "integration_type": "REST", "request_type": "GET", "input_schema": {"type": "object"}}
    response = api.post("/tools", json={"tool": tool, "team_id": None, "visibility": "private"})
    assert response.status_code in (200, 201), response.text
    tool_id = response.json()["id"]
    try:
        yield tool_id
    finally:
        with suppress(Exception):
            api.delete(f"/tools/{tool_id}")


@pytest.fixture
def make_server(api: httpx.Client) -> Generator[Callable[..., str], None, None]:
    """Return a factory that creates virtual servers and deletes them at teardown.

    Args:
        api: Admin REST client.

    Yields:
        A function that takes tool identifiers and an optional override, and returns the server identifier.
    """
    created: list[str] = []

    def _make(tool_ids: list[str], **extra: Any) -> str:
        server = {"name": f"instructions-{uuid.uuid4().hex[:8]}", "associated_tools": tool_ids, **extra}
        response = api.post("/servers", json={"server": server, "team_id": None, "visibility": "private"})
        assert response.status_code in (200, 201), response.text
        server_id = response.json()["id"]
        created.append(server_id)
        return server_id

    try:
        yield _make
    finally:
        for server_id in created:
            with suppress(Exception):
                api.delete(f"/servers/{server_id}")


def _assert_instructions(result: dict[str, Any], expected: str | None) -> None:
    """Check the ``instructions`` member of a handshake result.

    Args:
        result: The handshake result object.
        expected: The expected text, or None when the field must be absent.
    """
    if expected is None:
        assert "instructions" not in result, result
    else:
        assert result.get("instructions") == expected, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("era", ERAS)
def test_global_endpoint_sends_default_text(era: str) -> None:
    """The global /mcp endpoint has no virtual server and sends the default text."""
    _assert_instructions(_handshake_result("/mcp/", era), DEFAULT_SERVER_INSTRUCTIONS)


@pytest.mark.parametrize("era", ERAS)
def test_server_with_only_upstream_tools_sends_upstream_text(era: str, fast_time_tool_ids: list[str], make_server: Callable[..., str]) -> None:
    """A virtual server that holds only fast_time tools sends the fast_time text, or no field when fast_time has none."""
    server_id = make_server(fast_time_tool_ids)
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), FAST_TIME_INSTRUCTIONS)


@pytest.mark.parametrize("era", ERAS)
def test_server_with_upstream_tool_subset_sends_upstream_text(era: str, fast_time_tool_ids: list[str], make_server: Callable[..., str]) -> None:
    """A virtual server with a strict subset of fast_time tools sends the same text as the whole set."""
    server_id = make_server(fast_time_tool_ids[:1])
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), FAST_TIME_INSTRUCTIONS)


@pytest.mark.parametrize("era", ERAS)
def test_server_mixing_upstream_and_local_tools_sends_default_text(era: str, fast_time_tool_ids: list[str], local_tool_id: str, make_server: Callable[..., str]) -> None:
    """A virtual server that mixes a fast_time tool and a local tool sends the default text."""
    server_id = make_server([fast_time_tool_ids[0], local_tool_id])
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), DEFAULT_SERVER_INSTRUCTIONS)


@pytest.mark.parametrize("era", ERAS)
def test_server_with_local_tool_only_sends_default_text(era: str, local_tool_id: str, make_server: Callable[..., str]) -> None:
    """A virtual server with a local tool only has no single upstream server and sends the default text."""
    server_id = make_server([local_tool_id])
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), DEFAULT_SERVER_INSTRUCTIONS)


@pytest.mark.parametrize("era", ERAS)
def test_override_replaces_default_text(era: str, local_tool_id: str, make_server: Callable[..., str]) -> None:
    """An operator override replaces the default text."""
    server_id = make_server([local_tool_id], instructions=OVERRIDE_TEXT)
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), OVERRIDE_TEXT)


@pytest.mark.parametrize("era", ERAS)
def test_override_replaces_upstream_text(era: str, fast_time_tool_ids: list[str], make_server: Callable[..., str]) -> None:
    """An operator override wins over the text of a single upstream server."""
    server_id = make_server(fast_time_tool_ids, instructions=OVERRIDE_TEXT)
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), OVERRIDE_TEXT)


@pytest.mark.parametrize("era", ERAS)
def test_empty_override_sends_no_field(era: str, local_tool_id: str, make_server: Callable[..., str]) -> None:
    """An empty override sends no instructions field."""
    server_id = make_server([local_tool_id], instructions="")
    _assert_instructions(_handshake_result(f"/servers/{server_id}/mcp/", era), None)


@pytest.mark.parametrize("era", ERAS)
def test_update_changes_text_on_next_handshake(era: str, api: httpx.Client, local_tool_id: str, make_server: Callable[..., str]) -> None:
    """Setting and clearing the override through PUT changes the text of the next handshake."""
    server_id = make_server([local_tool_id])
    path = f"/servers/{server_id}/mcp/"
    _assert_instructions(_handshake_result(path, era), DEFAULT_SERVER_INSTRUCTIONS)

    response = api.put(f"/servers/{server_id}", json={"instructions": OVERRIDE_TEXT})
    assert response.status_code == 200, response.text
    assert response.json()["instructions"] == OVERRIDE_TEXT
    _assert_instructions(_handshake_result(path, era), OVERRIDE_TEXT)

    response = api.put(f"/servers/{server_id}", json={"instructions": None})
    assert response.status_code == 200, response.text
    assert response.json()["instructions"] is None
    _assert_instructions(_handshake_result(path, era), DEFAULT_SERVER_INSTRUCTIONS)
