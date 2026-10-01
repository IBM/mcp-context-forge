# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp_a2a/test_vault_header_injection.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway recast of the Vault plugin MCP tool-path E2E
(``tool_pre_invoke``). Replaces the subprocess-based
``tests/e2e/test_vault_plugin_a2a_e2e.py::test_tool_path_injects_token_and_strips_vault_header``,
which asserted by scraping the echo backend's stdout log.

Assertions run over the wire through the fast-time-server ``whoami`` tool,
which reflects the HTTP headers it received as a lowercased map
(``authorization`` is null when absent). The test proves:

- ``Authorization: Bearer <vault-token>`` injection on the upstream call.
- ``X-Vault-Tokens`` never reaches the upstream MCP server.

Requires a vault-enabled testing stack::

    ENABLE_HEADER_PASSTHROUGH=true \\
    ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true \\
    PLUGINS_CONFIG_FILE=plugins/vault/config_vault_e2e.yaml \\
    make testing-up

The module self-skips against a default ``make testing-up`` stack, where the
committed ``plugins/config.yaml`` keeps VaultPlugin in ``mode: disabled``.
The 431 header-size boundary scenarios of the old subprocess test are not
recast here: nginx rejects over-limit headers before the gateway sees them.
``HeaderSizeMiddleware`` keeps its unit coverage under
``tests/unit/mcpgateway/middleware/``.
"""

from __future__ import annotations

# Standard
import json
from typing import Any

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.mcp_a2a.conftest import VAULT_SYSTEM
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

TOOL_TOKEN = "tok-tool-live-e2e"  # pragma: allowlist secret


def _reflected_headers(result: dict[str, Any]) -> dict[str, Any]:
    """Extract the reflected header map from a ``whoami`` tool result.

    Args:
        result: JSON-RPC ``result`` payload from ``call_tool``.

    Returns:
        The lowercased header name -> value map the upstream server received.
    """
    structured = result.get("structuredContent") or result.get("structured_content")
    if isinstance(structured, dict):
        return structured
    parsed: dict[str, Any] = json.loads(_helpers.result_text(result))
    return parsed


def _call_whoami(admin_client: httpx.Client, vault_echo_server: dict[str, str], *, vault_tokens: dict[str, str] | None) -> dict[str, Any]:
    """Invoke ``whoami`` on the vault-tagged virtual server and return its header map.

    Args:
        admin_client: Authenticated admin HTTP client.
        vault_echo_server: Provisioned virtual server mapping from the fixture.
        vault_tokens: Vault token map to send as ``X-Vault-Tokens``, or
            ``None`` to call without the vault header.

    Returns:
        The reflected header map from the upstream fast-time-server.
    """
    session_id = _helpers.initialize_session(admin_client, server_id=vault_echo_server["server_id"], token=vault_echo_server["token"])
    extra_headers = {"X-Vault-Tokens": json.dumps(vault_tokens)} if vault_tokens is not None else None
    result = _helpers.call_tool(
        admin_client,
        server_id=vault_echo_server["server_id"],
        token=vault_echo_server["token"],
        tool_name=vault_echo_server["whoami_tool"],
        arguments={},
        session_id=session_id,
        extra_headers=extra_headers,
    )
    assert not result.get("isError") and not result.get("is_error"), f"whoami call failed: {result}"
    return _reflected_headers(result)


def test_tool_path_injects_token_and_strips_vault_header(admin_client: httpx.Client, vault_echo_server: dict[str, str]) -> None:
    """MCP tool path: Bearer injected upstream, X-Vault-Tokens stripped."""
    received = _call_whoami(admin_client, vault_echo_server, vault_tokens={VAULT_SYSTEM: TOOL_TOKEN})

    assert received.get("authorization") == f"Bearer {TOOL_TOKEN}", f"vault token was not injected as Bearer on the tool path: {received}"
    assert "x-vault-tokens" not in received, "SECURITY: X-Vault-Tokens leaked to the upstream MCP server"


def test_tool_path_without_vault_header_does_not_inject(admin_client: httpx.Client, vault_echo_server: dict[str, str]) -> None:
    """MCP tool path without the vault header: no vault Bearer reaches upstream."""
    received = _call_whoami(admin_client, vault_echo_server, vault_tokens=None)

    assert received.get("authorization") != f"Bearer {TOOL_TOKEN}", "vault Bearer injected without an X-Vault-Tokens header"
    assert "x-vault-tokens" not in received, "SECURITY: X-Vault-Tokens reached the upstream MCP server"
