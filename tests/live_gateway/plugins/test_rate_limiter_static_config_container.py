"""Static-config rate-limiter TLS+AUTH test (self-contained, isolated container stack).

Mirrors what Raji runs: the rate limiter enforces purely from **static
``config.yaml``** (no bindings API). All three dimensions are set to ``3/m`` in
``rl-shared-bake/config-static.yaml``, so a 5-call burst from one user/tool/tenant
lands 3 ALLOWED + 2 BLOCKED, and the per-dimension counter keys each reach 5
(the counter counts every attempt).

To get the **tenant/team** dimension (and team-namespaced keys), the test stamps
the fast-time tool with a team. Unlike the dynamic test (whose binding POST fires
a cache-invalidation pub/sub), there is no binding here, so a *fresh* team each
run would race the gateway's ~30s per-(team,tool) manager cache and land the keys
under the previous team. The test therefore **reuses** an already-stamped team
across runs (stamping + waiting only on the first run against a fresh stack), so
re-runs are reliable. The rate *limit* itself is still 100% static config.

This file is standalone — it does NOT import the dynamic binding test. Stand up
the isolated static stack first::

    ./rl-shared-bake/static-up.sh      # own containers (rl-static-*), network, port 8001
    ./rl-shared-bake/static-run.sh     # runs this test (INSPECT=1 narration)
    ./rl-shared-bake/static-down.sh

Asserts:
  * allowed == STATIC_LIMIT (3), blocked == STATIC_BURST - STATIC_LIMIT (2)
  * user, tool AND tenant counter keys all present under rl:<team>:* and each == STATIC_BURST (5)

Environment (set by static-run.sh):
  GATEWAY_URL (default http://localhost:8001) / REDIS_CONTAINER_NAME (rl-static-redis)
  PG_CONTAINER_NAME (rl-static-pg) / REDIS_CLI_PASSWORD / JWT_SECRET_KEY (required)
  STATIC_LIMIT (3) / STATIC_BURST (5) / STATIC_PROPAGATION_WAIT (8) / INSPECT (0|1)
  RUN_RATE_LIMITER_STATIC (required: 1/true/yes) — opt-in guard
"""

# requests' .json() returns Any, so JSON-walking here is inherently untyped.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownLambdaType=false

# Standard
import os
import subprocess
import sys
import time
import uuid

# Third-Party
import pytest
import requests

# ---------------------------------------------------------------------------
# Config (all from env so this points at the isolated static stack)
# ---------------------------------------------------------------------------
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8001")
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER_NAME", "rl-static-redis")
PG_CONTAINER = os.environ.get("PG_CONTAINER_NAME", "rl-static-pg")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "mcp")
REDIS_PASSWORD = os.environ.get("REDIS_CLI_PASSWORD", "rlTlsTest_pw_2026")  # pragma: allowlist secret
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "")
STATIC_LIMIT = int(os.environ.get("STATIC_LIMIT", "3"))
STATIC_BURST = int(os.environ.get("STATIC_BURST", "5"))
PROPAGATION_WAIT = float(os.environ.get("STATIC_PROPAGATION_WAIT", "8"))
ADMIN_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")

REDIS_CLI_TLS = ["--tls", "--cacert", "/certs/ca.crt", "-a", REDIS_PASSWORD, "--no-auth-warning"]

# Opt-in [inspect] narration (use with `pytest -s`); no-op when INSPECT is unset.
_INSPECT_ENABLED = os.environ.get("INSPECT", "0").lower() in {"1", "true", "yes"}


