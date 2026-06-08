# -*- coding: utf-8 -*-
"""Shared helpers for MCP E2E tests.

Provides common utilities for testing MCP protocol interactions,
including base URL detection, gateway availability checks, and
skip markers for tests that require a live gateway.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

# Base URL detection with fallback chain
BASE_URL = os.getenv(
    "MCP_CLI_BASE_URL",
    os.getenv("GATEWAY_URL", "http://localhost:8080")
)


def _is_gateway_available() -> bool:
    """Check if a live gateway is available at BASE_URL."""
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5.0, verify=False) as client:
            response = client.get("/health")
            return response.status_code == 200
    except Exception:
        return False


# Skip marker for tests requiring live gateway
skip_no_gateway = pytest.mark.skipif(
    not _is_gateway_available(),
    reason="Live gateway not available (set MCP_CLI_BASE_URL or start gateway)"
)


def get_gateway_base_url() -> str:
    """Return the configured gateway base URL."""
    return BASE_URL


def make_auth_headers(token: str) -> dict[str, str]:
    """Build standard authorization headers for API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def make_mcp_headers(
    token: str,
    *,
    session_id: str | None = None,
    protocol_version: str = "2025-11-25"
) -> dict[str, str]:
    """Build MCP JSON-RPC headers with optional session ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol_version,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def assert_json_response(
    response: httpx.Response,
    expected_status: int | tuple[int, ...] = 200,
) -> Any:
    """Assert response status and return parsed JSON body."""
    if isinstance(expected_status, int):
        expected_status = (expected_status,)
    
    assert response.status_code in expected_status, (
        f"Expected status {expected_status}, got {response.status_code}: {response.text}"
    )
    return response.json() if response.content else None


def assert_mcp_success(payload: dict[str, Any]) -> Any:
    """Assert MCP JSON-RPC response is successful and return result."""
    assert "error" not in payload or payload["error"] is None, (
        f"MCP request failed: {payload.get('error')}"
    )
    assert "result" in payload, f"MCP response missing result: {payload}"
    return payload["result"]


def assert_mcp_error(payload: dict[str, Any], expected_code: int | None = None) -> dict[str, Any]:
    """Assert MCP JSON-RPC response contains an error and return error object."""
    assert "error" in payload and payload["error"] is not None, (
        f"Expected MCP error but got success: {payload}"
    )
    error = payload["error"]
    if expected_code is not None:
        assert error.get("code") == expected_code, (
            f"Expected error code {expected_code}, got {error.get('code')}: {error}"
        )
    return error

