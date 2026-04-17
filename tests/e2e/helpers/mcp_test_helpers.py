# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/mcp_test_helpers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared MCP protocol test helpers for E2E tests.

Provides utilities for testing MCP JSON-RPC protocol via the mcpgateway.wrapper
stdio transport plus the mcp-cli CLI. Used by the remaining subprocess-based
E2E suites (``test_mcp_rbac_transport.py`` — multi-user RBAC + multi-transport,
and ``test_langfuse_traces.py`` — tracing integration).

New protocol-level E2E tests should prefer the FastMCP ``Client``-based pattern
in ``test_mcp_protocol_e2e.py`` (no subprocess, no external CLI). The helpers
below are retained for the suites that still need mcp-cli / wrapper semantics
and are candidates for removal once those suites migrate.
"""

# Future
from __future__ import annotations

# Standard
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080")  # IPv4 explicit — `localhost` resolves IPv6-first under the test conftest's getaddrinfo stub, which docker-compose doesn't bind
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
TOKEN_EXPIRY = os.getenv("MCP_CLI_TOKEN_EXPIRY", "60")  # minutes
MCP_CLI_TIMEOUT = int(os.getenv("MCP_CLI_TIMEOUT", "30"))  # seconds per command
WRAPPER_PYTHON = os.getenv("MCP_CLI_PYTHON", sys.executable)
TEST_PASSWORD = "SecureTestPass123!"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------
def _mcp_cli_available() -> bool:
    return shutil.which("mcp-cli") is not None


def _gateway_reachable() -> bool:
    try:
        # Third-Party
        import httpx

        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _rust_mcp_gateway_active() -> bool:
    try:
        # Third-Party
        import httpx

        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code != 200:
            return False
        return resp.headers.get("x-contextforge-mcp-transport-mounted") == "rust"
    except Exception:
        return False


def _rust_mcp_session_core_active() -> bool:
    try:
        # Third-Party
        import httpx

        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code != 200:
            return False
        return resp.headers.get("x-contextforge-mcp-transport-mounted") == "rust" and resp.headers.get("x-contextforge-mcp-session-core-mode") == "rust"
    except Exception:
        return False


skip_no_mcp_cli = pytest.mark.skipif(not _mcp_cli_available(), reason="mcp-cli not installed (pip install 'mcp-cli[cli]')")
skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"ContextForge not reachable at {BASE_URL}")
skip_no_rust_mcp_gateway = pytest.mark.skipif(not _rust_mcp_gateway_active(), reason=f"Rust MCP public transport not active at {BASE_URL}")
skip_no_rust_mcp_session_core = pytest.mark.skipif(
    not _rust_mcp_session_core_active(),
    reason=f"Rust MCP session core not active at {BASE_URL}",
)


# ---------------------------------------------------------------------------
# MCP CLI helpers
# ---------------------------------------------------------------------------
def run_mcp_cli(config_path, subcommand: str, *extra_args: str, timeout: int = MCP_CLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    cmd = ["mcp-cli", subcommand, "--config-file", str(config_path), "--server", "contextforge", *extra_args]
    return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)


def extract_json_from_output(text: str) -> Any:
    """Extract first JSON array or object from mcp-cli output (which includes banner lines)."""
    lines = text.splitlines()
    json_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            json_start = i
            break
    if json_start is None:
        raise ValueError(f"No JSON found in output:\n{text}")
    json_text = "\n".join(lines[json_start:])
    return json.loads(json_text)


# ---------------------------------------------------------------------------
# JSON-RPC via wrapper helpers
# ---------------------------------------------------------------------------
def send_jsonrpc_via_wrapper(
    env: dict[str, str],
    messages: list[dict[str, Any]],
    timeout: int = 15,
    settle_seconds: float = 3.0,
) -> list[dict[str, Any]]:
    """Send JSON-RPC messages to mcpgateway.wrapper via Popen.

    The wrapper cancels in-flight requests when stdin closes (EOF triggers shutdown).
    We use Popen to write messages, wait for responses to arrive, then close stdin.
    """
    proc = subprocess.Popen(
        [WRAPPER_PYTHON, "-m", "mcpgateway.wrapper"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Collect stdout lines in a background thread
    stdout_lines: list[str] = []
    read_done = threading.Event()

    def _reader() -> None:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            stdout_lines.append(raw_line.rstrip("\n"))
        read_done.set()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    def _parsed_response_ids() -> set[Any]:
        """Return currently observed JSON-RPC response ids from stdout lines."""
        response_ids: set[Any] = set()
        for line in stdout_lines:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in payload:
                response_ids.add(payload["id"])
        return response_ids

    expected_response_ids = {msg["id"] for msg in messages if "id" in msg}

    # Write all messages
    assert proc.stdin is not None
    for msg in messages:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    # Wait for responses to arrive before closing stdin. On a freshly recreated
    # stack, tool/prompt calls can take longer than a fixed short sleep.
    deadline = time.time() + timeout

    while time.time() < deadline:
        if expected_response_ids.issubset(_parsed_response_ids()):
            break
        time.sleep(0.1)

    # Close stdin to trigger graceful shutdown
    proc.stdin.close()

    # Wait for process to finish
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    read_done.wait(timeout=5)

    # Parse JSON-RPC responses
    responses = []
    for line in stdout_lines:
        line = line.strip()
        if line and line.startswith("{"):
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return responses


def build_initialize(request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mcp-cli-test", "version": "1.0.0"},
        },
    }


def build_wrapper_env(access_token: str, server_url: str = BASE_URL) -> dict[str, str]:
    """Build environment dict for mcpgateway.wrapper with the given token."""
    return {
        **os.environ,
        "MCP_AUTH": f"Bearer {access_token}",
        "MCP_SERVER_URL": server_url,
        "MCP_TOOL_CALL_TIMEOUT": "30",
    }


def get_response_by_id(responses: list[dict[str, Any]], request_id: int) -> dict[str, Any] | None:
    """Find a JSON-RPC response matching a given request ID."""
    return next((r for r in responses if r.get("id") == request_id), None)