def _is_gateway_running() -> bool:
    try:
        return requests.get(f"{GATEWAY_URL}/health", timeout=5).status_code == 200
    except requests.RequestException:
        return False


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_RATE_LIMITER_STATIC", "0").lower() not in {"1", "true", "yes"},
        reason=(
            "Static-config rate-limiter test. Opt in with RUN_RATE_LIMITER_STATIC=1, "
            "and bring up the isolated stack first: ./rl-shared-bake/static-up.sh."
        ),
    ),
    pytest.mark.skipif(
        not _is_gateway_running(),
        reason=f"Static gateway not running at {GATEWAY_URL} — run ./rl-shared-bake/static-up.sh",
    ),
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _token() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY must be set to mint an admin token")
    out = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token",
         "--username", ADMIN_EMAIL, "--exp", "10080", "--secret", JWT_SECRET],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out.splitlines()[-1].strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _find_server_and_tool(token: str) -> tuple[str, str]:
    servers = requests.get(f"{GATEWAY_URL}/servers", headers=_headers(token), timeout=10).json()
    for s in servers:
        for t in s.get("associatedTools") or []:
            if "fast-time" in (t or "").lower() and "get-system-time" in (t or "").lower():
                return s["id"], t
    pytest.skip("No virtual server with a fast-time get-system-time tool — run ./rl-shared-bake/static-up.sh")


def _resolve_tool_id(token: str, tool_name: str) -> str:
    tools = requests.get(f"{GATEWAY_URL}/tools", headers=_headers(token), timeout=10).json()
    tid = next((t["id"] for t in tools if t.get("name") == tool_name), None)
    if not tid:
        pytest.skip(f"Could not resolve tool id for {tool_name!r}")
    return tid


