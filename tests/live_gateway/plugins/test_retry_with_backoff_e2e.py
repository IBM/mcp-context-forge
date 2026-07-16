# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_retry_with_backoff_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the cpex-retry-with-backoff plugin.

Unlike the blocking plugins, retry-with-backoff does not reject a call - it
inspects the tool result on the ``tool_post_invoke`` hook and, when the result
is a (retryable) failure, asks the gateway to re-invoke the tool after a backoff
delay, up to ``max_retries`` times. This suite drives that behaviour with the
fast-time-server ``flaky`` tool, which returns ``isError=true`` for the first
``fail_times`` calls of a given ``key`` and then succeeds. Because the gateway
re-sends identical arguments on each retry, all attempts of one logical call
share a ``key`` and increment the same upstream counter, so the final result is
deterministic:

* with ``fail_times == max_retries`` the budget is just enough - the call
  eventually **succeeds** (a single non-retried call would have returned the
  error, so success proves the retries happened), and
* with ``fail_times > max_retries`` the budget is exhausted and the last
  **failure** surfaces unchanged.

The same assertions run against **both** enforcement paths, selected by the
``PLUGIN_ENFORCEMENT`` env var (set by the workflow matrix):

* ``static`` - the gateway boots with RetryWithBackoffPlugin in ``enforce`` mode
  (config derived from ``plugins/config.yaml``), and
* ``binding`` - the gateway boots with RetryWithBackoffPlugin ``disabled`` and a
  runtime tool-plugin-binding flips it to ``enforce`` for the test's team+tool.

Both paths bind the identical production config block, so one test body covers
both. The cpex plugin is never imported here - the gateway loads it from
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

PLUGIN_NAME = "RetryWithBackoffPlugin"


def _max_retries() -> int:
    """Return the retry budget from the committed config.

    Returns:
        The ``max_retries`` value (number of re-invocations the gateway will
        attempt on top of the original call).
    """
    block = _helpers.load_plugin_config_block(PLUGIN_NAME)
    return int(block["config"]["max_retries"])


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]):
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless RetryWithBackoffPlugin loaded on the gateway, and - on the
    bindings path - creates the runtime binding that makes it enforce, removing
    it on teardown.

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
        tool_name=fast_time_server["flaky_tool"],
    ):
        yield


def _flaky(admin_client: httpx.Client, fast_time_server: dict[str, str], *, key: str, fail_times: int) -> dict:
    """Invoke the fast-time flaky tool once, driving the tool_post_invoke hook.

    The gateway transparently re-invokes the tool on each retryable failure, so
    the returned payload is the *final* result after any retries.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        key: Unique per-call key isolating the upstream attempt counter.
        fail_times: Number of leading attempts the upstream fails before
            succeeding.

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
        tool_name=fast_time_server["flaky_tool"],
        arguments={"key": key, "fail_times": fail_times},
        session_id=session_id,
        request_id=1,
    )


def test_transient_failures_are_retried_until_success(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A call failing within the retry budget eventually succeeds.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    max_retries = _max_retries()
    key = f"retry-success-{_helpers.unique_suffix()}"

    # Fail exactly `max_retries` times: the original call plus `max_retries`
    # retries means the (max_retries + 1)-th attempt is the first to succeed.
    result = _flaky(admin_client, fast_time_server, key=key, fail_times=max_retries)

    assert result == {
        "content": [{"type": "text", "text": f"flaky recovered after {max_retries + 1} attempt(s)"}],
        "isError": False,
    }


def test_failures_beyond_budget_surface_error(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A call still failing after the retry budget surfaces the last error.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    max_retries = _max_retries()
    fail_times = max_retries + 1
    key = f"retry-exhaust-{_helpers.unique_suffix()}"

    # Fail one more time than the budget allows: after the original call plus
    # `max_retries` retries the upstream is still failing, so the last failure
    # (attempt max_retries + 1) surfaces unchanged.
    result = _flaky(admin_client, fast_time_server, key=key, fail_times=fail_times)

    assert result == {
        "content": [{"type": "text", "text": f"flaky transient failure (attempt {max_retries + 1}/{fail_times})"}],
        "isError": True,
    }
