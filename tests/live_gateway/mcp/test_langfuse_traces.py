# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_langfuse_traces.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end smoke checks for Langfuse trace export.

These tests are environment-gated and intended for manual or CI runs against a
live gateway + Langfuse stack. They are skipped unless both services are
reachable and the required credentials are present.
"""

# Standard
import base64
from datetime import datetime
import json
import os
import subprocess
import sys
import time
from typing import Any, Callable

# Third-Party
import httpx
import pytest

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL
from ..helpers.mcp_test_helpers import JWT_SECRET
from ..helpers.mcp_test_helpers import TOKEN_EXPIRY

BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://localhost:8080")
LANGFUSE_URL = os.getenv("LANGFUSE_URL", "http://localhost:3100").rstrip("/")


def _resolve_langfuse_auth() -> str:
    """Resolve Langfuse basic auth from explicit auth or project keys.

    Returns:
        Base64-encoded basic auth token, or an empty string when auth is not configured.
    """
    explicit_auth = os.getenv("LANGFUSE_OTEL_AUTH") or os.getenv("LANGFUSE_BASIC_AUTH")
    if explicit_auth:
        return explicit_auth

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        return ""

    return base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")


LANGFUSE_AUTH = _resolve_langfuse_auth()


def _gateway_reachable() -> bool:
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def _langfuse_reachable() -> bool:
    try:
        response = httpx.get(f"{LANGFUSE_URL}/api/public/health", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"ContextForge not reachable at {BASE_URL}")
skip_no_langfuse = pytest.mark.skipif(not _langfuse_reachable(), reason=f"Langfuse not reachable at {LANGFUSE_URL}")
skip_no_langfuse_auth = pytest.mark.skipif(not LANGFUSE_AUTH, reason="Langfuse auth not configured via LANGFUSE_OTEL_AUTH, LANGFUSE_BASIC_AUTH, or LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY")


def _langfuse_headers() -> dict[str, str]:
    return {"Authorization": f"Basic {LANGFUSE_AUTH}"}


def _gateway_api_headers(jwt_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/json",
    }


def _lookup_server_id(jwt_token: str, server_name: str) -> str:
    """Return the server ID for a named virtual server."""
    response = httpx.get(
        f"{BASE_URL}/servers",
        headers=_gateway_api_headers(jwt_token),
        timeout=10,
    )
    response.raise_for_status()
    for server in response.json():
        if server.get("name") == server_name:
            return str(server["id"])
    pytest.fail(f"Could not find server named {server_name!r}")


def _send_jsonrpc_http(jwt_token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send a direct JSON-RPC request to a live MCP HTTP endpoint."""
    response = httpx.post(
        f"{BASE_URL}{path}",
        headers={
            **_gateway_api_headers(jwt_token),
            "Content-Type": "application/json",
            "mcp-protocol-version": "2025-11-25",
        },
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _fetch_langfuse_traces(limit: int = 50) -> dict:
    """Fetch recent traces from the Langfuse public API.

    Args:
        limit: Maximum number of recent traces to fetch.

    Returns:
        Parsed JSON response from the Langfuse traces endpoint.
    """
    response = httpx.get(f"{LANGFUSE_URL}/api/public/traces", headers=_langfuse_headers(), params={"limit": limit}, timeout=10)
    response.raise_for_status()
    return response.json()


def _parse_timestamp(value: str | None) -> float:
    """Parse an ISO8601 timestamp from Langfuse into epoch seconds.

    Args:
        value: ISO8601 timestamp string or ``None``.

    Returns:
        Epoch seconds, or ``0.0`` when parsing fails.
    """
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _wait_for_fresh_trace(triggered_after: float, predicate: Callable[[dict[str, Any]], bool], timeout_seconds: int = 60) -> dict[str, Any]:
    """Poll Langfuse until a fresh trace matches the provided predicate."""
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.time() < deadline:
        last_payload = _fetch_langfuse_traces(limit=100)
        for trace in last_payload.get("data") or []:
            if _parse_timestamp(trace.get("timestamp")) < triggered_after:
                continue
            if predicate(trace):
                return trace
        time.sleep(2)

    trace_summaries = [f"{trace.get('timestamp')} {trace.get('name')}" for trace in (last_payload or {}).get("data", [])[:10]]
    pytest.fail(f"Did not observe a matching fresh Langfuse trace within timeout. Recent traces: {trace_summaries}")


def _trace_attributes(trace: dict[str, Any]) -> dict[str, Any]:
    """Extract flattened trace attributes from a Langfuse trace payload."""
    return (trace.get("metadata") or {}).get("attributes") or {}


def _is_admin_jwt_trace(trace: dict[str, Any]) -> bool:
    """Return whether a Langfuse trace belongs to the admin JWT test flow."""
    trace_attrs = _trace_attributes(trace)
    tags = trace.get("tags") or []
    return trace.get("userId") == ADMIN_EMAIL and trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL and isinstance(tags, list) and "auth:jwt" in tags


@pytest.fixture(scope="module")
def jwt_token() -> str:
    """Create a standard JWT for live MCP and Langfuse smoke traffic."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    return result.stdout.strip().strip('"')


@pytest.fixture(scope="module")
def admin_jwt_token() -> str:
    """Create an admin-bypass JWT for privileged live smoke traffic."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET, "--admin"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"Admin JWT generation failed: {result.stderr}"
    return result.stdout.strip().strip('"')


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_public_traces_endpoint_returns_trace_list():
    """Langfuse public traces API should be reachable with configured credentials."""
    payload = _fetch_langfuse_traces(limit=5)
    assert isinstance(payload, dict)


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_resource_read_trace(jwt_token: str):
    """A raw resources/read should export resource URI metadata.

    Uses _send_jsonrpc_http (HTTP direct path) so remains valid after wrapper removal.
    """
    fast_time_server_id = _lookup_server_id(jwt_token, "Fast Time Server")
    triggered_after = time.time() - 1
    read_response = _send_jsonrpc_http(
        jwt_token,
        f"/servers/{fast_time_server_id}/mcp/",
        {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "time://formats"}},
    )
    assert "error" not in read_response, f"resources/read returned error: {read_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and _trace_attributes(candidate).get("resource.uri") == "time://formats",
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert trace_attrs.get("resource.uri") == "time://formats"
    assert trace_attrs.get("langfuse.trace.name") == "Resource: time://formats"


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_root_list_trace(admin_jwt_token: str):
    """An authenticated root listing should export a Langfuse root-list trace."""
    triggered_after = time.time() - 1
    response = httpx.get(
        f"{BASE_URL}/roots",
        headers=_gateway_api_headers(admin_jwt_token),
        timeout=20,
    )
    response.raise_for_status()
    assert isinstance(response.json(), list)

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and (candidate.get("name") in {"root.list", "Roots"} or _trace_attributes(candidate).get("langfuse.trace.name") == "Roots"),
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert trace_attrs.get("langfuse.trace.name") == "Roots"
