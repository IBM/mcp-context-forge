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

# Third-Party
import httpx
import pytest

# Local
from .mcp_test_helpers import ADMIN_EMAIL
from .mcp_test_helpers import JWT_SECRET
from .mcp_test_helpers import TOKEN_EXPIRY
from .mcp_test_helpers import WRAPPER_PYTHON
from .mcp_test_helpers import extract_json_from_output as _extract_json_from_output
from .mcp_test_helpers import run_mcp_cli as _run_mcp_cli
from .mcp_test_helpers import skip_no_mcp_cli


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


@pytest.fixture(scope="module")
def jwt_token() -> str:
    """Create an admin JWT for live MCP CLI smoke traffic."""
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
@skip_no_mcp_cli
@pytest.mark.e2e
def test_langfuse_trace_export_eventually_contains_fresh_mcp_cli_tool_list_trace(config_file: Path):
    """A freshly generated MCP CLI tool listing should appear in Langfuse."""
    triggered_after = time.time() - 1
    result = _run_mcp_cli(config_file, "tools", "--raw")
    assert result.returncode == 0, f"mcp-cli tools --raw failed: {result.stderr}"
    tools = _extract_json_from_output(result.stdout)
    assert isinstance(tools, list)

    deadline = time.time() + 60
    last_payload = None

    while time.time() < deadline:
        last_payload = _fetch_langfuse_traces(limit=50)

        data = last_payload.get("data") or []
        for trace in data:
            if trace.get("name") not in {"tool.list", "Tools"}:
                continue
            if _parse_timestamp(trace.get("timestamp")) < triggered_after:
                continue

            metadata = trace.get("metadata") or {}
            resource_attrs = metadata.get("resourceAttributes") or {}
            assert resource_attrs.get("service.name") == "contextforge-gateway"
            return
        time.sleep(2)

    trace_summaries = [
        f"{trace.get('timestamp')} {trace.get('name')}"
        for trace in (last_payload or {}).get("data", [])[:10]
    ]
    pytest.fail(f"Did not observe a fresh tool listing trace in Langfuse within timeout. Recent traces: {trace_summaries}")
