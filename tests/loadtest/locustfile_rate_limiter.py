# -*- coding: utf-8 -*-
"""Rate limiter correctness load test.

Validates that the RateLimiterPlugin enforces per-user limits correctly across
multiple gateway instances.

How it works
------------
A single user sends requests at a fixed pace of 1 req/s (60 req/min) — exactly
twice the default 30/m per-user limit.  nginx round-robins across 3 gateway
instances, so each instance sees ~20 req/min from this user.

  Memory backend (broken, pre-fix)
    Each instance has its own counter.  20 req/min < 30/m limit on every
    instance → user is NEVER blocked.  Effective limit = 3 × 30 = 90/m.
    Expected result: ~0% failures.

  Redis backend (fixed)
    All instances share one counter.  60 req/min > 30/m → user is blocked
    after the first 30 requests in each 60-second window.
    Expected result: ~50% failures.

The ~50% vs ~0% difference is visible at a glance in the results table.

Usage
-----
    make benchmark-rate-limiter

    # Or direct invocation:
    locust -f tests/loadtest/locustfile_rate_limiter.py \\
        --host=http://localhost:8080 \\
        --users=1 --spawn-rate=1 --run-time=120s \\
        --headless RateLimitedUser

    # To test with a different limit, set by_user in plugins/config.yaml and
    # pass the configured value so the banner is accurate:
    RL_LIMIT_PER_MIN=60 make benchmark-rate-limiter

Environment Variables
---------------------
    MCP_SERVER_ID:       Virtual server UUID  (auto-detected if empty)
    JWT_SECRET_KEY:      JWT signing secret   (default: my-test-key)
    JWT_ALGORITHM:       JWT algorithm        (default: HS256)
    JWT_AUDIENCE:        JWT audience         (default: mcpgateway-api)
    JWT_ISSUER:          JWT issuer           (default: mcpgateway)
    PLATFORM_ADMIN_EMAIL Admin email for auth (default: admin@example.com)
    RL_LIMIT_PER_MIN:    Configured rate limit displayed in output banner
                         (default: 30)

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any
import uuid

# Third-Party
from locust import constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import WorkerRunner

# =============================================================================
# Configuration
# =============================================================================


def _load_env_file() -> dict[str, str]:
    """Load .env file from project root."""
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip().strip("\"'")
            break
    return env_vars


_ENV = _load_env_file()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key) or _ENV.get(key) or default


JWT_SECRET_KEY = _cfg("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")
ADMIN_EMAIL = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
MCP_SERVER_ID = _cfg("MCP_SERVER_ID", "")

# Rate limit as configured in plugins/config.yaml — only used for the banner.
RL_LIMIT_PER_MIN = int(_cfg("RL_LIMIT_PER_MIN", "30"))

# Fixed pace: 1 req/s = 60 req/min = 2× the default 30/m limit.
# Each of the 3 gateway instances sees ~20 req/min (below the per-instance
# threshold of 30/m in the memory backend but over the shared limit in Redis).
_REQS_PER_SECOND = 1.0

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# =============================================================================
# Shared state
# =============================================================================

_server_id: str = ""
_tool_names: list[str] = []
_detect_done = False


# =============================================================================
# JWT token
# =============================================================================


def _make_token() -> str:
    """Generate a JWT for the admin user (guaranteed to exist in the DB)."""
    import jwt  # pylint: disable=import-outside-toplevel

    payload = {
        "sub": ADMIN_EMAIL,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8760),
        "iat": datetime.now(timezone.utc),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "jti": str(uuid.uuid4()),
        "token_use": "session",
        "user": {
            "email": ADMIN_EMAIL,
            "full_name": "Rate Limit Load Test",
            "is_admin": True,
            "auth_provider": "local",
        },
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


_token: str = ""


def _get_token() -> str:
    global _token  # pylint: disable=global-statement
    if not _token:
        _token = _make_token()
    return _token


# =============================================================================
# Auto-detect server and tools
# =============================================================================


def _auto_detect(host: str) -> None:
    global _server_id, _tool_names, _detect_done  # pylint: disable=global-statement
    if _detect_done:
        return
    _detect_done = True

    import requests  # pylint: disable=import-outside-toplevel

    headers = {"Authorization": f"Bearer {_get_token()}", "Accept": "application/json"}

    if MCP_SERVER_ID:
        _server_id = MCP_SERVER_ID
    else:
        try:
            resp = requests.get(f"{host}/servers", headers=headers, timeout=10)
            servers = resp.json() if resp.status_code == 200 else []
            if isinstance(servers, list) and servers:
                _server_id = servers[0].get("id", "")
        except Exception as exc:
            logger.warning("Server auto-detect failed: %s", exc)

    if _server_id:
        try:
            payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
            resp = requests.post(
                f"{host}/servers/{_server_id}/mcp",
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json().get("result", {})
                _tool_names = [t["name"] for t in result.get("tools", [])]
        except Exception as exc:
            logger.warning("Tool auto-detect failed: %s", exc)

    logger.info("Rate limiter test: server=%s  tools=%s", _server_id, _tool_names)


# =============================================================================
# Event handlers
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    # Default: 1 user, 120s — enough to see two full 60-second rate limit windows
    parser.set_defaults(users=1, spawn_rate=1, run_time="120s")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    host = environment.host or "http://localhost:8080"
    _auto_detect(host)
    if isinstance(environment.runner, WorkerRunner):
        return

    reqs_per_min = int(_REQS_PER_SECOND * 60)
    memory_per_instance = reqs_per_min // 3
    expected_blocked_pct = max(0.0, (reqs_per_min - RL_LIMIT_PER_MIN) / reqs_per_min * 100)

    logger.error("=" * 70)
    logger.error("RATE LIMITER CORRECTNESS TEST")
    logger.error("=" * 70)
    logger.error("  Host:              %s", host)
    logger.error("  Server:            %s", _server_id)
    logger.error("  Tools:             %s", ", ".join(_tool_names[:5]) or "(none)")
    logger.error("  User:              %s", ADMIN_EMAIL)
    logger.error("  Rate limit:        %d req/min (as configured in plugins/config.yaml)", RL_LIMIT_PER_MIN)
    logger.error("  Test pace:         %.0f req/s = %d req/min (%.0fx the limit)", _REQS_PER_SECOND, reqs_per_min, reqs_per_min / RL_LIMIT_PER_MIN)
    logger.error("  Per-instance rate: ~%d req/min (nginx round-robin across 3 instances)", memory_per_instance)
    logger.error("")
    logger.error("  Memory backend: ~0%% failures  — each instance sees %d req/min < %d/m limit", memory_per_instance, RL_LIMIT_PER_MIN)
    logger.error("  Redis backend:  ~%.0f%% failures — shared counter: %d req/min > %d/m limit", expected_blocked_pct, reqs_per_min, RL_LIMIT_PER_MIN)
    logger.error("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.stats
    total = stats.total.num_requests
    infra_fails = stats.total.num_failures

    # Rate-limited requests: tracked as the "[rate-limited]" named entry
    rl_entry = stats.entries.get(("MCP tools/call [rate-limited]", "POST"), None)
    rl_count = rl_entry.num_requests if rl_entry else 0
    allowed_entry = stats.entries.get(("MCP tools/call [allowed]", "POST"), None)
    allowed_count = allowed_entry.num_requests if allowed_entry else 0

    infra_pct = (infra_fails / total * 100) if total > 0 else 0
    rl_pct = (rl_count / total * 100) if total > 0 else 0
    reqs_per_min = int(_REQS_PER_SECOND * 60)
    expected_pct = max(0.0, (reqs_per_min - RL_LIMIT_PER_MIN) / reqs_per_min * 100)

    print("\n" + "=" * 90)
    print("RATE LIMITER CORRECTNESS — RESULTS")
    print("=" * 90)
    print(f"\n  {'OVERALL':^86}")
    print("  " + "-" * 86)
    print(f"  Total tool call requests:  {total - (rl_entry.num_requests if rl_entry else 0):>8,}  (tool calls sent)")
    print(f"  Allowed through:           {allowed_count:>8,}")
    print(f"  Rate-limited (blocked):    {rl_count:>8,}  ({rl_pct:.1f}%  |  expected ~{expected_pct:.0f}% with Redis)")
    print(f"  Infrastructure failures:   {infra_fails:>8,}  ({infra_pct:.1f}%)")
    print()
    print(f"  Configured limit:   {RL_LIMIT_PER_MIN} req/min per user")
    print(f"  Test pace:          {reqs_per_min} req/min  (~{reqs_per_min // 3} req/min per gateway instance)")
    print()

    if rl_pct >= expected_pct * 0.5:
        verdict = f"✅  REDIS BACKEND — limit correctly enforced ({rl_pct:.0f}% blocked, expected ~{expected_pct:.0f}%)"
    elif rl_pct < 2 and total > 50:
        verdict = f"❌  MEMORY BACKEND — limit NOT enforced across instances ({rl_pct:.0f}% blocked, expected ~{expected_pct:.0f}%)"
    else:
        verdict = f"⚠️   INCONCLUSIVE — {rl_pct:.0f}% blocked (expected ~{expected_pct:.0f}%)"

    print(f"  Verdict:  {verdict}")

    if total > 0:
        print("\n  Response Times (all requests, ms):")
        print(f"    Average: {stats.total.avg_response_time:>8.1f}")
        print(f"    p50:     {stats.total.get_response_time_percentile(0.50):>8.1f}")
        print(f"    p90:     {stats.total.get_response_time_percentile(0.90):>8.1f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):>8.1f}")

    entries = sorted(stats.entries.values(), key=lambda e: e.num_requests, reverse=True)
    if entries:
        print(f"\n  {'BREAKDOWN':^86}")
        print("  " + "-" * 86)
        print(f"  {'Name':<50} {'Reqs':>8} {'Fails':>8} {'Avg(ms)':>8}")
        print("  " + "-" * 86)
        for entry in entries[:10]:
            print(f"  {entry.name:<50} {entry.num_requests:>8,} {entry.num_failures:>8,} {entry.avg_response_time:>8.1f}")

    print("\n" + "=" * 90 + "\n")


# =============================================================================
# Helpers
# =============================================================================


def _jsonrpc(method: str, params: dict | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
    if params is not None:
        body["params"] = params
    return body


# =============================================================================
# RateLimitedUser
# =============================================================================


class RateLimitedUser(FastHttpUser):
    """Sends tool calls at a fixed pace designed to expose the multi-instance
    rate limit enforcement gap.

    Pace: 1 req/s = 60 req/min = 2× the default 30/m per-user limit.

    With 3 gateway instances behind nginx:
      - Each instance sees ~20 req/min  →  below the per-instance limit
      - Memory backend: never blocked   →  ~0% failures  (the bug)
      - Redis backend:  blocked after 30/min  →  ~50% failures  (the fix)

    Rate-limited responses (isError: true in the MCP result) are re-issued as
    a separate named POST so they appear as a distinct row in the results table.
    """

    wait_time = constant_throughput(_REQS_PER_SECOND)
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mcp_session_id: str | None = None
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {_get_token()}",
        }
        if self._mcp_session_id:
            h["Mcp-Session-Id"] = self._mcp_session_id
        return h

    def _mcp_post(self, method: str, params: dict | None, name: str) -> dict | None:
        if not _server_id:
            return None
        try:
            with self.client.post(
                f"/servers/{_server_id}/mcp",
                data=json.dumps(_jsonrpc(method, params)),
                headers=self._headers(),
                name=name,
                catch_response=True,
            ) as response:
                sid = response.headers.get("Mcp-Session-Id") if response.headers else None
                if sid:
                    self._mcp_session_id = sid

                if response.status_code in (502, 503, 504):
                    response.failure(f"Infrastructure error: {response.status_code}")
                    return None
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return None
                try:
                    data = response.json()
                except Exception:
                    response.failure("Invalid JSON")
                    return None
                if data is None:
                    response.failure("Null response")
                    return None
                if "error" in data:
                    err = data["error"]
                    response.failure(f"JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}")
                    return None
                response.success()
                return data.get("result")
        except Exception as exc:
            logger.warning("Request failed (%s): %s", name, exc)
            return None

    def _ensure_initialized(self) -> None:
        if self._initialized or not _server_id:
            return
        result = self._mcp_post(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "locust-rate-limiter-test", "version": "1.0.0"},
            },
            "MCP initialize",
        )
        if result is not None:
            self._initialized = True

    def on_start(self) -> None:
        self._ensure_initialized()

    @task
    @tag("rate-limit", "tools", "call")
    def call_tool(self) -> None:
        """Call a tool and separately count rate-limited responses.

        Two named requests are used:
          - 'MCP tools/call [allowed]'      — the actual request (always fired)
          - 'MCP tools/call [rate-limited]' — a zero-cost marker fired only
            when the result contains isError=true (rate limit hit)
        This lets Locust show allowed vs blocked as separate rows in the table.
        """
        if not _tool_names:
            return

        tool = _tool_names[0]
        name_lower = tool.lower()
        if "time" in name_lower or "timezone" in name_lower:
            args: dict[str, Any] = {"timezone": "UTC"}
        elif "convert" in name_lower:
            args = {"time": "2025-01-01T00:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"}
        elif "echo" in name_lower:
            args = {"message": "rate-limit-test"}
        else:
            args = {}

        result = self._mcp_post("tools/call", {"name": tool, "arguments": args}, "MCP tools/call [allowed]")

        # If the MCP result has isError=true the gateway rate-limited the request
        # (PluginViolationError is surfaced as a tool error, not a JSON-RPC error).
        # Fire an extra named request as a failure marker so it's visible in stats.
        if isinstance(result, dict) and result.get("isError"):
            try:
                with self.client.post(
                    f"/servers/{_server_id}/mcp",
                    data=json.dumps(_jsonrpc("tools/call", {"name": tool, "arguments": args})),
                    headers=self._headers(),
                    name="MCP tools/call [rate-limited]",
                    catch_response=True,
                ) as resp:
                    resp.failure("rate limited")
            except Exception:
                pass
