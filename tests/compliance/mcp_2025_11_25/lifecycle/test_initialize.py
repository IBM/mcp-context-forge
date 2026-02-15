# -*- coding: utf-8 -*-
"""Initialize lifecycle checks for MCP 2025-11-25."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_lifecycle
@pytest.mark.mcp_required
def test_initialize_with_latest_protocol_version(rpc_call, ensure_not_auth_error, initialize_request):
    response = rpc_call("initialize", request_id="init-1", params=initialize_request)
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "init-1"
    assert "result" in payload
    assert payload["result"]["protocolVersion"] == "2025-11-25"
    assert "capabilities" in payload["result"]
    assert "serverInfo" in payload["result"]
    assert "name" in payload["result"]["serverInfo"]
    assert "version" in payload["result"]["serverInfo"]


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_lifecycle
@pytest.mark.mcp_required
def test_initialize_requires_protocol_version(rpc_call, ensure_not_auth_error):
    response = rpc_call(
        "initialize",
        request_id="init-missing-version",
        params={
            "capabilities": {},
            "clientInfo": {"name": "mcp-compliance-suite", "version": "1.0.0"},
        },
    )
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "init-missing-version"
    assert payload["error"]["code"] == -32602
