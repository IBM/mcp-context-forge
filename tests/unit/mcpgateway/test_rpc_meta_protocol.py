# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_meta_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for per-request _meta protocol validation in the /rpc endpoint
(MCP 2026-07-28 requirement: mandatory keys and -32021 capability-gating).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.main import app

_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


def _rpc(method: str, params: dict) -> dict:
    """Return a JSON-RPC 2.0 request body.

    Pass modern or legacy ``_meta`` contents via *params* to control protocol era.
    """
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}


class TestModernMetaMissingKeyRejection:
    """Modern requests missing either mandatory key return -32600."""

    def test_missing_client_capabilities_key_returns_error(self, client, mock_db):
        """A modern request missing clientCapabilities returns -32600."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    # Modern attempt: protocolVersion present, clientCapabilities absent.
                    body = _rpc(
                        "tools/list",
                        {
                            "_meta": {
                                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                # clientCapabilities key intentionally absent
                            }
                        },
                    )
                    response = client.post("/rpc", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["error"]["code"] == -32600
        assert "clientCapabilities" in result["error"]["message"]

    def test_missing_protocol_version_key_returns_error(self, client, mock_db):
        """A modern request with only clientCapabilities (no protocolVersion) returns -32600."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    # Modern attempt: clientCapabilities present, protocolVersion absent.
                    body = _rpc(
                        "tools/list",
                        {
                            "_meta": {
                                "io.modelcontextprotocol/clientCapabilities": {},
                                # protocolVersion key intentionally absent
                            }
                        },
                    )
                    response = client.post("/rpc", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["error"]["code"] == -32600
        assert "protocolVersion" in result["error"]["message"]

    def test_legacy_request_with_no_meta_passes_through(self, client, mock_db):
        """A legacy request (no _meta protocol keys) is never rejected for lacking them."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                        mock_list.return_value = ([], None)
                        # Legacy request: no _meta protocol keys.
                        body = _rpc("tools/list", {})
                        response = client.post("/rpc", json=body)
        # A -32600 must not appear; any non-method-error result is fine
        result = response.json()
        assert result.get("error", {}).get("code") != -32600


class TestCapabilityGating:
    """Methods gated on client capabilities return -32021 when capability is absent."""

    def test_elicitation_without_declared_capability_returns_32021(self, client, mock_db):
        """elicitation/create returns -32021 when elicitation cap is not declared."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    with patch("mcpgateway.main.session_registry.get_client_capabilities", new=AsyncMock(return_value={})):
                        body = _rpc(
                            "elicitation/create",
                            {
                                "_meta": {
                                    **_MODERN_META,
                                    "io.modelcontextprotocol/clientCapabilities": {},  # no elicitation
                                },
                                "message": "Please enter your name",
                                "requestedSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
                            },
                        )
                        response = client.post("/rpc", json=body)
        result = response.json()
        assert result["error"]["code"] == -32021
        assert "elicitation" in result["error"]["message"]

    def test_elicitation_with_declared_capability_proceeds(self, client, mock_db):
        """elicitation/create does not return -32021 when capability is declared."""
        caps_with_elicitation = {**_MODERN_META, "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}}}
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.config.settings.mcpgateway_elicitation_enabled", True):
                    with patch("mcpgateway.main.get_db", return_value=mock_db):
                        with patch("mcpgateway.main.session_registry.get_client_capabilities", new=AsyncMock(return_value={"elicitation": {}})):
                            with patch("mcpgateway.main.session_registry.get_elicitation_capable_sessions", new=AsyncMock(return_value=[])):
                                body = _rpc(
                                    "elicitation/create",
                                    {
                                        "_meta": caps_with_elicitation,
                                        "message": "Enter name",
                                        "requestedSchema": {},
                                    },
                                )
                                response = client.post("/rpc", json=body)
        result = response.json()
        # Must NOT be a -32021 capability error (may be other errors from missing session etc.)
        assert result.get("error", {}).get("code") != -32021

    def test_sampling_without_declared_capability_returns_32021(self, client, mock_db):
        """sampling/createMessage returns -32021 when sampling cap is not declared."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    with patch("mcpgateway.main.session_registry.get_client_capabilities", new=AsyncMock(return_value={})):
                        body = _rpc(
                            "sampling/createMessage",
                            {
                                "_meta": {
                                    **_MODERN_META,
                                    "io.modelcontextprotocol/clientCapabilities": {},  # no sampling
                                },
                                "messages": [],
                                "maxTokens": 100,
                            },
                        )
                        response = client.post("/rpc", json=body)
        result = response.json()
        assert result["error"]["code"] == -32021
        assert "sampling" in result["error"]["message"]


class TestServerInfoStamping:
    """Modern responses carry io.modelcontextprotocol/serverInfo in result._meta."""

    def test_modern_tools_list_response_has_server_info(self, client, mock_db):
        """A modern tools/list response includes serverInfo in result._meta."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                        mock_list.return_value = ([], None)
                        # Modern request: both mandatory keys present.
                        body = _rpc("tools/list", {"_meta": _MODERN_META})
                        response = client.post("/rpc", json=body)
        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        assert "_meta" in result["result"]
        server_info = result["result"]["_meta"].get("io.modelcontextprotocol/serverInfo")
        assert isinstance(server_info, dict)
        assert "name" in server_info
        assert "version" in server_info

    def test_legacy_tools_list_response_has_no_server_info_meta(self, client, mock_db):
        """A legacy tools/list response does not have serverInfo stamped."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.config.settings.csrf_enabled", False):
                with patch("mcpgateway.main.get_db", return_value=mock_db):
                    with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                        mock_list.return_value = ([], None)
                        # Legacy request: no _meta protocol keys.
                        body = _rpc("tools/list", {})
                        response = client.post("/rpc", json=body)
        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        # Legacy response must not have serverInfo injected
        meta = result["result"].get("_meta") or {}
        assert "io.modelcontextprotocol/serverInfo" not in meta
