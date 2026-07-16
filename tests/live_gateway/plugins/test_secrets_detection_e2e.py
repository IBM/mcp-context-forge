# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_secrets_detection_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the cpex-secrets-detection plugin.

Drives the plugin's ``tool_post_invoke`` hook by echoing tool output through a
live gateway and asserts that:

* a payload containing an AWS access key id is **blocked**, and
* a clean payload passes through unchanged.

The same assertions run against **both** enforcement paths, selected by the
``PLUGIN_ENFORCEMENT`` env var (set by the workflow matrix):

* ``static`` — the gateway boots with SecretsDetection in ``enforce`` mode
  (config derived from ``plugins/config.yaml``), and
* ``binding`` — the gateway boots with SecretsDetection ``disabled`` and a
  runtime tool-plugin-binding flips it to ``enforce`` for the test's team+tool.

Both paths surface the identical block message, so one test body covers both.
The cpex plugin is never imported here — the gateway loads it from
``PLUGINS_CONFIG_FILE``; ``plugin_enforcement`` asserts it actually loaded so a
broken build fails loudly instead of skipping.
"""

from __future__ import annotations

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

PLUGIN_NAME = "SecretsDetection"

# A syntactically valid but obviously fake AWS access key id. Matches the
# detector pattern ``\bAKIA[0-9A-Z]{16}\b`` (AKIA + 16 upper/digit chars).
SECRET_PAYLOAD = "Here is my key AKIAFAKE12345EXAMPLE please rotate it."  # pragma: allowlist secret

# A clean payload with no secret-like tokens (no 32+ hex run, no key prefixes).
CLEAN_PAYLOAD = "The weather in San Francisco is 72F and sunny."

# Exact block message the gateway surfaces when SecretsDetection blocks a tool
# result. The gateway wraps violations as
# "{hook} blocked by plugin {name}: {code} - {reason} ({description})"
# (plugins/framework/manager.py) and the cpex tool_post_invoke violation strings
# are all constants, so the full message is deterministic.
EXPECTED_BLOCK_MESSAGE = "tool_post_invoke blocked by plugin SecretsDetection: SECRETS_DETECTED - Secrets detected (Potential secrets detected in tool result)"


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]):
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless SecretsDetection loaded on the gateway, and — on the
    bindings path — creates the runtime binding that makes it enforce, removing
    it on teardown.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.

    Yields:
        ``None`` once the enforcement path is active.
    """
    with _helpers.plugin_enforcement(admin_client, fast_time_server=fast_time_server, plugin_name=PLUGIN_NAME):
        yield


def _echo(admin_client: httpx.Client, fast_time_server: dict[str, str], message: str) -> dict:
    """Invoke the fast-time echo tool with a fresh MCP session.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        message: Text to echo through the gateway (and its plugin hooks).

    Returns:
        The JSON-RPC ``result`` payload from ``tools/call``.
    """
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    return _helpers.call_tool(
        admin_client,
        server_id=server_id,
        token=token,
        tool_name=fast_time_server["echo_tool"],
        arguments={"message": message},
        session_id=session_id,
    )


def test_secret_in_tool_output_is_blocked(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A tool result containing an AWS key is blocked by SecretsDetection.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    result = _echo(admin_client, fast_time_server, SECRET_PAYLOAD)

    assert result == {
        "content": [{"type": "text", "text": EXPECTED_BLOCK_MESSAGE}],
        "isError": True,
    }


def test_clean_tool_output_passes_through(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A clean tool result passes through unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    result = _echo(admin_client, fast_time_server, CLEAN_PAYLOAD)

    assert result == {
        "content": [{"type": "text", "text": CLEAN_PAYLOAD}],
        "isError": False,
    }
