# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/mcp_test_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared MCP protocol test helpers for E2E tests.

New protocol-level E2E tests should prefer the FastMCP ``Client``-based pattern
in ``test_mcp_protocol_e2e.py`` (no subprocess, no external CLI).
"""

# Future
from __future__ import annotations

# Standard
import os
from typing import Any

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Force IPv4: localhost can resolve to ::1 first, but compose only publishes the
# gateway on IPv4, so an IPv6-first client hangs. Covers MCP_CLI_BASE_URL too.
BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080").replace("//localhost", "//127.0.0.1")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
TOKEN_EXPIRY = os.getenv("MCP_CLI_TOKEN_EXPIRY", "60")  # minutes
TEST_PASSWORD = "SecureTest!Xy9#Qw2@Kp5"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------
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


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"ContextForge not reachable at {BASE_URL}")
skip_no_rust_mcp_gateway = pytest.mark.skipif(not _rust_mcp_gateway_active(), reason=f"Rust MCP public transport not active at {BASE_URL}")
skip_no_rust_mcp_session_core = pytest.mark.skipif(
    not _rust_mcp_session_core_active(),
    reason=f"Rust MCP session core not active at {BASE_URL}",
)


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

