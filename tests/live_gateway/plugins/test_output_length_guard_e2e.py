# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_output_length_guard_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end gateway test for the cpex-output-length-guard plugin.

Drives the plugin's ``tool_post_invoke`` hook by echoing tool output through a
live gateway and asserts that:

* a payload exceeding ``max_chars`` is **blocked** when ``strategy: block``, and
* a payload within ``max_chars`` passes through unchanged.

The same assertions run against **both** enforcement paths, selected by the
``PLUGIN_ENFORCEMENT`` env var (set by the workflow matrix):

* ``static`` — the gateway boots with OutputLengthGuardPlugin in ``enforce``
  mode (config derived from ``plugins/config.yaml``), and
* ``binding`` — the gateway boots with OutputLengthGuardPlugin ``disabled`` and
  a runtime tool-plugin-binding flips it to ``enforce`` for the test's
  team+tool.

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

PLUGIN_NAME = "OutputLengthGuardPlugin"

# A payload that exceeds the committed ``max_chars: 15000`` limit. 16 000 'A'
# characters is deterministically over the threshold regardless of any
# per-deployment tuning.
OVERSIZED_PAYLOAD = "A" * 16_000

# A short payload well within the committed limit.
SHORT_PAYLOAD = "The result is within bounds."

# Exact block message the gateway surfaces when OutputLengthGuardPlugin blocks a
# tool result. The gateway wraps violations as
# "{hook} blocked by plugin {name}: {code} - {reason} ({description})"
# (plugins/framework/manager.py). The cpex output-length-guard emits code
# OUTPUT_LENGTH_VIOLATION with reason "Output length out of bounds" and
# description "Result length {n} exceeds max_chars {m}", so the prefix is
# deterministic regardless of the exact lengths at runtime.
EXPECTED_BLOCK_PREFIX = "tool_post_invoke blocked by plugin OutputLengthGuardPlugin: OUTPUT_LENGTH_VIOLATION - Output length out of bounds"


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless OutputLengthGuardPlugin loaded on the gateway, and — on
    the bindings path — creates the runtime binding with ``strategy: block`` so
    both paths surface the same block behaviour, removing it on teardown.

    The committed static config uses ``strategy: truncate``; on the static path
    the test asserts blocking, which requires ``strategy: block``. The static
    path therefore uses a ``config_overrides`` with ``strategy: block``; this
    works because ``plugin_enforcement`` on the ``static`` path only calls
    ``assert_plugin_active`` (no binding is created), and the test must pass on
    the ``static`` path as-is or be marked ``_static_only`` if appropriate.

    For the bindings path, ``config_overrides`` applies the block strategy
    explicitly so both paths produce a consistent assertion.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.

    Yields:
        ``None`` once the enforcement path is active.
    """
    with _helpers.plugin_enforcement(
        admin_client,
        fast_time_server=fast_time_server,
        plugin_name=PLUGIN_NAME,
        config_overrides={"strategy": "block", "max_chars": 15000},
    ):
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


def test_oversized_tool_output_is_blocked(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A tool result exceeding max_chars is blocked by OutputLengthGuardPlugin.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    result = _echo(admin_client, fast_time_server, OVERSIZED_PAYLOAD)

    assert result["isError"] is True
    block_text = _helpers.result_text(result)
    assert block_text.startswith(EXPECTED_BLOCK_PREFIX), f"unexpected block message: {block_text!r}"


def test_short_tool_output_passes_through(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A tool result within max_chars passes through unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    result = _echo(admin_client, fast_time_server, SHORT_PAYLOAD)

    assert result == {
        "content": [{"type": "text", "text": SHORT_PAYLOAD}],
        "isError": False,
    }
