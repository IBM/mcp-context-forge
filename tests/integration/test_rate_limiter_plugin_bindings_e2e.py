# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rate_limiter_plugin_bindings_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

End-to-end integration test for the rate-limiter via the plugin-bindings API.

Configures a ``RateLimiterPlugin`` binding on a per-team / per-tool scope
through the gateway's ``POST /v1/tools/plugin_bindings`` endpoint, waits for
propagation, then invokes the bound tool repeatedly to confirm enforcement
fires (HTTP 429 / MCP isError with rate-limit text).

This sits between two existing test layers:

  * ``tests/unit/mcpgateway/routers/test_tool_plugin_bindings.py`` exercises
    the binding router in isolation; plugin invocation is mocked.
  * ``tests/integration/test_rate_limiter.py`` (and cpex-plugins integration
    tests) exercise the plugin against real Redis but instantiate it
    directly, bypassing the gateway's binding API entirely.

Neither covers the full path: binding API → gateway plugin manager → plugin
instantiation with the binding's config → enforcement at tool dispatch. This
file fills that gap.

Requirements:
    - Running gateway at $GATEWAY_URL (default ``http://localhost:8080``)
    - Redis reachable from the gateway pod at $BINDING_REDIS_URL
      (default ``redis://redis:6379/0`` — the docker-compose hostname)
    - At least one server with a registered tool
    - Admin user belongs to at least one team (true for the seeded
      ``admin@example.com`` personal team)

Usage:
    uv run pytest tests/integration/test_rate_limiter_plugin_bindings_e2e.py \\
        -v --with-integration
"""

# Standard
import os
import subprocess
import time
import uuid

# Third-Party
import pytest
import requests

from tests.helpers.integration_constants import PLUGIN_MODE_PROPAGATION_WAIT_SECONDS

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

# Redis URL from the gateway pod's perspective. Defaults to the docker-compose
# service hostname; override when the gateway runs elsewhere.
BINDING_REDIS_URL = os.environ.get("BINDING_REDIS_URL", "redis://redis:6379/0")

# Optional team override — useful when the runner knows the team_id ahead of
# time. If unset, the test discovers the admin's first team automatically.
OVERRIDE_TEAM_ID = os.environ.get("RATE_LIMITER_TEST_TEAM_ID")

# Postgres container name for the in-test team-id stamping below.
# Tools registered via the docker-compose registration job are created with
# ``team_id = NULL``; ``ToolService.invoke_tool`` falls back to ``server_id``
# (no ``::`` separator) for the plugin context_id when the tool has no
# team_id, which makes ``get_config_from_db`` skip the binding lookup
# entirely. To exercise the binding path we therefore have to stamp a
# team_id onto the test tool *after* the docker-compose registration runs.
# There is no public API to set ``tools.team_id`` after creation
# (``ToolUpdate`` schema in ``mcpgateway/schemas.py`` does not include it),
# so we shell out to ``docker exec ... psql``. This couples the test to the
# docker-compose dev stack — acceptable because the suite is already
# skip-guarded on a running gateway via ``_is_gateway_running()``.
PG_CONTAINER = os.environ.get(
    "RATE_LIMITER_TEST_PG_CONTAINER", "rl-binding-test-postgres-1"
)
PG_USER = os.environ.get("RATE_LIMITER_TEST_PG_USER", "postgres")
PG_DATABASE = os.environ.get("RATE_LIMITER_TEST_PG_DATABASE", "mcp")

PROPAGATION_WAIT = int(
    os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS))
)

# Burst size and configured limit — burst must clearly exceed the limit so
# enforcement is observable even with mild clock jitter.
BURST_SIZE = 15
BURST_LIMIT_PER_SEC = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_token() -> str:
    """Login and return a session token."""
    resp = requests.post(
        f"{GATEWAY_URL}/auth/login",
        json={"email": GATEWAY_EMAIL, "password": GATEWAY_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fresh_headers() -> dict:
    """Get fresh auth headers for an admin call."""
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_gateway_running() -> bool:
    """Return True if the gateway is reachable."""
    try:
        return requests.get(f"{GATEWAY_URL}/health", timeout=5).status_code == 200
    except requests.ConnectionError:
        return False


def _create_test_team() -> str:
    """Create a fresh non-personal team for the test and return its id.

    Personal teams (the only kind the seeded admin user has out of the box)
    are excluded by the admin-side ``/teams/`` listing path, so we can't
    discover one to scope a binding to. The simplest reliable path is to
    create a dedicated test team and clean it up at the end.

    Honors $RATE_LIMITER_TEST_TEAM_ID — if set, that team_id is reused as
    is and no team is created (caller owns lifecycle).
    """
    if OVERRIDE_TEAM_ID:
        return OVERRIDE_TEAM_ID

    headers = _fresh_headers()
    resp = requests.post(
        f"{GATEWAY_URL}/teams/",
        json={
            "name": f"rate-limiter-test-team-{uuid.uuid4().hex[:8]}",
            "description": "Ephemeral team for rate-limiter binding e2e test",
            "visibility": "private",
        },
        headers=headers,
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        pytest.skip(
            f"POST /teams/ returned {resp.status_code}; cannot create a test "
            f"team. Body: {resp.text[:200]}. "
            f"Set RATE_LIMITER_TEST_TEAM_ID to override."
        )
    return resp.json()["id"]


def _delete_test_team(team_id: str) -> None:
    """Delete the test team. Best-effort — skipped when the caller supplied
    the team_id via env override (lifecycle owned by the caller)."""
    if OVERRIDE_TEAM_ID:
        return
    try:
        requests.delete(
            f"{GATEWAY_URL}/teams/{team_id}",
            headers=_fresh_headers(),
            timeout=10,
        )
    except requests.RequestException:
        pass


def _auto_detect_server_and_tool() -> tuple[str, str]:
    """Find a server ID and tool name to drive the test against."""
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=headers, timeout=10)
    resp.raise_for_status()
    for server in resp.json():
        tools = server.get("associatedTools", [])
        # Prefer echo (cheap, predictable), fall back to any time tool.
        for tool in tools:
            if "echo" in tool.lower():
                return server["id"], tool
        for tool in tools:
            if "time" in tool.lower() and "convert" not in tool.lower():
                return server["id"], tool
    pytest.skip("No suitable server/tool found for plugin-bindings test")


def _resolve_tool_id(tool_name: str) -> str:
    """Look up the UUID for ``tool_name`` via ``GET /tools/``."""
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/tools/", headers=headers, timeout=10)
    resp.raise_for_status()
    for tool in resp.json():
        if tool.get("name") == tool_name:
            return tool["id"]
    pytest.skip(f"Tool {tool_name!r} not found via /tools/")


def _stamp_tool_team_id(tool_id: str, team_id: str) -> str:
    """Force ``tools.team_id`` for ``tool_id`` via ``docker exec ... psql``.

    Returns the previous team_id (may be ``None`` / empty string) so the
    fixture can restore it on teardown.

    Skips the test if the postgres container isn't reachable — better
    than letting the actual assertions fail with a confusing "no
    requests were rate-limited" message that hides the real cause.
    """
    # Read the current value so we can restore it on teardown.
    select_sql = f"SELECT COALESCE(team_id, '') FROM tools WHERE id = '{tool_id}';"
    cmd_select = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-tAc", select_sql,
    ]
    try:
        prev = subprocess.run(
            cmd_select, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(
            f"Cannot reach postgres container {PG_CONTAINER!r} to stamp tool team_id "
            f"({type(exc).__name__}: {exc}). Set RATE_LIMITER_TEST_PG_CONTAINER if "
            f"the container has a different name in your environment."
        )

    update_sql = f"UPDATE tools SET team_id = '{team_id}' WHERE id = '{tool_id}';"
    cmd_update = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-c", update_sql,
    ]
    subprocess.run(cmd_update, capture_output=True, text=True, timeout=10, check=True)
    return prev


def _restore_tool_team_id(tool_id: str, prev_team_id: str) -> None:
    """Restore ``tools.team_id`` after the module finishes. Best-effort."""
    if prev_team_id:
        sql = f"UPDATE tools SET team_id = '{prev_team_id}' WHERE id = '{tool_id}';"
    else:
        sql = f"UPDATE tools SET team_id = NULL WHERE id = '{tool_id}';"
    cmd = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-c", sql,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # cleanup is best-effort


def _post_binding(
    team_id: str,
    tool_name: str,
    config: dict,
    mode: str,
    binding_reference_id: str,
) -> dict:
    """POST a single rate-limiter binding via the API."""
    headers = _fresh_headers()
    payload = {
        "teams": {
            team_id: {
                "policies": [
                    {
                        "tool_names": [tool_name],
                        "plugin_id": "RateLimiterPlugin",
                        "mode": mode,
                        "priority": 50,
                        "config": config,
                        "binding_reference_id": binding_reference_id,
                    }
                ]
            }
        }
    }
    resp = requests.post(
        f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
        json=payload,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _delete_binding_by_reference(binding_reference_id: str) -> None:
    """Delete bindings created with the given reference id. Best-effort."""
    try:
        requests.delete(
            f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
            params={"binding_reference_id": binding_reference_id},
            headers=_fresh_headers(),
            timeout=10,
        )
    except requests.RequestException:
        pass  # cleanup best-effort; surface in test failure if it matters


def _mcp_initialize_session(
    server_id: str, headers: dict
) -> str | None:
    """Run the MCP streamable-HTTP initialize + initialized handshake.

    Returns the gateway-issued ``mcp-session-id`` so subsequent tool calls
    can be sent against the same session. Per-server plugin bindings are
    scoped (team, server_id, tool) and the plugin manager resolves them
    only on session-bound requests.

    Returns ``None`` on any handshake failure; callers should treat that
    as a transport error (not a rate-limit signal).
    """
    init_body = {
        "jsonrpc": "2.0",
        "id": "init",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "rate-limiter-binding-e2e", "version": "0"},
        },
    }
    sse_headers = {**headers, "Accept": "application/json, text/event-stream"}
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/servers/{server_id}/mcp",
            json=init_body,
            headers=sse_headers,
            timeout=10,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        return None
    # Fire-and-forget initialized notification — gateway returns 202 and
    # we don't need the body. A failure here would surface on the next
    # tools/call as a session error, so we let that path handle it.
    try:
        requests.post(
            f"{GATEWAY_URL}/servers/{server_id}/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**sse_headers, "Mcp-Session-Id": session_id},
            timeout=5,
        )
    except requests.RequestException:
        pass
    return session_id


def _send_tool_burst(server_id: str, tool_name: str, count: int) -> dict:
    """Fire ``count`` JSON-RPC tool calls via ``/servers/<id>/mcp`` over a
    single MCP session and tally allowed / rate-limited / errors.

    Uses the per-server MCP route, not the session-less ``/rpc``: per-tenant
    plugin bindings are scoped (team, server, tool) and only the session-aware
    route carries the ``server_id`` context the plugin manager needs to
    resolve binding overrides at request time.

    The MCP initialize + initialized handshake runs once; the resulting
    session id is reused for all ``count`` tool calls. Burst counters
    accumulate against a single user identity so per-user rate limits
    accumulate the way bindings expect.
    """
    counters = {"allowed": 0, "rate_limited": 0, "errors": 0, "total": count}
    headers = _fresh_headers()

    session_id = _mcp_initialize_session(server_id, headers)
    if session_id is None:
        counters["errors"] = count
        return counters

    call_headers = {
        **headers,
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    }

    for i in range(count):
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": (
                    {"message": f"binding-test-{i}"} if "echo" in tool_name else {}
                ),
            },
        }
        try:
            resp = requests.post(
                f"{GATEWAY_URL}/servers/{server_id}/mcp",
                json=payload,
                headers=call_headers,
                timeout=15,
            )
            if resp.status_code == 429:
                counters["rate_limited"] += 1
                continue
            if resp.status_code != 200:
                counters["errors"] += 1
                continue

            data = resp.json()
            result = data.get("result", {})
            if result.get("isError"):
                content = result.get("content", [])
                text = content[0].get("text", "") if content else ""
                if "rate" in text.lower() or "limit" in text.lower():
                    counters["rate_limited"] += 1
                else:
                    counters["errors"] += 1
            else:
                counters["allowed"] += 1
        except requests.RequestException:
            counters["errors"] += 1

    return counters


# ---------------------------------------------------------------------------
# Skip-guards
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server_and_tool():
    """Auto-detect server/tool once for the module."""
    return _auto_detect_server_and_tool()


@pytest.fixture(scope="module")
def team_id(server_and_tool):
    """Create (or reuse via $RATE_LIMITER_TEST_TEAM_ID) a team_id for the
    module, stamp it onto the test tool's row so the plugin manager
    actually resolves bindings against it, and tear both down at the end.

    The stamp is the load-bearing piece: bindings are scoped per
    (team, tool, plugin) and ``tool_service.invoke_tool`` reads
    ``tool.team_id`` (not the calling user's team) when constructing
    the plugin context_id. Tools registered by the docker-compose
    bootstrap have ``team_id = NULL`` so the binding lookup is skipped
    entirely. See ``_stamp_tool_team_id`` for the why.
    """
    _, tool_name = server_and_tool
    tid = _create_test_team()
    tool_id = _resolve_tool_id(tool_name)
    prev_team_id = _stamp_tool_team_id(tool_id, tid)
    try:
        yield tid
    finally:
        _restore_tool_team_id(tool_id, prev_team_id)
        _delete_test_team(tid)


@pytest.fixture
def cleanup_bindings():
    """Track + clean up bindings by reference_id at the end of each test."""
    created: list[str] = []
    yield created
    for ref_id in created:
        _delete_binding_by_reference(ref_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRateLimiterBindingApiEnforcesLimits:
    """A rate-limiter binding configured through the bindings API enforces
    its limits at tool-dispatch time."""

    def test_binding_with_tight_user_limit_blocks_burst(
        self, server_and_tool, team_id, cleanup_bindings
    ):
        """A binding with ``by_user: 5/s`` rate-limits a 15-request burst.

        Asserts:
          - At least one request is rate-limited (proves the binding's
            tighter limit is being applied — shipped config alone is 30/m
            and would not block a 15-request burst).
          - At least one request is allowed (proves the binding is not
            outright failing the plugin and dropping every request).
          - No transport / MCP errors that aren't rate-limit signals.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-test-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config={
                "algorithm": "fixed_window",
                "backend": "redis",
                "by_user": f"{BURST_LIMIT_PER_SEC}/s",
                "by_tenant": None,
                "by_tool": {},
                # redis_url + redis_key_prefix intentionally omitted — see the
                # `_binding_config` docstring below: testing whether dropping
                # gateway-scoped keys lets the per-tenant overrides propagate.
                "fail_mode": "open",
            },
        )

        # Wait for binding propagation — invalidate-and-broadcast plus any
        # downstream cache TTLs.
        time.sleep(PROPAGATION_WAIT)

        result = _send_tool_burst(server_id, tool_name, BURST_SIZE)

        assert result["rate_limited"] > 0, (
            f"Binding configures by_user: {BURST_LIMIT_PER_SEC}/s and a burst of "
            f"{BURST_SIZE} requests should exceed it, but no requests were "
            f"rate-limited. Got: {result}"
        )
        assert result["allowed"] >= 1, (
            f"At least the first few requests should be allowed before the "
            f"limit kicks in. Got: {result}"
        )
        assert result["errors"] == 0, (
            f"Non-rate-limit errors indicate a setup or transport problem, "
            f"not enforcement behaviour. Got: {result}"
        )


class TestRateLimiterBindingModeAndLifecycle:
    """The binding's ``mode`` field and lifecycle operations (upsert, delete)
    propagate to the gateway plugin manager and change tool-dispatch behaviour.

    Shares the same burst shape as the enforcement test above so the contrast
    is unambiguous: a 15-request burst against a 5/s limit that *would* block
    in enforce mode must NOT block in disabled / permissive / post-delete
    states.
    """

    @staticmethod
    def _binding_config(ref_id: str) -> dict:
        """Return the standard rate-limiter config used across these tests.

        Probe for #4665: gateway-scoped keys (``redis_url``,
        ``redis_key_prefix``) intentionally omitted from the binding payload.
        Both flow from the static ``plugins/config.yaml``. If the binding's
        per-tenant ``by_user`` reaches the runtime now, it's evidence that
        sending gateway-scoped keys in the binding's config dict was poisoning
        the per-tenant merge for ``RateLimiterPlugin``.
        """
        return {
            "algorithm": "fixed_window",
            "backend": "redis",
            "by_user": f"{BURST_LIMIT_PER_SEC}/s",
            "by_tenant": None,
            "by_tool": {},
            "fail_mode": "open",
        }

    def test_disabled_mode_allows_burst_through(
        self, server_and_tool, team_id, cleanup_bindings
    ):
        """A binding with ``mode: disabled`` does not enforce its limit.

        Same tight 5/s by_user limit as the enforce test; with mode=disabled
        the plugin's hook should short-circuit and let the full burst through.
        Proves the binding-payload ``mode`` field reaches the plugin manager
        and is honoured at dispatch.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-disabled-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="disabled",
            binding_reference_id=ref_id,
            config=self._binding_config(ref_id),
        )
        time.sleep(PROPAGATION_WAIT)

        result = _send_tool_burst(server_id, tool_name, BURST_SIZE)

        assert result["rate_limited"] == 0, (
            f"mode=disabled must not enforce — no requests should have been "
            f"rate-limited, got: {result}"
        )
        assert result["allowed"] == BURST_SIZE, (
            f"All {BURST_SIZE} requests should pass when the binding is "
            f"disabled. Got: {result}"
        )
        assert result["errors"] == 0, f"Unexpected transport errors: {result}"

    def test_upsert_from_enforce_to_disabled_stops_blocking(
        self, server_and_tool, team_id, cleanup_bindings
    ):
        """Upserting an existing binding from ``enforce`` to ``disabled``
        propagates to the plugin manager and stops further blocking.

        Sequence:
          1. POST enforce binding, burst → some blocked (sanity).
          2. POST same triple with mode=disabled (upsert).
          3. Burst again → none blocked.

        Asserts the upsert path triggers a manager rebuild and the new mode
        actually takes effect — not just that the row was updated in the DB.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-upsert-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        # Phase 1 — enforce.
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config=self._binding_config(ref_id),
        )
        time.sleep(PROPAGATION_WAIT)

        before = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert before["rate_limited"] > 0, (
            f"Pre-upsert sanity: enforce binding should rate-limit some of a "
            f"{BURST_SIZE}-request burst against {BURST_LIMIT_PER_SEC}/s. "
            f"Got: {before}"
        )

        # Phase 2 — upsert to disabled (same team_id + tool_name + plugin_id).
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="disabled",
            binding_reference_id=ref_id,
            config=self._binding_config(ref_id),
        )
        time.sleep(PROPAGATION_WAIT)

        after = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert after["rate_limited"] == 0, (
            f"After upserting to disabled, no requests should be rate-limited. "
            f"Before: {before}; after: {after}"
        )
        assert after["allowed"] == BURST_SIZE, (
            f"All {BURST_SIZE} requests should pass after upsert to disabled. "
            f"Before: {before}; after: {after}"
        )

    def test_delete_binding_restores_baseline_dispatch(
        self, server_and_tool, team_id
    ):
        """Deleting a binding restores baseline (no per-binding enforcement).

        Sequence:
          1. POST enforce binding, burst → some blocked (sanity).
          2. DELETE the binding by reference_id.
          3. Burst again → none blocked by the binding's tighter limit.

        Note: the gateway-wide rate-limiter plugin (configured at ~30/m) is
        loose enough that a single 15-request burst won't trip it within the
        post-delete window. If the global default is tightened in future, this
        test may need a larger BURST_SIZE or to skip the post-delete burst.

        This test does NOT use the cleanup_bindings fixture — the binding is
        deleted as part of the test itself; the fixture would just no-op on
        a missing reference_id but it would also mask a real test failure if
        the in-test delete silently failed.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-delete-{uuid.uuid4().hex[:8]}"

        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config=self._binding_config(ref_id),
        )
        time.sleep(PROPAGATION_WAIT)

        before = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert before["rate_limited"] > 0, (
            f"Pre-delete sanity: enforce binding should block some of a "
            f"{BURST_SIZE}-burst. Got: {before}"
        )

        # In-test deletion (not via cleanup fixture — see docstring).
        resp = requests.delete(
            f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
            params={"binding_reference_id": ref_id},
            headers=_fresh_headers(),
            timeout=10,
        )
        assert resp.status_code in (200, 204), (
            f"DELETE by reference_id failed: {resp.status_code} {resp.text[:200]}"
        )
        time.sleep(PROPAGATION_WAIT)

        after = _send_tool_burst(server_id, tool_name, BURST_SIZE)
        assert after["rate_limited"] == 0, (
            f"After delete, the binding's tighter limit should no longer "
            f"apply. Before: {before}; after: {after}"
        )
        assert after["errors"] == 0, (
            f"Unexpected transport errors after delete: {after}"
        )
