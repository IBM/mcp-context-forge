# -*- coding: utf-8 -*-
"""Server feature surface checks for methods present in MCP 2025-11-25 schema."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_server_features
@pytest.mark.mcp_required
@pytest.mark.parametrize(
    ("method", "key"),
    (
        ("tools/list", "tools"),
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
        ("prompts/list", "prompts"),
    ),
)
def test_server_discovery_methods_return_expected_result_shapes(
    method,
    key,
    rpc_call,
    ensure_not_auth_error,
):
    response = rpc_call(method, request_id=f"{method}-shape")
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == f"{method}-shape"
    assert "result" in payload
    assert key in payload["result"]
    assert isinstance(payload["result"][key], list)


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_server_features
@pytest.mark.mcp_required
def test_logging_set_level_returns_empty_result(rpc_call, ensure_not_auth_error):
    response = rpc_call(
        "logging/setLevel",
        request_id="log-level-info",
        params={"level": "info"},
    )
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "log-level-info"
    assert payload["result"] == {}
