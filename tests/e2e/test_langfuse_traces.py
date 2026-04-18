# -*- coding: utf-8 -*-
"""End-to-end smoke checks for Langfuse trace export.

These tests are environment-gated and intended for manual or CI runs against a
live gateway + Langfuse stack. They are skipped unless both services are
reachable and the required credentials are present.
"""

# Standard
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

# Third-Party
import httpx
import pytest

# Local
from .helpers.mcp_test_helpers import ADMIN_EMAIL
from .helpers.mcp_test_helpers import build_initialize as _build_initialize
from .helpers.mcp_test_helpers import build_wrapper_env as _build_wrapper_env
from .helpers.mcp_test_helpers import JWT_SECRET
from .helpers.mcp_test_helpers import TOKEN_EXPIRY
from .helpers.mcp_test_helpers import WRAPPER_PYTHON
from .helpers.mcp_test_helpers import get_response_by_id as _get_response_by_id
from .helpers.mcp_test_helpers import run_mcp_cli as _run_mcp_cli
from .helpers.mcp_test_helpers import send_jsonrpc_via_wrapper as _send_jsonrpc_via_wrapper
from .helpers.mcp_test_helpers import skip_no_mcp_cli

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


@pytest.fixture(scope="module")
def config_file(jwt_token: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build an mcp-cli config that targets the live gateway through the wrapper."""
    config = {
        "mcpServers": {
            "contextforge": {
                "command": WRAPPER_PYTHON,
                "args": ["-m", "mcpgateway.wrapper"],
                "env": {
                    "MCP_AUTH": f"Bearer {jwt_token}",
                    "MCP_SERVER_URL": BASE_URL,
                    "MCP_TOOL_CALL_TIMEOUT": "30",
                },
            }
        }
    }
    tmp_dir = tmp_path_factory.mktemp("langfuse_trace_smoke")
    config_path = tmp_dir / "server_config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


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
def test_langfuse_trace_export_eventually_contains_initialize_trace(jwt_token: str):
    """A raw MCP initialize should export a Langfuse trace for the session-core path."""
    triggered_after = time.time() - 1
    responses = _send_jsonrpc_via_wrapper(
        _build_wrapper_env(jwt_token),
        [_build_initialize(1)],
        settle_seconds=2.0,
    )
    init_response = _get_response_by_id(responses, 1)
    assert init_response is not None, f"No initialize response: {responses}"
    assert "error" not in init_response, f"initialize returned error: {init_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and (candidate.get("name") == "mcp.initialize" or _trace_attributes(candidate).get("langfuse.trace.name") == "mcp.initialize"),
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert trace_attrs.get("langfuse.trace.name") == "mcp.initialize"


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@skip_no_mcp_cli
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_fresh_mcp_cli_tool_list_trace(config_file: Path):
    """A fresh MCP CLI tool listing should expose Langfuse trace metadata."""
    triggered_after = time.time() - 1
    result = _run_mcp_cli(config_file, "tools", "--raw")
    assert result.returncode == 0, f"mcp-cli tools --raw failed: {result.stderr}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and candidate.get("name") in {"tool.list", "Tools"},
    )
    metadata = trace.get("metadata") or {}
    resource_attrs = metadata.get("resourceAttributes") or {}
    trace_attrs = metadata.get("attributes") or {}

    assert resource_attrs.get("service.name") == "contextforge-gateway"
    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert any(isinstance(tag, str) and tag.startswith("env:") for tag in trace.get("tags", []))
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert "auth:jwt" in str(trace_attrs.get("langfuse.trace.tags"))
    assert trace_attrs.get("langfuse.trace.name")


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_resource_list_trace(jwt_token: str):
    """A raw resources/list should export a Langfuse resource-list trace."""
    triggered_after = time.time() - 1
    responses = _send_jsonrpc_via_wrapper(
        _build_wrapper_env(jwt_token),
        [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}},
        ],
        settle_seconds=4.0,
    )
    list_response = _get_response_by_id(responses, 2)
    assert list_response is not None, f"No resources/list response: {responses}"
    assert "error" not in list_response, f"resources/list returned error: {list_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and (candidate.get("name") in {"resource.list", "Resources"} or _trace_attributes(candidate).get("langfuse.trace.name") == "Resources"),
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert trace_attrs.get("langfuse.trace.name") == "Resources"


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_resource_read_trace(jwt_token: str):
    """A raw resources/read should export resource URI metadata."""
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


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_tool_call_input(jwt_token: str):
    """A raw tool call should export Langfuse input data for the invoked tool."""
    triggered_after = time.time() - 1
    responses = _send_jsonrpc_via_wrapper(
        _build_wrapper_env(jwt_token),
        [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}}},
        ],
        settle_seconds=4.0,
    )
    call_response = _get_response_by_id(responses, 2)
    assert call_response is not None, f"No tools/call response: {responses}"
    assert "error" not in call_response, f"tools/call returned error: {call_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and _trace_attributes(candidate).get("tool.name") == "fast-time-get-system-time" and candidate.get("input") == {"timezone": "UTC"},
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace.get("input") == {"timezone": "UTC"}
    assert trace_attrs.get("langfuse.user.id") == ADMIN_EMAIL
    assert trace_attrs.get("tool.name") == "fast-time-get-system-time"
    assert trace_attrs.get("langfuse.trace.name") == "Tool: fast-time-get-system-time"


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_prompt_render_linkage(jwt_token: str):
    """A prompt render should export Langfuse prompt linkage metadata."""
    prompt_args = {
        "time": "2025-01-15T12:00:00Z",
        "from_timezone": "UTC",
        "to_timezones": "America/New_York,Europe/Dublin",
        "include_context": "true",
    }
    triggered_after = time.time() - 1
    responses = _send_jsonrpc_via_wrapper(
        _build_wrapper_env(jwt_token),
        [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": "fast-time-convert-time-detailed", "arguments": prompt_args}},
        ],
        settle_seconds=4.0,
    )
    prompt_response = _get_response_by_id(responses, 2)
    assert prompt_response is not None, f"No prompts/get response: {responses}"
    assert "error" not in prompt_response, f"prompts/get returned error: {prompt_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and _trace_attributes(candidate).get("langfuse.observation.prompt.name") == "fast-time-convert-time-detailed",
    )
    trace_attrs = _trace_attributes(trace)

    assert trace.get("userId") == ADMIN_EMAIL
    assert isinstance(trace.get("tags"), list)
    assert "auth:jwt" in trace.get("tags", [])
    assert trace_attrs.get("langfuse.observation.prompt.name") == "fast-time-convert-time-detailed"
    assert trace_attrs.get("langfuse.trace.name") == "Prompt: fast-time-convert-time-detailed"
    prompt_version = trace_attrs.get("langfuse.observation.prompt.version")
    if prompt_version is not None:
        if isinstance(prompt_version, str):
            assert prompt_version.isdigit()
        else:
            assert isinstance(prompt_version, (int, float))


@skip_no_gateway
@skip_no_langfuse
@skip_no_langfuse_auth
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_sanitized_prompt_error(jwt_token: str):
    """Prompt failures should export sanitized Langfuse error metadata."""
    bad_prompt_name = "https://prompt.example.com/item?api_key=supersecret"
    triggered_after = time.time() - 1
    responses = _send_jsonrpc_via_wrapper(
        _build_wrapper_env(jwt_token),
        [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": bad_prompt_name}},
        ],
        settle_seconds=4.0,
    )
    prompt_response = _get_response_by_id(responses, 2)
    assert prompt_response is not None, f"No prompts/get response: {responses}"
    assert "error" in prompt_response, f"prompts/get unexpectedly succeeded: {prompt_response}"

    trace = _wait_for_fresh_trace(
        triggered_after,
        lambda candidate: _is_admin_jwt_trace(candidate) and _trace_attributes(candidate).get("langfuse.trace.name") == "Prompt: https://prompt.example.com/item?api_key=REDACTED",
    )
    trace_attrs = _trace_attributes(trace)
    status_message = str(trace_attrs.get("langfuse.observation.status_message") or "")
    error_message = str(trace_attrs.get("error.message") or "")

    assert trace.get("userId") == ADMIN_EMAIL
    assert trace_attrs.get("error.type") == "PromptNotFoundError"
    assert "supersecret" not in status_message
    assert "supersecret" not in error_message
    assert "supersecret" not in trace_attrs.get("langfuse.trace.name", "")
    assert "REDACTED" in status_message
    assert status_message == error_message
