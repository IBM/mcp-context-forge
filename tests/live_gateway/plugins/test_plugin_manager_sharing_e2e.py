# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_plugin_manager_sharing_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end gateway test for plugin manager sharing between tools.

Tools of one team without tool-specific bindings share one plugin manager. A
tool with its own binding must still run with that binding, even when an
unbound tool of the same team ran first and filled the shared manager.

The test needs the ``binding`` enforcement path: the gateway boots with
SecretsDetection ``disabled`` and a runtime binding enables it for the echo
tool only.
"""

from __future__ import annotations

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [
    pytest.mark.e2e,
    skip_no_gateway,
    pytest.mark.skipif(_helpers.PLUGIN_ENFORCEMENT != "binding", reason="needs the runtime tool-plugin-binding enforcement path"),
]

PLUGIN_NAME = "SecretsDetection"
SECRET_PAYLOAD = "Here is my key AKIAFAKE12345EXAMPLE please rotate it."  # pragma: allowlist secret
CALLS = 5


def _call(admin_client: httpx.Client, fast_time_server: dict[str, str], tool_name: str, arguments: dict) -> dict:
    """Invoke one fast-time tool over a fresh MCP session.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        tool_name: Gateway-prefixed tool name.
        arguments: Tool arguments.

    Returns:
        The JSON-RPC ``result`` payload from ``tools/call``.
    """
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    return _helpers.call_tool(admin_client, server_id=server_id, token=token, tool_name=tool_name, arguments=arguments, session_id=session_id)


def test_bound_tool_keeps_its_binding_after_unbound_tool_ran(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """The bound echo tool is blocked on every call, whatever tool ran before it.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    with _helpers.plugin_enforcement(admin_client, fast_time_server=fast_time_server, plugin_name=PLUGIN_NAME):
        for _ in range(CALLS):
            unbound = _call(admin_client, fast_time_server, fast_time_server["flaky_tool"], {"key": _helpers.unique_suffix(), "fail_times": 0})
            assert unbound["isError"] is False

        for _ in range(CALLS):
            bound = _call(admin_client, fast_time_server, fast_time_server["echo_tool"], {"message": SECRET_PAYLOAD})
            assert bound["isError"] is True
            assert "SECRETS_DETECTED" in bound["content"][0]["text"]
