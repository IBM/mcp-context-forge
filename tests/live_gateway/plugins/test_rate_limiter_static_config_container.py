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
  GATEWAY_ADMIN_TOKEN (optional pre-minted bearer token)
  GATEWAY_CA_CERT (default tls-certs/ca.crt) / GATEWAY_VERIFY_TLS (1) / EXPECT_AUTH_REQUIRED (0|1)
  GATEWAY_CONTAINER_NAME (rl-static-gw; used only to mint an admin token inside the running image)
  EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE (0|1) — set to 1 when intentionally reproducing the
    issue pattern where external gateway MCP tool calls return BACKEND_UNAVAILABLE
  STATIC_LIMIT (3) / STATIC_BURST (5) / STATIC_CONCURRENCY (1) / STATIC_PROPAGATION_WAIT (8) / INSPECT (0|1)
  RUN_RATE_LIMITER_STATIC (required: 1/true/yes) — opt-in guard
"""

# requests' .json() returns Any, so JSON-walking here is inherently untyped.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownLambdaType=false

# Standard
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
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
REPO_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_CONTAINER = os.environ.get("GATEWAY_CONTAINER_NAME", "rl-static-gw")
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER_NAME", "rl-static-redis")
PG_CONTAINER = os.environ.get("PG_CONTAINER_NAME", "rl-static-pg")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "mcp")
REDIS_PASSWORD = os.environ.get("REDIS_CLI_PASSWORD", "rlTlsTest_pw_2026")  # pragma: allowlist secret
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "")
STATIC_LIMIT = int(os.environ.get("STATIC_LIMIT", "3"))
STATIC_BURST = int(os.environ.get("STATIC_BURST", "5"))
STATIC_CONCURRENCY = max(1, int(os.environ.get("STATIC_CONCURRENCY", "1")))
REQUEST_TIMEOUT = float(os.environ.get("STATIC_REQUEST_TIMEOUT", "15"))
PROPAGATION_WAIT = float(os.environ.get("STATIC_PROPAGATION_WAIT", "8"))
ADMIN_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_CA_CERT = os.environ.get("GATEWAY_CA_CERT", str(REPO_ROOT / "tls-certs" / "ca.crt"))
VERIFY_GATEWAY_TLS = os.environ.get("GATEWAY_VERIFY_TLS", "1").lower() not in {"0", "false", "no"}
EXPECT_AUTH_REQUIRED = os.environ.get("EXPECT_AUTH_REQUIRED", "0").lower() in {"1", "true", "yes"}
EXPECT_GATEWAY_REDIS_READY = os.environ.get("EXPECT_GATEWAY_REDIS_READY", "1").lower() not in {"0", "false", "no"}
EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE = os.environ.get("EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE", "0").lower() in {"1", "true", "yes"}

REDIS_CLI_TLS = ["--tls", "--cacert", "/certs/ca.crt", "-a", REDIS_PASSWORD, "--no-auth-warning"]

# Opt-in [inspect] narration (use with `pytest -s`); no-op when INSPECT is unset.
_INSPECT_ENABLED = os.environ.get("INSPECT", "0").lower() in {"1", "true", "yes"}


def _gateway_verify() -> str | bool:
    if not GATEWAY_URL.lower().startswith("https://"):
        return True
    if not VERIFY_GATEWAY_TLS:
        return False
    if Path(GATEWAY_CA_CERT).is_file():
        return GATEWAY_CA_CERT
    return True


REQUEST_VERIFY = _gateway_verify()


def _is_gateway_running() -> bool:
    try:
        return requests.get(f"{GATEWAY_URL}/health", timeout=5, verify=REQUEST_VERIFY).status_code == 200
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
    if admin_token := os.environ.get("GATEWAY_ADMIN_TOKEN"):
        return admin_token
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY must be set to mint an admin token")

    gateway_token = subprocess.run(
        [
            "docker",
            "exec",
            GATEWAY_CONTAINER,
            "python3",
            "-m",
            "mcpgateway.utils.create_jwt_token",
            "--username",
            ADMIN_EMAIL,
            "--exp",
            "10080",
            "--secret",
            JWT_SECRET,
            "--admin",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if gateway_token.returncode == 0 and gateway_token.stdout.strip():
        return gateway_token.stdout.strip().splitlines()[-1].strip()

    out = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token",
         "--username", ADMIN_EMAIL, "--exp", "10080", "--secret", JWT_SECRET, "--admin"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out.splitlines()[-1].strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _request(method: str, path: str, token: str | None = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", None) or {}
    if token:
        headers = {**_headers(token), **headers}
    else:
        headers.setdefault("Accept", "application/json, text/event-stream")
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    kwargs.setdefault("verify", REQUEST_VERIFY)
    return requests.request(method, f"{GATEWAY_URL}{path}", headers=headers, **kwargs)


def _assert_auth_is_required(say) -> None:
    if not EXPECT_AUTH_REQUIRED:
        return
    resp = _request("GET", "/servers")
    assert resp.status_code in {401, 403}, f"expected unauthenticated /servers to be rejected, got HTTP {resp.status_code}: {resp.text[:200]}"
    say(f"Auth check — unauthenticated /servers rejected with HTTP {resp.status_code}")


def _assert_gateway_redis_ready(say) -> None:
    resp = _request("GET", "/ready", timeout=10)
    if not EXPECT_GATEWAY_REDIS_READY:
        if resp.status_code == 200:
            body = resp.json()
            cache_item = next((item for item in body.get("status_items", []) if item.get("name") == "Cache"), None)
            assert cache_item is None or cache_item.get("status_code") != 200, f"expected gateway-level Redis to fail, but /ready was healthy; body={body}"
        say(f"Gateway Redis check — expected /ready failure observed with HTTP {resp.status_code}")
        return

    assert resp.status_code == 200, f"gateway-level /ready failed with HTTP {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    cache_item = next((item for item in body.get("status_items", []) if item.get("name") == "Cache"), None)
    assert cache_item is not None, f"gateway /ready did not include Cache status; body={body}"
    assert cache_item.get("status_code") == 200, f"gateway-level Redis cache is not ready; cache={cache_item}, body={body}"

    say(f"Gateway Redis check — /ready Cache status {cache_item.get('status_code')} ({cache_item.get('message')})")


def _find_server_and_tool(token: str) -> tuple[str, str]:
    resp = _request("GET", "/servers", token=token, timeout=10)
    assert resp.status_code == 200, f"expected authenticated /servers to return 200, got HTTP {resp.status_code}: {resp.text[:300]}"
    servers = resp.json()
    assert isinstance(servers, list), f"expected /servers response list, got {type(servers).__name__}: {servers!r}"
    for s in servers:
        for t in s.get("associatedTools") or []:
            if "fast-time" in (t or "").lower() and "get-system-time" in (t or "").lower():
                return s["id"], t
    pytest.skip("No virtual server with a fast-time get-system-time tool — run ./rl-shared-bake/static-up.sh")


def _resolve_tool_id(token: str, tool_name: str) -> str:
    tools = _request("GET", "/tools", token=token, timeout=10).json()
    tid = next((t["id"] for t in tools if t.get("name") == tool_name), None)
    if not tid:
        pytest.skip(f"Could not resolve tool id for {tool_name!r}")
    return tid


def _create_test_team(token: str) -> str:
    resp = _request(
        "POST",
        "/teams/",
        token=token,
        json={"name": f"rl-static-team-{uuid.uuid4().hex[:8]}", "description": "static rate-limiter team"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _call_tool(server_id: str, tool_name: str, token: str, index: int) -> tuple[str, str]:
    payload = {
        "jsonrpc": "2.0",
        "id": f"static-{index + 1}",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }
    try:
        resp = _request("POST", f"/servers/{server_id}/mcp", token=token, json=payload)
    except requests.RequestException as exc:
        return "error", f"ERROR ({type(exc).__name__}: {exc})"

    if resp.status_code == 429:
        return "rate_limited", "BLOCKED (HTTP 429)"
    if resp.status_code != 200:
        return "error", f"ERROR (HTTP {resp.status_code}: {resp.text[:120]})"

    body = resp.json()
    err = body.get("error")
    result = body.get("result", {})
    text = " ".join(c.get("text", "") for c in (result.get("content") or [])).lower()
    if err is not None and "rate limit" in (err.get("message") or "").lower():
        return "rate_limited", "BLOCKED (JSON-RPC rate-limit)"
    if result.get("isError") and "rate limit" in text:
        return "rate_limited", "BLOCKED (MCP isError, rate-limit)"
    if err is not None:
        return "error", f"ERROR (JSON-RPC: {(err.get('message') or '')[:240]})"
    if result.get("isError"):
        return "error", f"ERROR (MCP isError: {text[:240]})"
    return "allowed", "ALLOWED"


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


def _is_backend_unavailable(outcome: str) -> bool:
    lowered = outcome.lower()
    return "backend_unavailable" in lowered or "backend unavailable" in lowered


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
        _assert_gateway_redis_ready(say)
        _assert_auth_is_required(say)
        server_id, tool_name = _find_server_and_tool(token)
        tool_id = _resolve_tool_id(token, tool_name)

        say(f"Phase 1 — static config only (no bindings API): by_user=by_tenant=by_tool={STATIC_LIMIT}/m, enforce")
        say(f"  gateway={GATEWAY_URL}  tls_verify={REQUEST_VERIFY}  expect_auth_required={EXPECT_AUTH_REQUIRED}")
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
        say(f"Phase 3 — firing {STATIC_BURST} tool calls as {ADMIN_EMAIL} with concurrency={STATIC_CONCURRENCY}")
        started = time.perf_counter()
        outcomes: list[tuple[str, str] | None] = [None] * STATIC_BURST
        if STATIC_CONCURRENCY == 1:
            for i in range(STATIC_BURST):
                outcomes[i] = _call_tool(server_id, tool_name, token, i)
        else:
            with ThreadPoolExecutor(max_workers=STATIC_CONCURRENCY) as pool:
                futures = {pool.submit(_call_tool, server_id, tool_name, token, i): i for i in range(STATIC_BURST)}
                for future in as_completed(futures):
                    outcomes[futures[future]] = future.result()
        elapsed = max(time.perf_counter() - started, 0.001)

        finalized = [o for o in outcomes if o is not None]
        allowed = sum(1 for status, _ in finalized if status == "allowed")
        rate_limited = sum(1 for status, _ in finalized if status == "rate_limited")
        errors = sum(1 for status, _ in finalized if status == "error")
        for i, (_status, outcome) in enumerate(finalized):
            say(f"  call {i + 1}/{STATIC_BURST}: {outcome}")

        observed_rps = len(finalized) / elapsed
        say(f"Phase 4 — summary: allowed={allowed}  rate_limited={rate_limited}  errors={errors}  elapsed={elapsed:.3f}s  observed_rps={observed_rps:.1f}")

        if EXPECT_GATEWAY_PLUGIN_BACKEND_UNAVAILABLE:
            assert allowed == 0, f"expected gateway plugin hook to fail closed, but {allowed} calls were allowed"
            assert rate_limited == 0, f"expected BACKEND_UNAVAILABLE errors, not rate-limit blocks; rate_limited={rate_limited}"
            assert errors == STATIC_BURST, f"expected all {STATIC_BURST} gateway calls to fail with BACKEND_UNAVAILABLE, errors={errors}"
            backend_failures = [outcome for status, outcome in finalized if status == "error" and _is_backend_unavailable(outcome)]
            assert len(backend_failures) == STATIC_BURST, f"expected BACKEND_UNAVAILABLE in every error; outcomes={finalized}"
            say("Phase 5 — reproduced issue shape: external gateway MCP tool calls returned BACKEND_UNAVAILABLE")
            return

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