def _create_test_team(token: str) -> str:
    resp = requests.post(
        f"{GATEWAY_URL}/teams/",
        json={"name": f"rl-static-team-{uuid.uuid4().hex[:8]}", "description": "static rate-limiter team"},
        headers=_headers(token), timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Postgres helpers (stamp the tool's team_id so calls carry a tenant context)
# ---------------------------------------------------------------------------
def _psql(sql: str, *vars_: str) -> str:
    cmd = ["docker", "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DATABASE, "-tA"]
    for v in vars_:
        cmd += ["-v", v]
    try:
        return subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(f"Cannot reach postgres container {PG_CONTAINER!r} ({type(exc).__name__}: {exc})")


def _tool_team(tool_id: str) -> str:
    """Current ``tools.team_id`` for the tool ('' if NULL)."""
    return _psql("SELECT COALESCE(team_id, '') FROM tools WHERE id = :'tool_id';", f"tool_id={tool_id}")


def _stamp_tool_team_id(tool_id: str, team_id: str) -> None:
    _psql("UPDATE tools SET team_id = :'team_id' WHERE id = :'tool_id';", f"team_id={team_id}", f"tool_id={tool_id}")


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------
def _redis_cli(*args: str) -> str:
    return subprocess.run(
        ["docker", "exec", REDIS_CONTAINER, "redis-cli", *REDIS_CLI_TLS, *args],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()


def _clear_rl_keys() -> None:
    try:
        keys = _redis_cli("--scan", "--pattern", "rl:*")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(f"Redis container {REDIS_CONTAINER!r} unreachable ({type(exc).__name__}: {exc})")
    for k in (line.strip() for line in keys.splitlines() if line.strip()):
        _redis_cli("DEL", k)


def _rl_keys(team_id: str) -> dict[str, int]:
    keys = _redis_cli("--scan", "--pattern", f"rl:{team_id}:*")
    out: dict[str, int] = {}
    for k in (line.strip() for line in keys.splitlines() if line.strip()):
        try:
            out[k] = int(_redis_cli("GET", k))
        except ValueError:
            out[k] = -1
    return out


def _make_say(capsys):
    """Return a narration helper printing ``[inspect]`` lines when ``INSPECT=1``;
    otherwise a no-op. Use with ``pytest -s`` for real-time output."""
    if not _INSPECT_ENABLED:
        return lambda _msg: None

    def _say(msg: str) -> None:
        with capsys.disabled():
            print(f"\n[inspect] {msg}")

    return _say


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
class TestRateLimiterStaticConfig:
    """Static config.yaml enforcement (no bindings API), all three dimensions."""

    def test_static_config_enforces_and_deposits_keys(self, capsys):
        say = _make_say(capsys)
        token = _token()
        server_id, tool_name = _find_server_and_tool(token)
        tool_id = _resolve_tool_id(token, tool_name)

        say(f"Phase 1 — static config only (no bindings API): by_user=by_tenant=by_tool={STATIC_LIMIT}/m, enforce")
        say(f"  server={server_id}  tool={tool_name}")

        # Reuse a stamped team across runs so the gateway's per-(team,tool)
        # manager cache stays consistent. A fresh team each run would race the
        # ~30s cache and land keys under the previous team (no binding here to
        # fire a cache-invalidation). Only the first run on a fresh stack stamps.
        team_id = _tool_team(tool_id)
        if team_id:
            say(f"Phase 2 — reusing already-stamped team {team_id} (tenant dimension)")
        else:
            team_id = _create_test_team(token)
            _stamp_tool_team_id(tool_id, team_id)
            say(f"Phase 2 — created team {team_id}, stamped the tool; waiting {PROPAGATION_WAIT:g}s to propagate")
            time.sleep(PROPAGATION_WAIT)

        _clear_rl_keys()
        say(f"Phase 3 — firing {STATIC_BURST} tool calls as {ADMIN_EMAIL}")
        allowed = rate_limited = errors = 0
        for i in range(STATIC_BURST):
            payload = {
                "jsonrpc": "2.0",
                "id": f"static-{i + 1}",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
            }
            resp = requests.post(
                f"{GATEWAY_URL}/servers/{server_id}/mcp",
                json=payload, headers=_headers(token), timeout=15,
            )
            if resp.status_code == 429:
                outcome = "BLOCKED (HTTP 429)"
                rate_limited += 1
            elif resp.status_code == 200:
                body = resp.json()
                err = body.get("error")
                result = body.get("result", {})
                text = " ".join(c.get("text", "") for c in (result.get("content") or [])).lower()
                if err is not None and "rate limit" in (err.get("message") or "").lower():
                    outcome = "BLOCKED (JSON-RPC rate-limit)"
                    rate_limited += 1
                elif result.get("isError") and "rate limit" in text:
                    outcome = "BLOCKED (MCP isError, rate-limit)"
                    rate_limited += 1
                elif err is not None or result.get("isError"):
                    outcome = f"ERROR ({(err or {}).get('message', '') or text[:40]})"
                    errors += 1
                else:
                    outcome = "ALLOWED"
                    allowed += 1
            else:
                outcome = f"ERROR (HTTP {resp.status_code})"
                errors += 1
            say(f"  call {i + 1}/{STATIC_BURST}: {outcome}")

        say(f"Phase 4 — summary: allowed={allowed}  rate_limited={rate_limited}  errors={errors}")

        # ---- enforcement ---------------------------------------------------
        assert errors == 0, f"unexpected errors during burst: {errors}"
        assert allowed == STATIC_LIMIT, (
            f"static by_user/by_tenant/by_tool={STATIC_LIMIT}/m should allow exactly "
            f"{STATIC_LIMIT}, got allowed={allowed} (blocked={rate_limited})"
        )
        assert rate_limited == STATIC_BURST - STATIC_LIMIT, (
            f"expected {STATIC_BURST - STATIC_LIMIT} BLOCKED, got rate_limited={rate_limited}"
        )

        # ---- all three dimension keys, team-namespaced, each == burst ------
        keys = _rl_keys(team_id)
        say(f"Phase 5 — rl:{team_id}:* counter keys the plugin wrote:")
        for k, v in keys.items():
            say(f"  {k} = {v}  (attempts)")
        dims = {
            "user": next((k for k in keys if ":user:" in k and ADMIN_EMAIL in k), None),
            "tool": next((k for k in keys if ":tool:" in k and "get-system-time" in k), None),
            "tenant": next((k for k in keys if ":tenant:" in k), None),
        }
        say("Phase 6 — asserting all three dimensions present and each == burst (1:1 counter)")
        for dim, key in dims.items():
            assert key is not None, f"{dim} counter key not deposited under rl:{team_id}:*; have: {list(keys)}"
            assert keys[key] == STATIC_BURST, (
                f"{dim} counter {key}={keys[key]} should equal the {STATIC_BURST} attempts"
            )
        say(f"  ✓ allowed={allowed}, blocked={rate_limited}; user/tool/tenant keys all == {STATIC_BURST}")
