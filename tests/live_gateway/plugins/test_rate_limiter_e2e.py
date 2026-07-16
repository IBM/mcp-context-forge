# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_rate_limiter_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the cpex-rate-limiter plugin.

Drives the plugin's ``tool_pre_invoke`` hook by repeatedly invoking a live tool
through the gateway and asserts that:

* a call within the per-user limit passes through unchanged, and
* the first call past the limit is **blocked** with a ``RATE_LIMIT`` violation.

The plugin keeps its counters in Redis (the production backend), so a Redis
service must be reachable; a per-test flush of the plugin's key prefix isolates
each test's fixed window. The same assertions run against **both** enforcement
paths, selected by the ``PLUGIN_ENFORCEMENT`` env var (set by the workflow
matrix):

* ``static`` — the gateway boots with RateLimiterPlugin in ``enforce`` mode
  (config derived from ``plugins/config.yaml``), and
* ``binding`` — the gateway boots with RateLimiterPlugin ``disabled`` and a
  runtime tool-plugin-binding flips it to ``enforce`` for the test's team+tool.

Both paths bind the identical production config block, so one test body covers
both. The cpex plugin is never imported here — the gateway loads it from
``PLUGINS_CONFIG_FILE``; ``plugin_enforcement`` asserts it actually loaded so a
broken build fails loudly instead of skipping.
"""

from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest
import redis as redis_lib

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

PLUGIN_NAME = "RateLimiterPlugin"

# Exact block message the gateway surfaces when RateLimiterPlugin blocks a tool
# call on the tool_pre_invoke hook. The gateway wraps violations as
# "{hook} blocked by plugin {name}: {code} - {reason} ({description})"; the cpex
# rate-limiter emits code RATE_LIMIT with reason/description "Rate limit
# exceeded" (rate_limiter src/plugin.rs build_violation), so the full message is
# deterministic.
EXPECTED_BLOCK_MESSAGE = "tool_pre_invoke blocked by plugin RateLimiterPlugin: RATE_LIMIT - Rate limit exceeded (Rate limit exceeded)"


def _redis_url() -> str:
    """Resolve the rate-limiter Redis URL the same way the plugin config does.

    Returns:
        The Redis URL, honouring ``RATELIMITER_REDIS_URL`` then ``REDIS_URL``,
        falling back to a local default.
    """
    return os.getenv("RATELIMITER_REDIS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def _key_prefix() -> str:
    """Return the rate-limiter Redis key prefix from the committed config.

    Returns:
        The ``redis_key_prefix`` value (defaults to ``"rl"``).
    """
    block = _helpers.load_plugin_config_block(PLUGIN_NAME)
    return block["config"].get("redis_key_prefix", "rl")


def _user_limit() -> int:
    """Return the per-user request limit from the committed config.

    Returns:
        The integer request count from the ``by_user`` ``"N/period"`` spec.
    """
    block = _helpers.load_plugin_config_block(PLUGIN_NAME)
    spec = str(block["config"]["by_user"])  # e.g. "30/m"
    return int(spec.split("/", 1)[0])


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]):
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless RateLimiterPlugin loaded on the gateway, and — on the
    bindings path — creates the runtime binding that makes it enforce, removing
    it on teardown.

    The binding receives a resolved ``redis_url`` because the bindings API
    stores config verbatim and does not render the ``{{ env.* }}`` template that
    the static-config loader expands; without it the binding's limiter cannot
    reach Redis and fails open (never blocks).

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
        config_overrides={"redis_url": _redis_url()},
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_counters():
    """Flush the rate-limiter's Redis keys before each test to isolate windows.

    The plugin keeps per-user counters in Redis under its configured key prefix;
    clearing them before each test guarantees every test starts with a fresh
    fixed window regardless of execution order.

    Yields:
        ``None`` after the prefix has been cleared.
    """
    client = redis_lib.from_url(_redis_url())
    try:
        keys = list(client.scan_iter(match=f"{_key_prefix()}*"))
        if keys:
            client.delete(*keys)
    finally:
        client.close()
    yield


def _echo(admin_client: httpx.Client, fast_time_server: dict[str, str], message: str, *, session_id: str | None, request_id: int) -> dict:
    """Invoke the fast-time echo tool, driving the tool_pre_invoke hook.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        message: Text to echo through the gateway.
        session_id: MCP session id to reuse across calls.
        request_id: JSON-RPC request id.

    Returns:
        The JSON-RPC ``result`` payload from ``tools/call``.
    """
    return _helpers.call_tool(
        admin_client,
        server_id=fast_time_server["server_id"],
        token=fast_time_server["token"],
        tool_name=fast_time_server["echo_tool"],
        arguments={"message": message},
        session_id=session_id,
        request_id=request_id,
    )


def test_within_limit_passes(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """A call within the per-user limit passes through unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)

    result = _echo(admin_client, fast_time_server, "within-limit ping", session_id=session_id, request_id=1)

    assert result == {
        "content": [{"type": "text", "text": "within-limit ping"}],
        "isError": False,
    }


def test_exceeding_limit_is_blocked(admin_client: httpx.Client, fast_time_server: dict[str, str]) -> None:
    """Calls past the per-user limit are blocked with a RATE_LIMIT violation.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
    """
    limit = _user_limit()
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)

    blocked = None
    # A fresh window allows `limit` calls; the next is blocked. Sending up to
    # 2*limit+1 calls guarantees a block even if the fixed window rolls once
    # mid-burst (counters reset on the boundary).
    for i in range(2 * limit + 1):
        result = _echo(admin_client, fast_time_server, f"flood-{i}", session_id=session_id, request_id=i + 1)
        if result.get("isError"):
            blocked = result
            break

    assert blocked == {
        "content": [{"type": "text", "text": EXPECTED_BLOCK_MESSAGE}],
        "isError": True,
    }
