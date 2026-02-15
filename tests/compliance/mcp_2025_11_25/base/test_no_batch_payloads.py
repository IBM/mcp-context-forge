# -*- coding: utf-8 -*-
"""Batch payload rejection tests for streamable HTTP MCP endpoint."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_base
@pytest.mark.mcp_required
def test_streamable_http_rejects_jsonrpc_batch(
    compliance_client,
    mcp_compliance_headers,
    mcp_compliance_rpc_path,
    ensure_not_auth_error,
):
    response = compliance_client.post(
        mcp_compliance_rpc_path,
        headers=mcp_compliance_headers,
        json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
    )
    ensure_not_auth_error(response)

    assert response.status_code == 400
    payload = response.json()
    assert payload.get("jsonrpc") == "2.0"
    assert payload.get("error", {}).get("code") in (-32600, -32602)
