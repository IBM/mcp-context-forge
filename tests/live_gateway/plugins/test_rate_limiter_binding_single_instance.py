# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_rate_limiter_binding_single_instance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Single-instance baseline test for the rate-limiter binding lifecycle.

Companion to ``test_rate_limiter_bindings_lifecycle.py`` (the multi-instance
reproducer). This file verifies the binding flow against a single-process
gateway where there is no session-affinity amplification: 5 user-facing tool
calls produce exactly 5 plugin hook invocations, and the binding's per-user
limit is enforced at exactly the configured number.

Used as the production-like baseline to confirm the binding flow itself is
sound, independent of the multi-replica amplification investigated in #4627.

DEFAULT: SKIPPED.
    Skipped from default pytest runs. Opt in with
    ``RUN_BINDING_SINGLE_INSTANCE=1``.

Prerequisites:
    - Three standalone docker containers running:
        rl-pg         (postgres:18, port 5432:5432, db=mcp, user/pass=postgres/postgres)
        rl-redis      (redis:latest, port 6379:6379)
        rl-fast-time  (ghcr.io/ibm/fast-time-server:latest -transport sse, port 8888:8080)
    - Gateway running locally via ``make dev`` with env::

        DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/mcp'
        REDIS_URL='redis://127.0.0.1:6379/0'
        CACHE_TYPE='redis'
        AUTH_REQUIRED=false
        MCPGATEWAY_UI_ENABLED=true
        MCPGATEWAY_ADMIN_API_ENABLED=true
        SSRF_ALLOW_PRIVATE_NETWORKS=true
        SSRF_ALLOW_LOCALHOST=true
        PLUGINS_ENABLED=true
        PLUGINS_CONFIG_FILE=plugins/config.yaml

    The auto-setup fixture in this file will register the fast-time gateway +
    create a virtual server containing its tools if they aren't already
    present, so no manual API setup is required.

How to run:

    # Terse mode (just asserts pass/fail)
    RUN_BINDING_SINGLE_INSTANCE=1 \\
        uv run pytest \\
        tests/live_gateway/plugins/test_rate_limiter_binding_single_instance.py -v

    # Inspect mode (full [inspect] narration of every phase)
    RUN_BINDING_SINGLE_INSTANCE=1 INSPECT=1 \\
        uv run pytest \\
        tests/live_gateway/plugins/test_rate_limiter_binding_single_instance.py -v -s

