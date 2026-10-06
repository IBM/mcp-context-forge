# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_plugin_header_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for trusted A2A plugin output and protected caller header input.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_protocol import resolve_a2a_headers


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ({}, {"authorization": "Bearer configured", "cookie": "session=caller", "x-agent-key": "configured"}),
        ({"x-request-id": ""}, {"authorization": "Bearer configured", "cookie": "session=caller", "x-agent-key": "configured"}),
        ({"X-Agent-Key": ""}, {"authorization": "Bearer configured", "cookie": "session=caller", "x-agent-key": "configured"}),
        ({"x-agent-key": "plugin"}, {"authorization": "Bearer configured", "cookie": "session=caller", "x-agent-key": "plugin"}),
        ({"AUTHORIZATION": ""}, {"cookie": "session=caller", "x-agent-key": "configured"}),
        ({"Authorization": "Bearer first", "authorization": "Bearer plugin"}, {"authorization": "Bearer plugin", "cookie": "session=caller", "x-agent-key": "configured"}),
        ({"X-Vault-Tokens": "vault-data"}, {"authorization": "Bearer configured", "cookie": "session=caller", "x-agent-key": "configured"}),
    ],
)
def test_trusted_output_resolves_credentials_and_received_header_removal(output, expected):
    """Resolve plugin output without dropping withheld caller or configured authentication."""
    result = resolve_a2a_headers(
        caller_headers={"Authorization": "Bearer caller", "Cookie": "session=caller", "X-Request-ID": "caller"},
        configured_headers={"authorization": "Bearer configured", "X-Agent-Key": "configured", "x-vault-tokens": "vault-data"},
        plugin_input_headers={"x-request-id": "caller"},
        plugin_output_headers=output,
        uses_jsonrpc=False,
        protocol_version_header="1.0",
        correlation_id=None,
    )
    normalized = {name.lower(): value for name, value in result.items()}
    assert len(result) == len(normalized)
    assert normalized == {"content-type": "application/json", **expected}


def test_prepare_header_flows_with_flag_enabled(monkeypatch):
    """Caller passthrough can include sensitive headers while plugin input remains sanitized."""
    from mcpgateway import config
    from mcpgateway.services.a2a_service import A2AAgentService

    monkeypatch.setattr(config.settings, "enable_sensitive_header_passthrough", True)

    request_headers = {
        "authorization": "Bearer token",  # Lowercase as it would be in reality
        "x-custom-header": "value",
    }
    whitelist = ["Authorization", "X-Custom-Header"]

    plugin_headers, downstream_headers = A2AAgentService._prepare_header_flows(
        request_headers=request_headers,
        agent_passthrough_headers=whitelist,
    )

    # Plugin headers never include sensitive
    assert "authorization" not in plugin_headers
    assert plugin_headers.get("x-custom-header") == "value"

    # Downstream DOES include sensitive when flag enabled (line 1966)
    assert downstream_headers.get("authorization") == "Bearer token"
    assert downstream_headers.get("x-custom-header") == "value"
