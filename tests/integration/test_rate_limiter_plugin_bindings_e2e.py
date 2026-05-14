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
#
# Default matches the container name produced by ``docker compose up`` from the
# repo root (project name = ``mcp-context-forge``). Override via env var if
# you bring the stack up under a different project name (e.g.
# ``docker compose -p <name> up`` → set RATE_LIMITER_TEST_PG_CONTAINER=<name>-postgres-1).
PG_CONTAINER = os.environ.get(
    "RATE_LIMITER_TEST_PG_CONTAINER", "mcp-context-forge-postgres-1"
)
PG_USER = os.environ.get("RATE_LIMITER_TEST_PG_USER", "postgres")
PG_DATABASE = os.environ.get("RATE_LIMITER_TEST_PG_DATABASE", "mcp")

# Plugin under test (used by the inspection-friendly lifecycle test).
PLUGIN_NAME = "RateLimiterPlugin"

PROPAGATION_WAIT = int(
    os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS))
)


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


def _get_admin_plugin_state(plugin_name: str) -> dict:
    """Return the loaded plugin's runtime state from ``GET /admin/plugins``.

    The ``mode`` and ``config_summary`` fields here reflect whatever the
    gateway has currently mounted in memory for this plugin — i.e., the
    static ``plugins/config.yaml`` overlaid with any Redis-persisted
    ``plugin:<name>:mode`` override. This is the right baseline to compare
    binding behaviour against.
    """
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/admin/plugins", headers=headers, timeout=10)
    resp.raise_for_status()
    plugins = resp.json().get("plugins", [])
    for p in plugins:
        if p.get("name") == plugin_name:
            return p
    pytest.skip(f"Plugin {plugin_name!r} not present in /admin/plugins listing")