Environment variables:
    RUN_BINDING_SINGLE_INSTANCE       (required: 1/true/yes) opt-in to running
    INSPECT                           (optional: 1) enable [inspect] narration
    GATEWAY_URL                       (default: http://localhost:8000)
    GATEWAY_EMAIL                     (default: admin@example.com)
    GATEWAY_PASSWORD                  (default: changeme)
    RATE_LIMITER_TEST_PG_CONTAINER    (default: rl-pg)
    REDIS_CONTAINER_NAME              (default: rl-redis)
    FAST_TIME_CONTAINER_PORT          (default: 8888)
    PROPAGATION_WAIT                  (default: see tests/helpers/integration_constants.py)
"""

# Standard
import os
import subprocess
import sys
import time
import uuid
from typing import Callable

# Third-Party
import pytest
import requests

from tests.helpers.integration_constants import PLUGIN_MODE_PROPAGATION_WAIT_SECONDS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

# Postgres container name (overridable for non-default compose project names).
# Default matches the standalone-container setup pattern used in single-instance
# tests (separate from the docker-compose stack which uses "*-postgres-1").
PG_CONTAINER = os.environ.get("RATE_LIMITER_TEST_PG_CONTAINER", "rl-pg")
PG_USER = os.environ.get("RATE_LIMITER_TEST_PG_USER", "postgres")
PG_DATABASE = os.environ.get("RATE_LIMITER_TEST_PG_DATABASE", "mcp")

# Redis container name for the docker-exec helpers (matches standalone setup).
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER_NAME", "rl-redis")

# Fast-time-server container port on the host (so the auto-setup fixture can
# construct the gateway URL from the host's LAN IP).
FAST_TIME_CONTAINER_PORT = int(os.environ.get("FAST_TIME_CONTAINER_PORT", "8888"))

# Plugin under test.
PLUGIN_NAME = "RateLimiterPlugin"

PROPAGATION_WAIT = int(
    os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS))
)


# Opt-in to the per-call ``[inspect]`` narration. When unset, ``_make_say()``
# returns a no-op so the test runs silently with just pass/fail and asserts.
_INSPECT_ENABLED = os.environ.get("INSPECT", "0").lower() in {"1", "true", "yes"}


def _make_say(capsys):
    """Return a narration helper that prints ``[inspect]`` lines when
    ``INSPECT=1`` is set; otherwise a no-op. Use with ``pytest -s`` for
    real-time output.
    """
    if not _INSPECT_ENABLED:
        return lambda _msg: None

    def _say(msg: str) -> None:
        with capsys.disabled():
            print(f"\n[inspect] {msg}")

    return _say


def _is_gateway_running() -> bool:
    """Return True if the gateway is reachable."""
    try:
        return requests.get(f"{GATEWAY_URL}/health", timeout=5).status_code == 200
    except requests.ConnectionError:
        return False


# ---------------------------------------------------------------------------
# Skip-guards
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_BINDING_SINGLE_INSTANCE", "0").lower() not in {"1", "true", "yes"},
        reason=(
            "Single-instance binding-lifecycle baseline test. "
            "Intentionally skipped by default. "
            "Opt in explicitly with RUN_BINDING_SINGLE_INSTANCE=1. "
            "Add INSPECT=1 and `pytest -s` for full diagnostic narration. "
            "See module docstring for the full command set and prereqs."
        ),
    ),
    pytest.mark.skipif(
        not _is_gateway_running(),
        reason=f"Gateway not running at {GATEWAY_URL}",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_API_TOKEN_CACHE: str | None = None


def _get_session_token() -> str:
    """Return an admin bearer token for gateway calls.

    NOTE: this mints an API-style token (``sub`` = email) via
    ``mcpgateway.utils.create_jwt_token`` rather than a ``/auth/login`` session
    token (``sub`` = UUID). On this build the streamable-HTTP
    ``POST /servers/{id}/mcp`` path rejects session tokens with HTTP 401
    "User not found in database": it reads ``user_email = payload["sub"]`` (the
    UUID) and never resolves it to an email the way the REST path does
    (issue #4816). An API token sidesteps that gap so the rate-limiter binding
    behaviour itself can be exercised end-to-end. Requires ``JWT_SECRET_KEY``
    in the environment.
    """
    global _API_TOKEN_CACHE  # noqa: PLW0603
    if _API_TOKEN_CACHE:
        return _API_TOKEN_CACHE
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY must be set in the environment to mint an API token")
    out = subprocess.check_output(
        [
            sys.executable, "-m", "mcpgateway.utils.create_jwt_token",
            "--username", GATEWAY_EMAIL, "--exp", "240", "--admin", "--secret", secret,
        ],
        text=True,
    )
    _API_TOKEN_CACHE = out.strip().splitlines()[-1].strip()
    return _API_TOKEN_CACHE


def _fresh_headers() -> dict:
    """Get fresh auth headers for an admin call."""
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _create_test_team() -> str:
    """Create a fresh non-personal team for the test and return its id."""
    headers = _fresh_headers()
    resp = requests.post(
        f"{GATEWAY_URL}/teams/",
        json={
            "name": f"rl-single-test-team-{uuid.uuid4().hex[:8]}",
            "description": "Ephemeral team for rate-limiter single-instance binding test",
        },
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _delete_test_team(team_id: str) -> None:
    """Best-effort delete of the test team at the end of the run."""
    try:
        requests.delete(
            f"{GATEWAY_URL}/teams/{team_id}",
            headers=_fresh_headers(),
            timeout=10,
        )
    except requests.RequestException:
        pass  # cleanup best-effort


def _stamp_tool_team_id(tool_id: str, team_id: str) -> str:
    """Force ``tools.team_id`` for ``tool_id`` via ``docker exec ... psql``.

    Returns the previous team_id (empty string if NULL) so the caller can
    restore it on teardown. Skips the test if the postgres container isn't
    reachable.

    Uses psql's ``-v`` variable substitution piped via stdin so values are
    quoted as SQL string literals by psql itself (escape-safe).
    """
    # Read the current value so we can restore it on teardown.
    select_sql = "SELECT COALESCE(team_id, '') FROM tools WHERE id = :'tool_id';"
    cmd_select = [
        "docker", "exec", "-i", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-v", f"tool_id={tool_id}",
        "-tA",
    ]
    try:
        prev = subprocess.run(
            cmd_select, input=select_sql, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(
            f"Cannot reach postgres container {PG_CONTAINER!r} to stamp tool team_id "
            f"({type(exc).__name__}: {exc}). Set RATE_LIMITER_TEST_PG_CONTAINER if "
            f"the container has a different name in your environment."
        )

    update_sql = "UPDATE tools SET team_id = :'team_id' WHERE id = :'tool_id';"
    cmd_update = [
        "docker", "exec", "-i", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-v", f"team_id={team_id}",
        "-v", f"tool_id={tool_id}",
    ]
    subprocess.run(cmd_update, input=update_sql, capture_output=True, text=True, timeout=10, check=True)
    return prev


def _restore_tool_team_id(tool_id: str, prev_team_id: str) -> None:
    """Restore ``tools.team_id`` after the test finishes. Best-effort.

    NULL branch keeps the SQL keyword literal since psql's ``-v`` can only
    substitute quoted string values, not bare keywords.
    """
    cmd = [
        "docker", "exec", "-i", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-v", f"tool_id={tool_id}",
    ]
    if prev_team_id:
        cmd += ["-v", f"team_id={prev_team_id}"]
        sql = "UPDATE tools SET team_id = :'team_id' WHERE id = :'tool_id';"
    else:
        sql = "UPDATE tools SET team_id = NULL WHERE id = :'tool_id';"
    try:
        subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=10, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # cleanup best-effort


def _post_binding(
    team_id: str,
    tool_name: str,
    mode: str,
    binding_reference_id: str,
    config: dict,
) -> dict:
    """POST a single rate-limiter binding via the API."""
    payload = {
        "teams": {
            team_id: {
                "policies": [
                    {
                        "tool_names": [tool_name],
                        "plugin_id": PLUGIN_NAME,
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
        headers=_fresh_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _get_binding_via_api(binding_reference_id: str) -> dict | None:
    """Fetch a binding by ``binding_reference_id`` via the gateway API.

    Returns the first binding row with the given reference id, or ``None``
    if not found.
    """
    resp = requests.get(
        f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
        params={"binding_reference_id": binding_reference_id},
        headers=_fresh_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    bindings = body.get("bindings", []) if isinstance(body, dict) else body
    return bindings[0] if bindings else None


def _delete_binding_by_reference(binding_reference_id: str) -> None:
    """Delete bindings tagged with the given reference id. Best-effort."""
    try:
        requests.delete(
            f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
            params={"binding_reference_id": binding_reference_id},
            headers=_fresh_headers(),
            timeout=10,
        )
    except requests.RequestException:
        pass  # cleanup best-effort


def _psql_get_binding_config(binding_reference_id: str) -> dict | None:
    """Belt-and-braces: read the ``config`` JSON column directly from Postgres.

    Cross-checks that the binding API write path persisted to the right
    place. Returns the parsed dict, or ``None`` if the row isn't found.
    Skips the test if the postgres container isn't reachable.
    """
    sql = (
        "SELECT config::text FROM tool_plugin_bindings "
        "WHERE binding_reference_id = :'ref_id' LIMIT 1;"
    )
    cmd = [
        "docker", "exec", "-i", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DATABASE,
        "-v", f"ref_id={binding_reference_id}",
        "-tA",
    ]
    try:
        out = subprocess.run(
            cmd, input=sql, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(
            f"psql cross-check unavailable ({type(exc).__name__}: {exc})"
        )
    if not out:
        return None
    import json as _json  # noqa: PLC0415
    try:
        return _json.loads(out)
    except _json.JSONDecodeError:
        return None


def _redis_rl_keys(team_id: str) -> list[tuple[str, str, str]]:
    """Return rate-limiter keys for ``team_id`` as ``(key, value, ttl)`` tuples.

    Scans only ``rl:{team_id}:*`` so cross-team and cross-test contamination
    can't satisfy a per-test "this dimension key exists" assertion.

    Raises ``pytest.skip`` when the Redis container is unreachable. Empty-list
    return is reserved for "container reachable, no keys present".
    """
    pattern = f"rl:{team_id}:*"
    try:
        keys_out = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "--scan", "--pattern", pattern],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(
            f"Redis container {REDIS_CONTAINER!r} unreachable via docker exec "
            f"({type(exc).__name__}: {exc}). "
            f"Set REDIS_CONTAINER_NAME if your environment uses a different container."
        )
    rows: list[tuple[str, str, str]] = []
    for k in (line.strip() for line in keys_out.splitlines() if line.strip()):
        try:
            v = subprocess.run(
                ["docker", "exec", REDIS_CONTAINER, "redis-cli", "GET", k],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            t = subprocess.run(
                ["docker", "exec", REDIS_CONTAINER, "redis-cli", "TTL", k],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            v = "?"
            t = "?"
        rows.append((k, v, t))
    return rows


def _get_admin_plugin_state(plugin_name: str) -> dict:
    """Return the loaded plugin's runtime state from ``GET /admin/plugins``.

    The ``mode`` and ``config_summary`` fields here reflect whatever the
    gateway has currently mounted in memory for this plugin (static config
    overlaid with any Redis-persisted ``plugin:<name>:mode`` override).
    """
    resp = requests.get(
        f"{GATEWAY_URL}/admin/plugins",
        headers=_fresh_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    plugins = resp.json().get("plugins", [])
    for p in plugins:
        if p.get("name") == plugin_name:
            return p
    pytest.skip(f"Plugin {plugin_name!r} not present in /admin/plugins listing")


def _auto_detect_server_and_tool() -> tuple[str, str]:
    """Find a virtual server with a fast-time tool and return (server_id, tool_name).

    Looks for a server whose ``associatedTools`` includes a tool matching
    the ``fast-time-*-get-system-time`` pattern. Skips the test if no such
    server is registered (the auto-setup fixture should have created one,
    so this skip means setup itself failed).
    """
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=_fresh_headers(), timeout=10)
    resp.raise_for_status()
    for server in resp.json():
        tools = server.get("associatedTools", []) or []
        for tool in tools:
            tl = tool.lower() if isinstance(tool, str) else ""
            if "fast-time" in tl and "get-system-time" in tl:
                return server["id"], tool
    pytest.skip(
        "No virtual server with a fast-time-*-get-system-time tool found. "
        "The auto-setup fixture should have created one — check that "
        "fast-time-server container is reachable at the configured port."
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _detect_host_lan_ip() -> str:
    """Detect the host's LAN IP for constructing the fast-time-server URL.

    The gateway is on the host (make dev) and the fast-time-server is in a
    container with its port published. From the gateway's perspective, the
    container is reachable via the host's LAN IP. ``host.docker.internal``
    doesn't apply here because the gateway is not in a container.
    """
    for iface in ("en0", "en1"):
        try:
            out = subprocess.run(
                ["ipconfig", "getifaddr", iface],
                capture_output=True, text=True, timeout=3, check=False,
            ).stdout.strip()
            if out:
                return out
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


@pytest.fixture(scope="session")
def ensure_fast_time_gateway_and_server():
    """Idempotent setup: ensure the ``fast-time-sse`` gateway is registered
    and a virtual server containing its tools exists.

    On session teardown, only deletes resources THIS fixture created. If the
    gateway/server already existed (e.g., set up manually by the operator),
    they are left in place.
    """
    created_gateway_id: str | None = None
    created_server_id: str | None = None

    # ---- Ensure fast-time-sse gateway exists -------------------------------
    headers = _fresh_headers()
    gateways = requests.get(f"{GATEWAY_URL}/gateways", headers=headers, timeout=10).json()
    existing_gw = next((g for g in gateways if g.get("name") == "fast-time-sse"), None)
    if existing_gw is None:
        host_ip = _detect_host_lan_ip()
        if not host_ip:
            pytest.skip(
                "Cannot detect host LAN IP (tried en0, en1) to construct the "
                "fast-time gateway URL. Set up the gateway manually or check "
                "your network interfaces."
            )
        gw_resp = requests.post(
            f"{GATEWAY_URL}/gateways",
            json={
                "name": "fast-time-sse",
                "url": f"http://{host_ip}:{FAST_TIME_CONTAINER_PORT}/sse",
                "transport": "SSE",
            },
            headers=_fresh_headers(),
            timeout=60,
        )
        gw_resp.raise_for_status()
        created_gateway_id = gw_resp.json()["id"]
        # Give the gateway a moment for federation tool discovery to fan out
        # before we check /tools for the virtual-server creation step.
        time.sleep(3)

    # ---- Ensure a virtual server with fast-time tools exists ---------------
    servers = requests.get(f"{GATEWAY_URL}/servers", headers=_fresh_headers(), timeout=10).json()
    has_fast_time_server = any(
        any(
            "fast-time" in (t or "").lower() and "get-system-time" in (t or "").lower()
            for t in (s.get("associatedTools") or [])
        )
        for s in servers
    )
    if not has_fast_time_server:
        tools = requests.get(f"{GATEWAY_URL}/tools", headers=_fresh_headers(), timeout=10).json()
        ft_tool_ids = [
            t["id"] for t in tools
            if "fast-time" in (t.get("name") or "").lower()
        ]
        if not ft_tool_ids:
            pytest.skip(
                "fast-time gateway is registered but no fast-time-* tools were "
                "discovered. Check that the fast-time-server container is "
                "actually reachable from the gateway."
            )
        srv_resp = requests.post(
            f"{GATEWAY_URL}/servers",
            json={
                "server": {
                    "name": "fast-time",
                    "description": "Auto-created by single-instance binding test",
                    "associated_tools": ft_tool_ids,
                },
            },
            headers=_fresh_headers(),
            timeout=15,
        )
        srv_resp.raise_for_status()
        created_server_id = srv_resp.json()["id"]

    yield  # tests run

    # ---- Teardown: only delete what THIS fixture created -------------------
    if created_server_id:
        try:
            requests.delete(
                f"{GATEWAY_URL}/servers/{created_server_id}",
                headers=_fresh_headers(),
                timeout=10,
            )
        except requests.RequestException:
            pass
    if created_gateway_id:
        try:
            requests.delete(
                f"{GATEWAY_URL}/gateways/{created_gateway_id}",
                headers=_fresh_headers(),
                timeout=10,
            )
        except requests.RequestException:
            pass


@pytest.fixture(scope="module")
def server_and_tool(ensure_fast_time_gateway_and_server):
    """Locate the virtual server + fast-time tool for the test to call.

    Depends on the session-scoped auto-setup fixture so we know the
    artifacts exist before we look for them.
    """
    return _auto_detect_server_and_tool()


@pytest.fixture
def team_id(server_and_tool):
    """Create a fresh test team, stamp the test tool with its id, yield the
    team_id, and restore + delete the team on teardown.
    """
    _, tool_name = server_and_tool
    # Find the tool's id (the auto-detect helper returns name; we need id for stamping)
    tools = requests.get(f"{GATEWAY_URL}/tools", headers=_fresh_headers(), timeout=10).json()
    tool_id = next(
        (t["id"] for t in tools if t.get("name") == tool_name),
        None,
    )
    if not tool_id:
        pytest.skip(f"Could not resolve tool id for {tool_name!r}")

    tid = _create_test_team()
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


# Reference-id prefixes this test file creates. Used by the autouse fixture
# below to clean up leftover bindings from prior runs that crashed before
# their own teardown could run.
_TEST_BINDING_REF_PREFIXES = (
    "rl-single-inspect-",
)


def _delete_leftover_test_bindings() -> None:
    """List all bindings via the API; delete any matching this file's test
    naming convention. Goes through the API DELETE so the gateway publishes
    the cache-invalidation pub/sub. Best-effort: any single failure is
    swallowed so the fixture can still run.
    """
    try:
        resp = requests.get(
            f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
            headers=_fresh_headers(),
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return
    body = resp.json()
    bindings = body.get("bindings", []) if isinstance(body, dict) else body
    for binding in bindings:
        ref = binding.get("bindingReferenceId") or ""
        if any(ref.startswith(p) for p in _TEST_BINDING_REF_PREFIXES):
            _delete_binding_by_reference(ref)


@pytest.fixture(autouse=True)
def _isolate_state_before_each_binding_test():
    """Clean cross-test state before each test runs. Three layers:

    1. Redis: drop ``plugin:RateLimiterPlugin:mode`` + leftover ``rl:*`` keys
    2. DB: delete any leftover ``rl-single-*`` rows from prior crashed runs
       (via API DELETE so the gateway invalidates its caches too)
    3. Plugin-manager caches: invalidated implicitly by step 2's pub/sub

    Raises ``pytest.skip`` if the Redis container is unreachable at fixture
    setup (so a docker outage surfaces as a test-infra skip rather than a
    misleading "counter is missing" assertion failure).
    """
    def _docker_redis_cli(*args: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["docker", "exec", REDIS_CONTAINER, "redis-cli", *args],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            pytest.skip(
                f"Redis container {REDIS_CONTAINER!r} unreachable via docker exec — "
                f"cannot isolate rl:* state for this test ({type(exc).__name__}: {exc}). "
                f"Set REDIS_CONTAINER_NAME if your environment uses a different name."
            )

    # 1. Drop the gateway-wide mode override (cross-test pollutant)
    _docker_redis_cli("DEL", "plugin:RateLimiterPlugin:mode")

    # 2. Drop any leftover rl:* counters from prior runs
    scan = _docker_redis_cli("--scan", "--pattern", "rl:*")
    if scan.returncode == 0:
        for key in (k.strip() for k in scan.stdout.splitlines() if k.strip()):
            _docker_redis_cli("DEL", key)

    # 3. Delete leftover DB bindings from prior crashed runs (via API)
    _delete_leftover_test_bindings()

    yield
    # No teardown — the same logic at the start of the next test handles it.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRateLimiterBindingSingleInstance:
    """Single-instance baseline: a rate-limiter binding configured through
    the bindings API enforces its limits at tool-dispatch time with EXACT
    1:1 counter behavior (no amplification)."""

    def test_binding_full_lifecycle_inspectable(
        self, server_and_tool, team_id, cleanup_bindings, capsys
    ):
        """End-to-end binding flow against a single-process gateway.

        Walks the full POST-binding lifecycle and verifies:

        1. The binding's caller-scoped overrides land in Postgres (API + psql
           cross-check) with the exact values configured.
        2. After ``PROPAGATION_WAIT``, the gateway routes calls through the
           per-tenant plugin manager that reflects the binding.
        3. 5 user-facing tool calls produce EXACTLY 5 plugin-hook invocations
           (counter == 5 on all 3 dimension keys). This is the 1:1 baseline
           that confirms the rate-limiter counts user invocations correctly
           when there is no session-affinity fan-out across worker processes.
        4. With ``by_user: 3/m``, calls 1-3 are ALLOWED and calls 4-5 are
           BLOCKED — exact enforcement at the configured number.

        Companion to ``test_rate_limiter_bindings_lifecycle.py`` (the
        multi-instance reproducer). That file uses looser limits because
        the docker-compose stack amplifies counters by ~15x via session
        affinity across 3 replicas × 24 workers (see #4627). This file
        uses tighter limits because there is no amplification to absorb.
        """
        server_id, tool_name = server_and_tool
        ref_id = f"rl-single-inspect-{uuid.uuid4().hex[:8]}"
        cleanup_bindings.append(ref_id)

        # Tight 3-dim limits chosen so a 5-call burst visibly trips the
        # tightest (by_user: 3/m) at call 4.
        binding_by_user = "3/m"
        binding_by_tenant = "5/m"
        binding_by_tool_limit = "7/m"

        _say = _make_say(capsys)

        # ---- Phase 0: baseline ----------------------------------------------
        _say("Phase 0 — capturing baseline plugin state from /admin/plugins")
        baseline = _get_admin_plugin_state(PLUGIN_NAME)
        baseline_mode = baseline.get("mode")
        _say(f"  baseline mode = {baseline_mode!r}")
        _say("  → expected mode: 'disabled' (binding's mode='enforce' will override per-tenant)")

        # ---- Phase 1: POST binding ------------------------------------------
        _say(
            f"Phase 1 — POSTing binding with by_user={binding_by_user!r}, "
            f"by_tenant={binding_by_tenant!r}, "
            f"by_tool={{{tool_name!r}: {binding_by_tool_limit!r}}}"
        )
        binding_config = {
            "algorithm": "fixed_window",
            "backend": "redis",
            "by_user": binding_by_user,
            "by_tenant": binding_by_tenant,
            "by_tool": {tool_name: binding_by_tool_limit},
            # redis_url + redis_key_prefix omitted (gateway-scoped, not
            # operator-tunable; see #4665 for why).
            "fail_mode": "open",
        }
        _post_binding(
            team_id=team_id,
            tool_name=tool_name,
            mode="enforce",
            binding_reference_id=ref_id,
            config=binding_config,
        )
        _say(f"  binding_reference_id = {ref_id}")

        # ---- Phase 2: persistence cross-check -------------------------------
        _say("Phase 2 — verifying the binding actually persisted (all 3 dimensions)")
        api_binding = _get_binding_via_api(ref_id)
        assert api_binding is not None, f"binding {ref_id} not returned by API"
        api_config = api_binding.get("config") or {}
        assert api_config.get("by_user") == binding_by_user
        assert api_config.get("by_tenant") == binding_by_tenant
        assert api_config.get("by_tool", {}).get(tool_name) == binding_by_tool_limit
        _say(f"  ✓ API confirms all 3 dimension values")

        psql_config = _psql_get_binding_config(ref_id)
        assert psql_config is not None, f"binding {ref_id} not found in Postgres"
        assert psql_config.get("by_user") == binding_by_user
        assert psql_config.get("by_tenant") == binding_by_tenant
        assert psql_config.get("by_tool", {}).get(tool_name) == binding_by_tool_limit
        _say(f"  ✓ Postgres confirms config column persisted with the binding's exact values")

        # ---- Phase 3: propagation wait --------------------------------------
        _say(f"Phase 3 — sleeping {PROPAGATION_WAIT}s for per-tenant manager rebuild")
        time.sleep(PROPAGATION_WAIT)

        # ---- Phase 4: fire 5 calls (no session-id; single-instance doesn't need it)
        burst_size = 5
        _say(
            f"Phase 4 — firing {burst_size} tool calls. "
            f"Expected: calls 1-3 ALLOWED, calls 4-5 BLOCKED at binding's by_user: {binding_by_user}"
        )

        call_headers = {
            **_fresh_headers(),
            "Accept": "application/json, text/event-stream",
        }

        per_call_outcomes: list[str] = []
        allowed = rate_limited = errors = 0
        for i in range(burst_size):
            payload = {
                "jsonrpc": "2.0",
                "id": f"single-{i + 1}",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
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
                elif resp.status_code == 200:
                    body = resp.json()
                    result = body.get("result", {})
                    err = body.get("error")
                    if err is not None:
                        msg = (err.get("message") or "").lower()
                        if "rate limit" in msg:
                            outcome = "BLOCKED (JSON-RPC rate-limit error)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR (JSON-RPC: {err.get('message', '?')[:50]})"
                            errors += 1
                    elif result.get("isError"):
                        text = ""
                        for c in result.get("content", []) or []:
                            if c.get("type") == "text":
                                text = c.get("text", "")
                                break
                        if "rate limit" in text.lower():
                            outcome = "BLOCKED (MCP isError, rate-limit)"
                            rate_limited += 1
                        else:
                            outcome = f"ERROR (MCP isError: {text[:50]})"
                            errors += 1
                    else:
                        outcome = "ALLOWED"
                        allowed += 1
                else:
                    outcome = f"ERROR (HTTP {resp.status_code})"
                    errors += 1
            except requests.RequestException as exc:
                outcome = f"ERROR (transport: {exc})"
                errors += 1
            per_call_outcomes.append(outcome)
            _say(f"  call {i + 1}/{burst_size}: {outcome}")

        _say(f"  summary: allowed={allowed}  rate_limited={rate_limited}  errors={errors}")

        # ---- Phase 5: final Redis snapshot ----------------------------------
        _say("Phase 5 — current rl:{team_id}:* keys in Redis (what the plugin actually wrote)")
        rl_keys = _redis_rl_keys(team_id)
        for k, v, t in rl_keys:
            _say(f"  {k} = {v}  (ttl={t}s)")

        # ---- Phase 6: EXACT behavioral assertions ---------------------------
        _say("Phase 6 — asserting EXACT enforcement (1:1 counter, blocks at binding limit)")

        # 6a — no transport-level errors
        assert errors == 0, (
            f"Non-rate-limit errors indicate a setup/transport problem: "
            f"outcomes={per_call_outcomes}"
        )

        # 6b — exact 3 allowed / 2 blocked (the 1:1 fingerprint)
        assert allowed == 3, (
            f"Expected exactly 3 ALLOWED calls (1:1 single-instance baseline), "
            f"got allowed={allowed}, rate_limited={rate_limited}. "
            f"Outcomes: {per_call_outcomes}. "
            f"If allowed > 3, calls aren't being blocked at the binding's limit. "
            f"If allowed < 3, something is rate-limiting before the binding's by_user: 3/m."
        )
        assert rate_limited == 2, (
            f"Expected exactly 2 BLOCKED calls, got rate_limited={rate_limited}. "
            f"Outcomes: {per_call_outcomes}"
        )
        _say(f"  ✓ allowed={allowed}, rate_limited={rate_limited} (matches binding's by_user: 3/m exactly)")

        # 6c — all 3 dimension counter keys present, each at exactly 5
        key_strs = [k for (k, _v, _t) in rl_keys]
        user_keys = [k for k in key_strs if ":user:" in k]
        tenant_keys = [k for k in key_strs if ":tenant:" in k]
        tool_keys = [k for k in key_strs if f":tool:{tool_name}:" in k]

        assert len(user_keys) >= 1, (
            f"by_user counter key missing under rl:{team_id}:*. "
            f"All keys: {key_strs!r}"
        )
        assert len(tenant_keys) >= 1, (
            f"by_tenant counter key missing under rl:{team_id}:*. "
            f"All keys: {key_strs!r}"
        )
        assert len(tool_keys) >= 1, (
            f"by_tool counter key for {tool_name!r} missing under rl:{team_id}:*. "
            f"All keys: {key_strs!r}"
        )

        # 6d — each counter at EXACTLY 5 (1:1 with the 5 user-facing calls)
        key_to_value = {k: v for (k, v, _t) in rl_keys}
        for kind, keys in (("user", user_keys), ("tenant", tenant_keys), ("tool", tool_keys)):
            for k in keys:
                v = key_to_value[k]
                assert v == str(burst_size), (
                    f"Expected {kind} counter at {burst_size} (1:1 with {burst_size} user calls); "
                    f"got {k} = {v!r}. "
                    f"If counter > {burst_size}, something is amplifying (session-affinity fan-out, "
                    f"federation duplication, or hook double-firing — see #4627)."
                )
        _say(f"  ✓ all 3 dimension counters at exactly {burst_size} — 1:1 with user calls, no amplification")

        _say("Phase 7 — cleanup runs via cleanup_bindings fixture on test exit")
