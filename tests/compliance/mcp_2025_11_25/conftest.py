# -*- coding: utf-8 -*-
"""Shared fixtures for MCP 2025-11-25 compliance tests."""

# Standard
import os
from typing import Any, Callable, Dict, Optional

# Third-Party
import httpx
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.config import settings
from mcpgateway.main import app

LATEST_MCP_PROTOCOL_VERSION = "2025-11-25"


@pytest.fixture(scope="session")
def mcp_compliance_base_url() -> Optional[str]:
    """Optional external base URL for black-box compliance runs."""
    value = os.getenv("MCP_COMPLIANCE_BASE_URL", "").strip()
    return value or None


@pytest.fixture(scope="session")
def mcp_compliance_rpc_path() -> str:
    """Path for streamable HTTP RPC endpoint."""
    path = os.getenv("MCP_COMPLIANCE_RPC_PATH", "/mcp/").strip() or "/mcp/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path


@pytest.fixture(scope="session")
def mcp_compliance_headers() -> Dict[str, str]:
    """Default headers for MCP streamable HTTP requests."""
    headers: Dict[str, str] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": LATEST_MCP_PROTOCOL_VERSION,
    }
    bearer_token = os.getenv("MCP_COMPLIANCE_BEARER_TOKEN", "").strip()
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


@pytest.fixture(scope="session")
def compliance_client(
    mcp_compliance_base_url: Optional[str],
):
    """Client fixture supporting both in-process and live endpoint modes."""
    if mcp_compliance_base_url:
        timeout = float(os.getenv("MCP_COMPLIANCE_TIMEOUT", "30"))
        with httpx.Client(base_url=mcp_compliance_base_url, follow_redirects=True, timeout=timeout) as client:
            yield client
        return

    # In-process mode: disable auth requirements for deterministic local checks.
    previous_auth_required = settings.auth_required
    previous_client_auth_enabled = settings.mcp_client_auth_enabled
    settings.auth_required = False
    settings.mcp_client_auth_enabled = False
    try:
        with TestClient(app, follow_redirects=True) as client:
            yield client
    finally:
        settings.auth_required = previous_auth_required
        settings.mcp_client_auth_enabled = previous_client_auth_enabled


@pytest.fixture
def ensure_not_auth_error() -> Callable[[Any], None]:
    """Skip a test when live endpoint auth credentials are missing."""

    def _ensure(response: Any) -> None:
        if response.status_code in (401, 403):
            pytest.skip(
                "Endpoint requires auth. Set MCP_COMPLIANCE_BEARER_TOKEN for live runs."
            )

    return _ensure


@pytest.fixture
def rpc_call(
    compliance_client: Any,
    mcp_compliance_headers: Dict[str, str],
    mcp_compliance_rpc_path: str,
) -> Callable[..., Any]:
    """Helper for issuing JSON-RPC requests against streamable HTTP endpoint."""

    def _call(
        method: str,
        *,
        request_id: Any = 1,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        path: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        return compliance_client.post(
            path or mcp_compliance_rpc_path,
            headers=headers or mcp_compliance_headers,
            json=payload,
        )

    return _call


@pytest.fixture
def initialize_request() -> Dict[str, Any]:
    """Canonical initialize params for latest protocol tests."""
    return {
        "protocolVersion": LATEST_MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "mcp-compliance-suite", "version": "1.0.0"},
    }
