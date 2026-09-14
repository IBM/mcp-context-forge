# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/reverse_proxy/helpers/live_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Typed I/O helpers for reverse-proxy live tests.
"""

from __future__ import annotations

import json
import os
import time
from typing import Final
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mcpgateway.services.reverse_proxy_protocol import JsonObject

BASE_URL: Final = os.environ.get("REVERSE_PROXY_E2E_BASE_URL", "http://127.0.0.1:18080")
TOKEN: Final = os.environ.get("REVERSE_PROXY_E2E_TOKEN", "")
RESTRICTED_TOKEN: Final = os.environ.get("REVERSE_PROXY_E2E_RESTRICTED_TOKEN", "")
COMPOSE_PROJECT: Final = os.environ.get("REVERSE_PROXY_E2E_COMPOSE_PROJECT", "mcpgw-rp-e2e")
FAST_SERVER_NAME: Final = os.environ.get("REVERSE_PROXY_E2E_FAST_SERVER_NAME", "t8-fast-test")
COMPLIANCE_SERVER_NAME: Final = os.environ.get("REVERSE_PROXY_E2E_COMPLIANCE_SERVER_NAME", "t8-compliance")
AUTH_SERVER_NAME: Final = os.environ.get("REVERSE_PROXY_E2E_AUTH_SERVER_NAME", "t8-auth-probe")
AUTHORITY_SERVER_NAME: Final = os.environ.get("REVERSE_PROXY_E2E_AUTHORITY_SERVER_NAME", "t8-authority-probe")
FAST_TOOL_NAME: Final = f"{FAST_SERVER_NAME}-echo"
COMPLIANCE_PROMPT_NAME: Final = f"{COMPLIANCE_SERVER_NAME}-greet"
AUTH_TOOL_NAME: Final = f"{AUTH_SERVER_NAME}-auth-probe"
FAST_CLIENT_PID: Final = int(os.environ.get("REVERSE_PROXY_E2E_FAST_CLIENT_PID", "0"))
AUTH_CLIENT_PID: Final = int(os.environ.get("REVERSE_PROXY_E2E_AUTH_CLIENT_PID", "0"))


def json_request(path: str, *, payload: bytes | None = None, method: str | None = None) -> JsonObject | list[JsonObject]:
    """Send one authenticated JSON request to the live gateway."""
    request = Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"),
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed local live-test target
        return json.load(response)


def post(path: str, payload: JsonObject) -> JsonObject:
    """POST one JSON object and require an object response."""
    response = json_request(path, payload=json.dumps(payload).encode())
    assert isinstance(response, dict)
    return response


def put(path: str, payload: JsonObject) -> JsonObject:
    """PUT one JSON object and require an object response."""
    response = json_request(path, payload=json.dumps(payload).encode(), method="PUT")
    assert isinstance(response, dict)
    return response


def rpc(method: str, params: JsonObject, *, request_id: str = "e2e") -> JsonObject:
    """Call the live JSON-RPC endpoint and require an object response."""
    payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
    response = json_request("/rpc", payload=payload)
    assert isinstance(response, dict)
    return response


def rpc_text(response: JsonObject) -> str | None:
    """Extract the first text content value from a JSON-RPC result."""
    if not isinstance(result := response.get("result"), dict):
        return None
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    if not isinstance(first, dict):
        return None
    text = first.get("text")
    return text if isinstance(text, str) else None


def wait_for_tool() -> None:
    """Wait until the maintained client publishes a callable echo tool."""
    deadline = time.monotonic() + 60
    last_response: JsonObject = {}
    while time.monotonic() < deadline:
        try:
            tools = json_request("/tools?limit=1000")
            assert isinstance(tools, list)
        except (HTTPError, TimeoutError, ConnectionError):
            time.sleep(1)
            continue
        if any(tool.get("name") == FAST_TOOL_NAME for tool in tools):
            try:
                response = rpc("tools/call", {"name": FAST_TOOL_NAME, "arguments": {"message": "ready"}}, request_id="ready")
            except (HTTPError, TimeoutError, ConnectionError):
                time.sleep(1)
                continue
            last_response = response
            if rpc_text(response) == "ready":
                return
        time.sleep(1)
    pytest.fail(f"maintained client did not publish a callable echo tool: {last_response}")


def wait_for_gateway(name: str, reachable: bool, *, timeout: float = 30) -> JsonObject:
    """Wait for a named catalog gateway to reach the expected state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        gateways = json_request("/gateways?limit=1000")
        assert isinstance(gateways, list)
        matching = next((gateway for gateway in gateways if gateway.get("name") == name), None)
        if matching is not None and matching.get("reachable") is reachable:
            return matching
        time.sleep(1)
    return pytest.fail(f"gateway {name!r} did not reach reachable={reachable}")