def _get_binding_via_api(binding_reference_id: str) -> dict | None:
    """Fetch a binding by ``binding_reference_id`` via the gateway API.

    Returns the first binding row with the given reference id, or ``None``
    if not found. Used to confirm the binding actually persisted on the
    write path before any tool calls run.
    """
    headers = _fresh_headers()
    resp = requests.get(
        f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
        params={"binding_reference_id": binding_reference_id},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    bindings = body.get("bindings", []) if isinstance(body, dict) else body
    return bindings[0] if bindings else None


def _psql_get_binding_config(binding_reference_id: str) -> dict | None:
    """Belt-and-braces: read the ``config`` JSON column directly from Postgres.

    Cross-checks that the binding API write path persisted to the right
    place. Returns the parsed dict, or ``None`` if the row isn't found.
    Skips the test if the postgres container isn't reachable.
    """
    sql = (
        "SELECT config::text FROM tool_plugin_bindings "
        f"WHERE binding_reference_id = '{binding_reference_id}';"
    )
    cmd = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-tAc", sql,
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(
            f"psql cross-check unavailable ({type(exc).__name__}: {exc})"
        )
    if not out:
        return None
    # JSON column comes back as a string from -tAc; parse it
    import json  # noqa: PLC0415  - local import to keep top-of-file imports clean
    return json.loads(out)


def _redis_rl_keys() -> list[tuple[str, str, str]]:
    """Return rate-limiter keys currently in Redis as ``(key, value, ttl)`` tuples.

    Default container name matches ``docker compose up`` from the repo root
    (project name = ``mcp-context-forge``). Override via REDIS_CONTAINER_NAME
    if you use a custom project name (e.g. ``docker compose -p <name> up``).
    """
    container = os.environ.get("REDIS_CONTAINER_NAME", "mcp-context-forge-redis-1")
    try:
        keys_out = subprocess.run(
            ["docker", "exec", container, "redis-cli", "--scan", "--pattern", "rl:*"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []
    rows: list[tuple[str, str, str]] = []
    for k in (line.strip() for line in keys_out.splitlines() if line.strip()):
        try:
            v = subprocess.run(
                ["docker", "exec", container, "redis-cli", "GET", k],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            t = subprocess.run(
                ["docker", "exec", container, "redis-cli", "TTL", k],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            v = "?"
            t = "?"
        rows.append((k, v, t))
    return rows


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

    @pytest.mark.slow
    def test_binding_full_lifecycle_inspectable(
        self, server_and_tool, team_id, cleanup_bindings, capsys
    ):
        """End-to-end binding-flow walkthrough with deliberate inspection pauses.

        Designed for manual eyeballing alongside Redis Insight, not for CI.
        Run with ``-s`` to see the printed inspection pointers in real time::

            pytest tests/integration/test_rate_limiter_plugin_bindings_e2e.py \\
                ::TestRateLimiterBindingApiEnforcesLimits \\
                ::test_binding_full_lifecycle_inspectable \\
                -v -s --with-integration -m slow

        Walks through every layer of the binding contract:

        1. Capture baseline runtime config from ``GET /admin/plugins/...``
           (the static YAML's view, before any binding is in play).
        2. POST a binding with deliberately uncommon, distinct values for all
           three dimensions (``by_user: "7/m"``, ``by_tenant: "9/m"``,
           ``by_tool: {<tool>: "11/m"}``) so each value is recognisable in API
           responses, DB rows, and Redis.
        3. Verify the binding row genuinely landed in Postgres — both via the
           gateway API and via a direct ``docker exec psql`` cross-check.
        4. Sleep for inspection so the runner can refresh Redis Insight and
           confirm no ``rl:*`` keys exist yet.
        5. Burst a small number of tool calls.
        6. Dump Redis state, sleep again so the runner can compare counter
           values to the static-vs-binding signature.
        7. Assert the counter reflects the *binding's* tighter limit, not
           the static config's.

        Distinguishing binding-from-static signal:

          - The binding row in Postgres carries the binding's exact values
            (verified in Phase 2 — API + psql cross-check).
          - At runtime, all three dimension counter keys appear in Redis
            (`:user:`, `:tenant:`, `:tool:`), proving the multi-dim merged
            config reached the plugin.
          - Counter values (~75 each in a 5-call burst with amplification)
            don't directly distinguish 7 vs 30 because both limits get
            exceeded by amplification — the DB cross-check is the cleaner
            signal that the binding's specific values are what's stored.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-inspect-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        # Deliberately uncommon, distinct values for each dimension so each is
        # easy to spot in API responses, DB rows, and Redis Insight.
        binding_by_user = "7/m"
        binding_by_tenant = "9/m"
        binding_by_tool_limit = "11/m"
        # Inspection pauses are tuned for human reaction time, not CI speed.
        baseline_pause = 5
        post_propagation_pause = 10  # on top of PROPAGATION_WAIT
        post_burst_pause = 30
        # capsys lets us flush prints even with pytest output capture (use -s
        # to see them in real time as the test executes).

        def _say(msg: str) -> None:
            with capsys.disabled():
                print(f"\n[inspect] {msg}")

        # ---- Phase 0: baseline -----------------------------------------------
        _say("Phase 0 — capturing baseline plugin state from /admin/plugins")
        baseline = _get_admin_plugin_state(PLUGIN_NAME)
        baseline_mode = baseline.get("mode")
        baseline_summary = baseline.get("config_summary") or {}
        baseline_by_user = baseline_summary.get("by_user")
        _say(f"  baseline mode = {baseline_mode!r}")
        _say(f"  baseline by_user (static) = {baseline_by_user!r}")
        _say(f"  → if you peek at Redis Insight now, there should be no rl:* keys yet")
        time.sleep(baseline_pause)

        # ---- Phase 1: POST binding ------------------------------------------
        _say(
            f"Phase 1 — POSTing binding with by_user={binding_by_user!r}, "
            f"by_tenant={binding_by_tenant!r}, "
            f"by_tool={{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config={
                "algorithm": "fixed_window",
                "backend": "redis",
                "by_user": binding_by_user,
                "by_tenant": binding_by_tenant,
                "by_tool": {tool_name: binding_by_tool_limit},
                # redis_url + redis_key_prefix omitted — gateway-scoped keys,
                # leaving them out lets the binding's caller-scoped overrides
                # propagate cleanly (see #4665 for why).
                "fail_mode": "open",
            },
        )
        _say(f"  binding_reference_id = {ref_id}")

        # ---- Phase 2: persistence cross-check --------------------------------
        _say("Phase 2 — verifying the binding actually persisted (all 3 dimensions)")
        api_binding = _get_binding_via_api(ref_id)
        assert api_binding is not None, f"binding {ref_id} not returned by API"
        api_config = api_binding.get("config") or {}
        api_by_user = api_config.get("by_user")
        api_by_tenant = api_config.get("by_tenant")
        api_by_tool = api_config.get("by_tool")
        assert api_by_user == binding_by_user, (
            f"API returned binding with by_user={api_by_user!r}, expected {binding_by_user!r}"
        )
        assert api_by_tenant == binding_by_tenant, (
            f"API returned binding with by_tenant={api_by_tenant!r}, expected {binding_by_tenant!r}"
        )
        assert isinstance(api_by_tool, dict) and api_by_tool.get(tool_name) == binding_by_tool_limit, (
            f"API returned binding with by_tool={api_by_tool!r}, "
            f"expected {{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _say(f"  ✓ API confirms by_user={api_by_user!r}, by_tenant={api_by_tenant!r}, by_tool={api_by_tool!r}")

        psql_config = _psql_get_binding_config(ref_id)
        assert psql_config is not None, f"binding {ref_id} not found in Postgres"
        psql_by_user = psql_config.get("by_user")
        psql_by_tenant = psql_config.get("by_tenant")
        psql_by_tool = psql_config.get("by_tool")
        assert psql_by_user == binding_by_user, (
            f"Postgres has by_user={psql_by_user!r}, expected {binding_by_user!r}"
        )
        assert psql_by_tenant == binding_by_tenant, (
            f"Postgres has by_tenant={psql_by_tenant!r}, expected {binding_by_tenant!r}"
        )
        assert isinstance(psql_by_tool, dict) and psql_by_tool.get(tool_name) == binding_by_tool_limit, (
            f"Postgres has by_tool={psql_by_tool!r}, "
            f"expected {{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _say(f"  ✓ Postgres confirms by_user={psql_by_user!r}, by_tenant={psql_by_tenant!r}, by_tool={psql_by_tool!r}")
        _say(f"  ✓ binding stored cleanly in DB at row keyed by binding_reference_id={ref_id}")

        # ---- Phase 3: pause for per-tenant manager rebuild + human refresh --
        _say(f"Phase 3 — sleeping {PROPAGATION_WAIT + post_propagation_pause}s")
        _say("  → covers the per-tenant plugin manager rebuild")
        _say("  → also gives you a window to peek at Redis Insight (still no rl:* keys)")
        time.sleep(PROPAGATION_WAIT + post_propagation_pause)

        # ---- Phase 4: paced burst with per-call observation ----------------
        burst_size = 5
        pace_between_calls = 3
        _say(
            f"Phase 4 — pacing {burst_size} tool calls {pace_between_calls}s apart "
            f"so the counter increments are observable in Redis Insight"
        )
        _say(
            "  → watch the rl:<tenant>:user:admin@example.com:60 counter "
            "climb with each call (refresh between calls)"
        )

        # Single MCP session for the full burst — keeps tenant_id resolution stable.
        session_id = _mcp_initialize_session(server_id, _fresh_headers())
        assert session_id is not None, (
            "MCP initialize handshake failed — can't drive the burst without a session id"
        )
        call_headers = {
            **_fresh_headers(),
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        }

        per_call_outcomes: list[str] = []
        allowed = rate_limited = errors = 0
        for i in range(burst_size):
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": (
                        {"message": f"inspect-{i}"} if "echo" in tool_name else {}
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
                    outcome = "BLOCKED (HTTP 429)"
                    rate_limited += 1
                elif resp.status_code != 200:
                    outcome = f"ERROR (HTTP {resp.status_code})"
                    errors += 1
                else:
                    body = resp.json()
                    err = body.get("error")
                    result_obj = body.get("result") or {}
                    if err:
                        msg = str(err.get("message", "")).lower()
                        if "rate" in msg or "limit" in msg:
                            outcome = "BLOCKED (JSON-RPC rate-limit error)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR ({err.get('message', 'unknown')})"
                            errors += 1
                    elif result_obj.get("isError"):
                        content = result_obj.get("content", [])
                        text = content[0].get("text", "") if content else ""
                        if "rate" in text.lower() or "limit" in text.lower():
                            outcome = "BLOCKED (MCP isError, rate-limit)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR (MCP isError: {text[:50]})"
                            errors += 1
                    else:
                        outcome = "ALLOWED"
                        allowed += 1
            except requests.RequestException as exc:
                outcome = f"ERROR (transport: {exc})"
                errors += 1
            _say(f"  call {i + 1}/{burst_size}: {outcome}")
            per_call_outcomes.append(outcome)
            if i < burst_size - 1:
                time.sleep(pace_between_calls)

        result = {
            "allowed": allowed,
            "rate_limited": rate_limited,
            "errors": errors,
            "total": burst_size,
        }
        _say(
            f"  summary: allowed={allowed} rate_limited={rate_limited} errors={errors}"
        )

        # ---- Phase 5: inspect Redis -----------------------------------------
        _say("Phase 5 — current rl:* keys in Redis (these are what the plugin actually wrote)")
        rl_keys = _redis_rl_keys()
        if not rl_keys:
            _say("  (no rl:* keys found — counters may have already expired or the plugin didn't run)")
        else:
            for k, v, t in rl_keys:
                _say(f"  {k} = {v}  (ttl={t}s)")

        _say(
            f"  → refresh Redis Insight in the next ~{post_burst_pause}s; "
            "the keys above should be visible there"
        )
        _say(
            "  → expected counter ranges:\n"
            "      binding's 7/m active   → counter ~5-15  (small)\n"
            "      static's 30/m active   → counter ~30-150 (much larger)"
        )
        time.sleep(post_burst_pause)

        # ---- Phase 6: behavioural assertion ---------------------------------
        _say("Phase 6 — asserting the enforcement transition + multi-dim tracking")
        assert result["errors"] == 0, (
            f"Non-rate-limit errors indicate a setup/transport problem: {result}"
        )
        # Enforcement signal: at least one call was blocked. A "first call
        # allowed, later blocked" transition is observable when amplification
        # is mild, but with the binding's tight 7/m limit and tool-path
        # amplification varying between runs (~5x – 20x ticks per call), the
        # very first call sometimes already trips. Both shapes are valid
        # enforcement; we only insist on at least one block.
        assert result["rate_limited"] >= 1, (
            f"Expected at least one call to be blocked by the binding's tight "
            f"per-dimension limits. Got: {result}"
        )
        if result["allowed"] >= 1:
            _say(
                f"  ✓ visible enforcement transition: "
                f"{result['allowed']} allowed → {result['rate_limited']} blocked"
            )
        else:
            _say(
                f"  ✓ enforcement was strict from the first call: "
                f"all {result['rate_limited']} blocked (amplification high this run)"
            )

        # The binding configures all three dimensions with non-null values, so
        # the merged runtime config should track all three. We verify each one
        # has a counter key in Redis. The values themselves don't directly
        # distinguish 7-vs-30 (amplification dominates), but the *presence* of
        # all three dimension keys confirms multi-dim is engaged.
        rl_keys_now = _redis_rl_keys()
        key_strs = [k for (k, _, _) in rl_keys_now]
        user_keys = [k for k in key_strs if ":user:" in k]
        tenant_keys = [k for k in key_strs if ":tenant:" in k]
        tool_keys = [k for k in key_strs if f":tool:{tool_name}:" in k]

        _say(
            f"  dimension keys observed: "
            f"user={len(user_keys)}, tenant={len(tenant_keys)}, "
            f"tool({tool_name})={len(tool_keys)}"
        )

        assert len(user_keys) >= 1, (
            "by_user counter is missing — the binding's by_user override "
            "didn't engage at runtime."
        )
        assert len(tenant_keys) >= 1, (
            "by_tenant counter is missing — the binding's by_tenant override "
            "didn't engage at runtime."
        )
        assert len(tool_keys) >= 1, (
            f"by_tool counter for {tool_name!r} is missing — the binding's "
            f"by_tool override didn't engage at runtime."
        )

        _say("  ✓ all three dimension keys present in Redis")
        _say("  ✓ binding's multi-dimensional config genuinely reached the runtime")
        _say(
            "  ✓ DB cross-check (Phase 2) confirms the binding row carries the binding's "
            "exact values (7/m, 9/m, 11/m), not the static defaults"
        )

        _say("Phase 7 — cleanup runs via the cleanup_bindings fixture on test exit")


class TestRateLimiterBindingModeAndLifecycle:
    """The binding's lifecycle operations (upsert, delete) propagate to the
    gateway plugin manager and change tool-dispatch behaviour."""

    @pytest.mark.slow
    def test_upsert_binding_full_lifecycle_inspectable(
        self, server_and_tool, team_id, cleanup_bindings, capsys
    ):
        """End-to-end binding-upsert walkthrough mirroring the persistence test.

        Companion to
        ``TestRateLimiterBindingApiEnforcesLimits.test_binding_full_lifecycle_inspectable``
        (POST happy path) and
        ``test_delete_binding_full_lifecycle_inspectable``
        (DELETE lifecycle): this one verifies the UPSERT path. Specifically,
        a second POST with the same ``(team_id, tool_name, plugin_id)`` triple
        UPDATES the existing row in place rather than failing with a
        duplicate-key error or creating a second row, AND the new mode
        propagates past the DB into the plugin manager so it actually
        changes dispatch behaviour. Run with ``-s`` to see the inspection
        pointers in real time::

            pytest tests/integration/test_rate_limiter_plugin_bindings_e2e.py \\
                ::TestRateLimiterBindingModeAndLifecycle \\
                ::test_upsert_binding_full_lifecycle_inspectable \\
                -v -s --with-integration -m slow

        Phases:
          0. Baseline plugin state from ``/admin/plugins``.
          1. POST binding with ``mode: enforce`` + multi-dim (7/m, 9/m, 11/m).
          2. Verify persisted via API + Postgres; capture API mode field.
          3. Propagation wait — covers the per-tenant plugin manager rebuild.
          4. Paced 5-call burst — assert ``rate_limited >= 1`` (enforce live).
          5. Inspect Redis — all three dimension keys must be present.
          6. UPSERT: POST same triple with ``mode: disabled`` (config preserved).
          7. Verify via API that one row still exists for this
             ``binding_reference_id`` with ``mode`` flipped vs phase 2;
             Postgres confirms the config dict is unchanged.
          8. Propagation wait — covers the per-tenant manager rebuild after
             the upsert.
          9. Paced 5-call burst — assert ``rate_limited == 0`` and
             ``allowed == burst_size``.

        Why ``rate_limited == 0`` is reliable here despite session-affinity
        amplification: ``mode: disabled`` causes the cpex framework to skip
        the plugin's hooks entirely for this tenant manager. No Redis writes
        happen and no thresholds are evaluated, so amplification is moot.
        Contrast with the delete-binding test, where DELETE falls back to
        the gateway-wide static config (still enforcing at 30/m), making a
        post-delete behavioural assertion unsafe.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-upsert-inspect-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        # Distinct multi-dim values so each is easy to spot in API responses,
        # DB rows, and Redis Insight.
        binding_by_user = "7/m"
        binding_by_tenant = "9/m"
        binding_by_tool_limit = "11/m"
        # Inspection pauses tuned for human reaction time, not CI speed.
        baseline_pause = 5
        post_propagation_pause = 10
        post_burst_pause = 30

        def _say(msg: str) -> None:
            with capsys.disabled():
                print(f"\n[inspect] {msg}")

        # Same multi-dim config used for both the initial POST and the
        # mode-flip upsert — only the mode field changes between the two.
        binding_config = {
            "algorithm": "fixed_window",
            "backend": "redis",
            "by_user": binding_by_user,
            "by_tenant": binding_by_tenant,
            "by_tool": {tool_name: binding_by_tool_limit},
            # redis_url + redis_key_prefix omitted — gateway-scoped keys
            # come from the static plugins/config.yaml, not the binding.
            "fail_mode": "open",
        }
        burst_size = 5
        pace_between_calls = 3

        def _paced_burst(phase_label: str) -> dict:
            """Run a paced burst over a fresh MCP session; tally outcomes."""
            session_id = _mcp_initialize_session(server_id, _fresh_headers())
            assert session_id is not None, (
                f"{phase_label}: MCP initialize failed — can't drive the burst"
            )
            call_headers = {
                **_fresh_headers(),
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            }
            allowed = rate_limited = errors = 0
            for i in range(burst_size):
                payload = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": (
                            {"message": f"upsert-{phase_label}-{i}"}
                            if "echo" in tool_name
                            else {}
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
                        outcome = "BLOCKED (HTTP 429)"
                        rate_limited += 1
                    elif resp.status_code != 200:
                        outcome = f"ERROR (HTTP {resp.status_code})"
                        errors += 1
                    else:
                        body = resp.json()
                        err = body.get("error")
                        result_obj = body.get("result") or {}
                        if err:
                            msg = str(err.get("message", "")).lower()
                            if "rate" in msg or "limit" in msg:
                                outcome = "BLOCKED (JSON-RPC rate-limit error)"
                                rate_limited += 1
                            else:
                                outcome = f"ERROR ({err.get('message', 'unknown')})"
                                errors += 1
                        elif result_obj.get("isError"):
                            content = result_obj.get("content", [])
                            text = content[0].get("text", "") if content else ""
                            if "rate" in text.lower() or "limit" in text.lower():
                                outcome = "BLOCKED (MCP isError, rate-limit)"
                                rate_limited += 1
                            else:
                                outcome = f"ERROR (MCP isError: {text[:50]})"
                                errors += 1
                        else:
                            outcome = "ALLOWED"
                            allowed += 1
                except requests.RequestException as exc:
                    outcome = f"ERROR (transport: {exc})"
                    errors += 1
                _say(f"  {phase_label} call {i + 1}/{burst_size}: {outcome}")
                if i < burst_size - 1:
                    time.sleep(pace_between_calls)
            return {
                "allowed": allowed,
                "rate_limited": rate_limited,
                "errors": errors,
                "total": burst_size,
            }

        # ---- Phase 0: baseline -----------------------------------------------
        _say("Phase 0 — capturing baseline plugin state from /admin/plugins")
        baseline = _get_admin_plugin_state(PLUGIN_NAME)
        baseline_mode = baseline.get("mode")
        _say(f"  baseline mode = {baseline_mode!r}")
        _say("  → no rl-binding-upsert-inspect-* row in tool_plugin_bindings yet")
        time.sleep(baseline_pause)

        # ---- Phase 1: POST enforce binding ----------------------------------
        _say(
            f"Phase 1 — POSTing binding (mode=enforce) with by_user={binding_by_user!r}, "
            f"by_tenant={binding_by_tenant!r}, "
            f"by_tool={{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config=binding_config,
        )
        _say(f"  binding_reference_id = {ref_id}")

        # ---- Phase 2: persistence cross-check (post-INSERT) -----------------
        _say("Phase 2 — verifying the enforce binding actually persisted")
        api_binding = _get_binding_via_api(ref_id)
        assert api_binding is not None, f"binding {ref_id} not returned by API"
        api_config = api_binding.get("config", {}) or {}
        assert api_config.get("by_user") == binding_by_user, (
            f"API has by_user={api_config.get('by_user')!r}, expected {binding_by_user!r}"
        )
        assert api_config.get("by_tenant") == binding_by_tenant, (
            f"API has by_tenant={api_config.get('by_tenant')!r}, expected {binding_by_tenant!r}"
        )
        assert api_config.get("by_tool", {}) == {tool_name: binding_by_tool_limit}, (
            f"API has by_tool={api_config.get('by_tool')!r}, "
            f"expected {{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        enforce_api_mode = api_binding.get("mode")
        _say(
            f"  ✓ API confirms binding row (mode={enforce_api_mode!r}, "
            f"by_user={api_config.get('by_user')!r})"
        )

        psql_config = _psql_get_binding_config(ref_id)
        assert psql_config is not None, f"binding {ref_id} not in Postgres"
        assert psql_config.get("by_user") == binding_by_user, (
            f"Postgres has by_user={psql_config.get('by_user')!r}, expected {binding_by_user!r}"
        )
        _say("  ✓ Postgres confirms config column persisted")

        # ---- Phase 3: propagation wait --------------------------------------
        _say(f"Phase 3 — sleeping {PROPAGATION_WAIT + post_propagation_pause}s")
        _say("  → covers the per-tenant plugin manager rebuild")
        time.sleep(PROPAGATION_WAIT + post_propagation_pause)

        # ---- Phase 4: paced enforce-burst -----------------------------------
        _say(
            f"Phase 4 — pacing {burst_size} tool calls {pace_between_calls}s apart "
            f"to confirm the enforce binding is live before we upsert it"
        )
        enforce_result = _paced_burst("enforce")
        _say(
            f"  summary: allowed={enforce_result['allowed']} "
            f"rate_limited={enforce_result['rate_limited']} "
            f"errors={enforce_result['errors']}"
        )
        assert enforce_result["errors"] == 0, (
            f"Non-rate-limit errors indicate a setup/transport problem: {enforce_result}"
        )
        assert enforce_result["rate_limited"] >= 1, (
            f"Expected at least one block under mode=enforce. Got: {enforce_result}"
        )

        # ---- Phase 5: inspect Redis -----------------------------------------
        _say("Phase 5 — inspecting Redis for binding-driven dimension keys")
        rl_keys = _redis_rl_keys()
        for k, v, t in rl_keys:
            _say(f"  {k} = {v}  (ttl={t}s)")
        key_strs = [k for (k, _, _) in rl_keys]
        user_keys = [k for k in key_strs if ":user:" in k]
        tenant_keys = [k for k in key_strs if ":tenant:" in k]
        tool_keys = [k for k in key_strs if f":tool:{tool_name}:" in k]
        _say(
            f"  dimension keys observed: "
            f"user={len(user_keys)}, tenant={len(tenant_keys)}, "
            f"tool({tool_name})={len(tool_keys)}"
        )
        assert len(user_keys) >= 1, (
            "by_user counter is missing — the enforce binding's by_user "
            "override didn't engage at runtime."
        )
        assert len(tenant_keys) >= 1, "by_tenant counter is missing"
        assert len(tool_keys) >= 1, (
            f"by_tool counter for {tool_name!r} is missing"
        )
        _say("  ✓ all three dimension keys present in Redis")

        # ---- Phase 6: UPSERT to mode=disabled -------------------------------
        _say(
            f"Phase 6 — UPSERTing same (team={team_id!r}, tool={tool_name!r}, "
            f"plugin=RateLimiterPlugin) triple with mode=disabled"
        )
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="disabled",
            binding_reference_id=ref_id,
            config=binding_config,  # same multi-dim config — only mode changes
        )

        # ---- Phase 7: persistence cross-check (post-UPSERT) -----------------
        _say("Phase 7 — verifying the upsert updated the existing row in place")
        api_after = _get_binding_via_api(ref_id)
        assert api_after is not None, (
            f"binding {ref_id} disappeared after upsert — UPSERT looks like "
            f"DELETE-then-INSERT-failed, not in-place UPDATE"
        )
        disabled_api_mode = api_after.get("mode")
        assert disabled_api_mode != enforce_api_mode, (
            f"Upsert should have flipped the mode field; both phase 2 and "
            f"phase 7 reported mode={disabled_api_mode!r}"
        )
        _say(
            f"  ✓ API confirms mode flipped: enforce={enforce_api_mode!r} "
            f"→ disabled={disabled_api_mode!r}"
        )
        api_after_config = api_after.get("config", {}) or {}
        assert api_after_config.get("by_user") == binding_by_user, (
            f"by_user changed across upsert (was {binding_by_user!r}, "
            f"now {api_after_config.get('by_user')!r})"
        )
        assert api_after_config.get("by_tenant") == binding_by_tenant, (
            f"by_tenant changed across upsert (was {binding_by_tenant!r}, "
            f"now {api_after_config.get('by_tenant')!r})"
        )
        assert api_after_config.get("by_tool", {}) == {tool_name: binding_by_tool_limit}, (
            f"by_tool changed across upsert"
        )
        _say("  ✓ API confirms config dict preserved across upsert (only mode flipped)")

        psql_after_config = _psql_get_binding_config(ref_id)
        assert psql_after_config is not None, (
            f"binding {ref_id} disappeared from Postgres after upsert"
        )
        assert psql_after_config == psql_config, (
            f"Postgres config column changed across upsert. "
            f"before={psql_config}, after={psql_after_config}"
        )
        _say("  ✓ Postgres confirms config column unchanged across upsert")

        # ---- Phase 8: propagation wait --------------------------------------
        _say(f"Phase 8 — sleeping {PROPAGATION_WAIT + post_propagation_pause}s")
        _say("  → covers the per-tenant manager rebuild after the mode flip")
        time.sleep(PROPAGATION_WAIT + post_propagation_pause)

        # ---- Phase 9: paced disabled-burst ----------------------------------
        _say(
            f"Phase 9 — pacing {burst_size} tool calls {pace_between_calls}s apart "
            f"to confirm mode=disabled propagated past the DB into the plugin "
            f"manager (and skips the plugin entirely, including gateway-wide limits)"
        )
        disabled_result = _paced_burst("disabled")
        _say(
            f"  summary: allowed={disabled_result['allowed']} "
            f"rate_limited={disabled_result['rate_limited']} "
            f"errors={disabled_result['errors']}"
        )
        assert disabled_result["errors"] == 0, (
            f"Non-rate-limit errors after upsert: {disabled_result}"
        )
        assert disabled_result["rate_limited"] == 0, (
            f"After upsert to mode=disabled, no calls should be blocked. "
            f"Got: {disabled_result}"
        )
        assert disabled_result["allowed"] == burst_size, (
            f"After upsert to mode=disabled, all {burst_size} calls should "
            f"pass. Got: {disabled_result}"
        )
        _say(
            f"  ✓ {burst_size}/{burst_size} calls allowed after upsert — the "
            f"new mode reached the plugin manager and skipped dispatch entirely"
        )
        _say(
            f"  → refresh Redis Insight in the next ~{post_burst_pause}s; "
            "no new rl:* keys should appear from this disabled-binding burst"
        )
        time.sleep(post_burst_pause)

    @pytest.mark.slow
    def test_delete_binding_full_lifecycle_inspectable(
        self, server_and_tool, team_id, capsys
    ):
        """End-to-end binding-delete walkthrough mirroring the persistence test.

        Companion to
        ``TestRateLimiterBindingApiEnforcesLimits.test_binding_full_lifecycle_inspectable``:
        that test verifies the binding's multi-dim config reaches the runtime;
        this one verifies the deletion path removes the binding from every
        write surface it landed on (API + Postgres). Run with ``-s`` to see
        the printed inspection pointers in real time::

            pytest tests/integration/test_rate_limiter_plugin_bindings_e2e.py \\
                ::TestRateLimiterBindingModeAndLifecycle \\
                ::test_delete_binding_full_lifecycle_inspectable \\
                -v -s --with-integration -m slow

        Phases:
          0. Baseline plugin state from ``/admin/plugins``.
          1. POST a binding with distinct multi-dim values (7/m, 9/m, 11/m).
          2. Verify persisted via the bindings API and direct Postgres lookup.
          3. Propagation wait — covers the per-tenant plugin manager rebuild.
          4. Paced 5-call burst — assert at least one block, confirming the
             binding is live at dispatch.
          5. Inspect Redis — all three dimension keys must be present.
          6. DELETE the binding via API; assert HTTP 200/204.
          7. Verify the binding is GONE from API + Postgres (mirror of phase 2).

        This test does NOT use the cleanup_bindings fixture — the binding is
        deleted as part of the test itself; the fixture would just no-op on
        a missing reference_id but it would also mask a real test failure if
        the in-test delete silently failed.

        Why no post-delete behavioral burst: the gateway-wide RateLimiter at
        ``by_user: 30/m`` combined with session-affinity tool-path
        amplification (~24x ticks per user-level call) means a 15-call
        pre-delete burst saturates the per-user bucket, so any post-delete
        burst stays blocked by the gateway-wide limit (not the deleted
        binding). Verifying the deletion via the same API + DB write
        surfaces used in the persistence test (phase 2 there, phase 7 here)
        avoids that confound entirely while still asserting the contract
        that DELETE removes the binding from every place POST landed it.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-binding-delete-inspect-{uuid.uuid4().hex[:8]}"

        # Distinct multi-dim values so each is easy to spot in API responses,
        # DB rows, and Redis Insight.
        binding_by_user = "7/m"
        binding_by_tenant = "9/m"
        binding_by_tool_limit = "11/m"
        # Inspection pauses tuned for human reaction time, not CI speed.
        baseline_pause = 5
        post_propagation_pause = 10
        post_delete_pause = 30

        def _say(msg: str) -> None:
            with capsys.disabled():
                print(f"\n[inspect] {msg}")

        # ---- Phase 0: baseline -----------------------------------------------
        _say("Phase 0 — capturing baseline plugin state from /admin/plugins")
        baseline = _get_admin_plugin_state(PLUGIN_NAME)
        baseline_mode = baseline.get("mode")
        _say(f"  baseline mode = {baseline_mode!r}")
        _say(f"  → no rl-binding-delete-inspect-* row in tool_plugin_bindings yet")
        time.sleep(baseline_pause)

        # ---- Phase 1: POST binding ------------------------------------------
        _say(
            f"Phase 1 — POSTing binding with by_user={binding_by_user!r}, "
            f"by_tenant={binding_by_tenant!r}, "
            f"by_tool={{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config={
                "algorithm": "fixed_window",
                "backend": "redis",
                "by_user": binding_by_user,
                "by_tenant": binding_by_tenant,
                "by_tool": {tool_name: binding_by_tool_limit},
                # redis_url + redis_key_prefix omitted — gateway-scoped keys
                # come from the static plugins/config.yaml, not the binding.
                "fail_mode": "open",
            },
        )
        _say(f"  binding_reference_id = {ref_id}")

        # ---- Phase 2: persistence cross-check --------------------------------
        _say("Phase 2 — verifying the binding actually persisted (all 3 dimensions)")
        api_binding = _get_binding_via_api(ref_id)
        assert api_binding is not None, f"binding {ref_id} not returned by API"
        api_config = api_binding.get("config", {}) or {}
        api_by_user = api_config.get("by_user")
        api_by_tenant = api_config.get("by_tenant")
        api_by_tool = api_config.get("by_tool", {})
        assert api_by_user == binding_by_user, (
            f"API returned binding with by_user={api_by_user!r}, expected {binding_by_user!r}"
        )
        assert api_by_tenant == binding_by_tenant, (
            f"API returned binding with by_tenant={api_by_tenant!r}, expected {binding_by_tenant!r}"
        )
        assert api_by_tool == {tool_name: binding_by_tool_limit}, (
            f"API returned binding with by_tool={api_by_tool!r}, "
            f"expected {{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _say(f"  ✓ API confirms by_user={api_by_user!r}, by_tenant={api_by_tenant!r}, by_tool={api_by_tool!r}")

        psql_config = _psql_get_binding_config(ref_id)
        assert psql_config is not None, f"binding {ref_id} not in Postgres"
        psql_by_user = psql_config.get("by_user")
        psql_by_tenant = psql_config.get("by_tenant")
        psql_by_tool = psql_config.get("by_tool", {})
        assert psql_by_user == binding_by_user, (
            f"Postgres has by_user={psql_by_user!r}, expected {binding_by_user!r}"
        )
        assert psql_by_tenant == binding_by_tenant, (
            f"Postgres has by_tenant={psql_by_tenant!r}, expected {binding_by_tenant!r}"
        )
        assert psql_by_tool == {tool_name: binding_by_tool_limit}, (
            f"Postgres has by_tool={psql_by_tool!r}, "
            f"expected {{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        _say(f"  ✓ Postgres confirms by_user={psql_by_user!r}, by_tenant={psql_by_tenant!r}, by_tool={psql_by_tool!r}")

        # ---- Phase 3: propagation wait --------------------------------------
        _say(f"Phase 3 — sleeping {PROPAGATION_WAIT + post_propagation_pause}s")
        _say("  → covers the per-tenant plugin manager rebuild")
        _say("  → also gives you a window to peek at Redis Insight (still no rl:* keys)")
        time.sleep(PROPAGATION_WAIT + post_propagation_pause)

        # ---- Phase 4: paced burst with per-call observation ----------------
        burst_size = 5
        pace_between_calls = 3
        _say(
            f"Phase 4 — pacing {burst_size} tool calls {pace_between_calls}s apart "
            f"to confirm the binding is live before we delete it"
        )

        session_id = _mcp_initialize_session(server_id, _fresh_headers())
        assert session_id is not None, (
            "MCP initialize handshake failed — can't drive the burst without a session id"
        )
        call_headers = {
            **_fresh_headers(),
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        }

        allowed = rate_limited = errors = 0
        for i in range(burst_size):
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": (
                        {"message": f"delete-inspect-{i}"} if "echo" in tool_name else {}
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
                    outcome = "BLOCKED (HTTP 429)"
                    rate_limited += 1
                elif resp.status_code != 200:
                    outcome = f"ERROR (HTTP {resp.status_code})"
                    errors += 1
                else:
                    body = resp.json()
                    err = body.get("error")
                    result_obj = body.get("result") or {}
                    if err:
                        msg = str(err.get("message", "")).lower()
                        if "rate" in msg or "limit" in msg:
                            outcome = "BLOCKED (JSON-RPC rate-limit error)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR ({err.get('message', 'unknown')})"
                            errors += 1
                    elif result_obj.get("isError"):
                        content = result_obj.get("content", [])
                        text = content[0].get("text", "") if content else ""
                        if "rate" in text.lower() or "limit" in text.lower():
                            outcome = "BLOCKED (MCP isError, rate-limit)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR (MCP isError: {text[:50]})"
                            errors += 1
                    else:
                        outcome = "ALLOWED"
                        allowed += 1
            except requests.RequestException as exc:
                outcome = f"ERROR (transport: {exc})"
                errors += 1
            _say(f"  call {i + 1}/{burst_size}: {outcome}")
            if i < burst_size - 1:
                time.sleep(pace_between_calls)

        burst_result = {
            "allowed": allowed,
            "rate_limited": rate_limited,
            "errors": errors,
            "total": burst_size,
        }
        _say(
            f"  summary: allowed={allowed} rate_limited={rate_limited} errors={errors}"
        )
        assert burst_result["errors"] == 0, (
            f"Non-rate-limit errors indicate a setup/transport problem: {burst_result}"
        )
        assert burst_result["rate_limited"] >= 1, (
            f"Expected at least one block before deletion to confirm the "
            f"binding is live at dispatch. Got: {burst_result}"
        )

        # ---- Phase 5: inspect Redis -----------------------------------------
        _say("Phase 5 — inspecting Redis for binding-driven dimension keys")
        rl_keys = _redis_rl_keys()
        if not rl_keys:
            _say("  (no rl:* keys found — counters may have already expired)")
        else:
            for k, v, t in rl_keys:
                _say(f"  {k} = {v}  (ttl={t}s)")

        key_strs = [k for (k, _, _) in rl_keys]
        user_keys = [k for k in key_strs if ":user:" in k]
        tenant_keys = [k for k in key_strs if ":tenant:" in k]
        tool_keys = [k for k in key_strs if f":tool:{tool_name}:" in k]
        _say(
            f"  dimension keys observed: "
            f"user={len(user_keys)}, tenant={len(tenant_keys)}, "
            f"tool({tool_name})={len(tool_keys)}"
        )
        assert len(user_keys) >= 1, (
            "by_user counter is missing — the binding's by_user override "
            "didn't engage at runtime."
        )
        assert len(tenant_keys) >= 1, (
            "by_tenant counter is missing — the binding's by_tenant override "
            "didn't engage at runtime."
        )
        assert len(tool_keys) >= 1, (
            f"by_tool counter for {tool_name!r} is missing — the binding's "
            f"by_tool override didn't engage at runtime."
        )
        _say("  ✓ all three dimension keys present in Redis")

        # ---- Phase 6: DELETE binding ----------------------------------------
        _say(f"Phase 6 — DELETEing binding {ref_id}")
        resp = requests.delete(
            f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
            params={"binding_reference_id": ref_id},
            headers=_fresh_headers(),
            timeout=10,
        )
        assert resp.status_code in (200, 204), (
            f"DELETE by reference_id failed: {resp.status_code} {resp.text[:200]}"
        )
        _say(f"  ✓ DELETE returned HTTP {resp.status_code}")
        _say(f"  → sleeping {PROPAGATION_WAIT}s for the deletion to propagate")
        time.sleep(PROPAGATION_WAIT)

        # ---- Phase 7: deletion cross-check ----------------------------------
        _say("Phase 7 — verifying the binding is GONE from every write surface")
        api_after = _get_binding_via_api(ref_id)
        assert api_after is None, (
            f"binding {ref_id} still returned by API after delete: {api_after}"
        )
        _say("  ✓ API confirms binding is no longer present")

        psql_after = _psql_get_binding_config(ref_id)
        assert psql_after is None, (
            f"binding {ref_id} still in Postgres after delete: {psql_after}"
        )
        _say("  ✓ Postgres confirms binding row is gone")
        _say(
            "  ✓ delete-lifecycle: the binding was removed from both write "
            "surfaces it landed on"
        )

        _say(
            f"  → refresh Redis Insight in the next ~{post_delete_pause}s if you "
            "want to watch the existing rl:* counters expire naturally"
        )
        time.sleep(post_delete_pause)
