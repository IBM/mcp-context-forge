# -*- coding: utf-8 -*-
"""Rate limiter algorithm comparison load test.

Compares fixed_window, sliding_window, and token_bucket algorithms under
identical conditions: 1 user sending at 2× the configured per-user limit
through the Redis backend (so multi-instance state is shared).

How it works
------------
A single user sends 1 req/s (60 req/min) — exactly twice the default 30/m
per-user limit.  The test runs for 120 s, covering two full 60-second windows.

The test records requests in 30-second buckets so you can see *when* blocking
starts relative to window boundaries — the key behavioral difference between
algorithms.

A background process streams `docker stats` the entire time, so the final
results table includes gateway and Redis memory/CPU usage alongside the rate
limiting accuracy numbers — no extra tooling required.

Expected results with Redis backend at 30/m limit, 2× pace (60 req/min):
─────────────────────────────────────────────────────────────────────────────
  fixed_window    ~40-48% blocked   First 30 of every window pass freely.
                                    At a window boundary up to 60 requests
                                    can pass (30 end of W1 + 30 start of W2).

  sliding_window  ~50% blocked      No boundary burst — blocks as soon as
                                    30 timestamps exist in the past 60 s.
                                    Blocking is smooth and consistent.
                                    Uses more Redis memory (sorted-set of
                                    timestamps vs a single integer).

  token_bucket    ~50% blocked      Bucket starts full (30 tokens).  First 30
                                    requests drain it; subsequent requests are
                                    blocked until tokens refill at 0.5/s.
                                    Block rate converges to ~50% at steady state.
─────────────────────────────────────────────────────────────────────────────

Usage
-----
    # 1. Set algorithm in plugins/config.yaml:
    #      algorithm: fixed_window   # or sliding_window / token_bucket
    #    Restart gateway: docker restart mcp-context-forge-gateway-{1,2,3}
    #    Flush Redis between runs: docker exec mcp-context-forge-redis-1 redis-cli FLUSHDB

    # 2. Run the test:
    make benchmark-rate-limiter-algorithms

    # 3. Compare results across algorithms — the 30-second bucket breakdown
    #    shows whether boundary bursts occur (fixed_window) or not (others).
    #    The resource table shows memory and CPU consumed during the test.

Environment Variables
---------------------
    RL_ALGORITHM:           Algorithm name shown in banner   (default: fixed_window)
    RL_LIMIT_PER_MIN:       Configured limit displayed       (default: 30)
    MCP_SERVER_ID:          Virtual server UUID              (auto-detected if empty)
    DOCKER_GATEWAY_PATTERN: grep pattern for gateway containers
                            (default: mcp-context-forge-gateway)
    DOCKER_REDIS_PATTERN:   grep pattern for Redis container
                            (default: mcp-context-forge-redis)
    JWT_SECRET_KEY:         JWT signing secret               (default: my-test-key)
    JWT_ALGORITHM:          JWT algorithm                    (default: HS256)
    JWT_AUDIENCE:           JWT audience                     (default: mcpgateway-api)
    JWT_ISSUER:             JWT issuer                       (default: mcpgateway)
    PLATFORM_ADMIN_EMAIL    Admin email for auth             (default: admin@example.com)

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
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

RL_ALGORITHM = _cfg("RL_ALGORITHM", "fixed_window")
RL_LIMIT_PER_MIN = int(_cfg("RL_LIMIT_PER_MIN", "30"))

DOCKER_GATEWAY_PATTERN = _cfg("DOCKER_GATEWAY_PATTERN", "mcp-context-forge-gateway")
DOCKER_REDIS_PATTERN = _cfg("DOCKER_REDIS_PATTERN", "mcp-context-forge-redis")

_REQS_PER_SECOND = 1.0  # 60 req/min = 2× the default 30/m limit

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# =============================================================================
# Shared state — rate limiting
# =============================================================================

_server_id: str = ""
_tool_names: list[str] = []
_detect_done = False
_test_start_time: float = 0.0

# Per-30s bucket counters: bucket_index -> {"allowed": int, "blocked": int}
_bucket_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"allowed": 0, "blocked": 0})


def _current_bucket() -> int:
    """Return 30-second bucket index relative to test start."""
    elapsed = time.time() - _test_start_time if _test_start_time else 0
    return int(elapsed // 30)


# =============================================================================
# Shared state — resource monitor
# =============================================================================

_stats_file: Any = None          # open file handle written to by docker stats
_stats_proc: Any = None          # subprocess.Popen for docker stats
_stats_path: str = ""            # path to the temp file


# =============================================================================
# Resource monitor — helpers
# =============================================================================


def _mem_to_mib(raw: str) -> float:
    """Parse Docker memory string like '143.2MiB' or '1.2GiB' → MiB float."""
    raw = raw.strip()
    match = re.match(r"([\d.]+)\s*([KMGTkmgt]i?[Bb]?)", raw)
    if not match:
        return 0.0
    val = float(match.group(1))
    unit = match.group(2).upper()
    if unit.startswith("K"):
        return val / 1024
    if unit.startswith("M"):
        return val
    if unit.startswith("G"):
        return val * 1024
    if unit.startswith("T"):
        return val * 1024 * 1024
    return val


def _parse_stats_file(path: str) -> dict[str, dict[str, float]]:
    """Parse the docker stats output file.

    Returns a dict:  container_name -> {mem_avg, mem_peak, cpu_avg}
    """
    # samples: container_name -> list of (mem_mib, cpu_pct)
    samples: dict[str, list[tuple[float, float]]] = defaultdict(list)

    # docker stats streaming mode writes ANSI cursor-control sequences
    # (e.g. ESC[H, ESC[J) to reposition the terminal. Strip them before parsing.
    _ansi_escape = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\[[?][0-9;]*[A-Za-z]|\x1b=[^\x1b]*")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = _ansi_escape.sub("", line).strip()
                # docker stats --format "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"
                # skip header-like lines that don't parse
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                name, mem_usage, cpu_perc = parts[0].strip(), parts[1], parts[2]
                # Skip blank names (leftover from escape code stripping)
                if not name:
                    continue
                # mem_usage: "143.2MiB / 15.56GiB" — take the used part
                used_mem = mem_usage.split("/")[0].strip()
                mem_mib = _mem_to_mib(used_mem)
                cpu_str = cpu_perc.replace("%", "").strip()
                try:
                    cpu = float(cpu_str)
                except ValueError:
                    continue
                if mem_mib > 0:
                    samples[name].append((mem_mib, cpu))
    except FileNotFoundError:
        pass

    result: dict[str, dict[str, float]] = {}
    for name, pts in samples.items():
        if not pts:
            continue
        mems = [p[0] for p in pts]
        cpus = [p[1] for p in pts]
        result[name] = {
            "mem_avg": sum(mems) / len(mems),
            "mem_peak": max(mems),
            "cpu_avg": sum(cpus) / len(cpus),
            "cpu_peak": max(cpus),
            "samples": len(pts),
        }
    return result


def _start_resource_monitor() -> None:
    """Spawn docker stats in streaming mode, writing to a temp file."""
    global _stats_file, _stats_proc, _stats_path  # pylint: disable=global-statement
    try:
        fd, _stats_path = tempfile.mkstemp(prefix="rl_algo_stats_", suffix=".tsv")
        _stats_file = os.fdopen(fd, "w")
        _stats_proc = subprocess.Popen(
            [
                "docker", "stats",
                "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}",
            ],
            stdout=_stats_file,
            stderr=subprocess.DEVNULL,
        )
        logger.error("Resource monitor started → %s", _stats_path)
    except FileNotFoundError:
        logger.error("docker CLI not found — resource monitoring disabled")
    except Exception as exc:
        logger.error("Resource monitor failed to start: %s", exc)


def _stop_resource_monitor() -> dict[str, dict[str, float]]:
    """Terminate docker stats and parse the collected data."""
    global _stats_proc, _stats_file  # pylint: disable=global-statement
    if _stats_proc is not None:
        try:
            _stats_proc.terminate()
            _stats_proc.wait(timeout=5)
        except Exception:
            pass
        _stats_proc = None
    if _stats_file is not None:
        try:
            _stats_file.flush()
            _stats_file.close()
        except Exception:
            pass
        _stats_file = None

    return _parse_stats_file(_stats_path) if _stats_path else {}


def _print_resource_table(resource_data: dict[str, dict[str, float]]) -> None:
    """Print gateway and Redis resource usage as a formatted table."""
    if not resource_data:
        print("\n  Resource monitoring unavailable (docker CLI not found or no data collected).")
        return

    gateways = sorted(
        [(n, d) for n, d in resource_data.items() if DOCKER_GATEWAY_PATTERN in n],
        key=lambda x: x[0],
    )
    redis_entries = [(n, d) for n, d in resource_data.items() if DOCKER_REDIS_PATTERN in n]

    rows = gateways + redis_entries
    if not rows:
        print("\n  No matching containers found in stats data.")
        print(f"  (Looking for: '{DOCKER_GATEWAY_PATTERN}' and '{DOCKER_REDIS_PATTERN}')")
        return

    print(f"\n  {'RESOURCE USAGE  (sampled every ~1s via docker stats)':^86}")
    print("  " + "-" * 86)
    print(f"  {'Container':<38} {'Mem avg':>9} {'Mem peak':>9} {'CPU avg':>8} {'CPU peak':>9} {'Samples':>8}")
    print("  " + "-" * 86)

    total_mem_avg = 0.0
    total_mem_peak = 0.0
    for name, d in rows:
        short = name.replace("mcp-context-forge-", "")
        mem_avg = d["mem_avg"]
        mem_peak = d["mem_peak"]
        cpu_avg = d["cpu_avg"]
        cpu_peak = d["cpu_peak"]
        samples = int(d["samples"])
        print(f"  {short:<38} {mem_avg:>7.1f}M {mem_peak:>7.1f}M {cpu_avg:>7.1f}% {cpu_peak:>8.1f}% {samples:>8}")
        if DOCKER_GATEWAY_PATTERN in name:
            total_mem_avg += mem_avg
            total_mem_peak += mem_peak

    if len(gateways) > 1:
        print("  " + "-" * 86)
        print(f"  {'All gateways combined':<38} {total_mem_avg:>7.1f}M {total_mem_peak:>7.1f}M")

    # Redis memory note: sliding_window uses more Redis memory (sorted sets vs integers)
    if redis_entries:
        _, rd = redis_entries[0]
        print(f"\n  Redis peak: {rd['mem_peak']:.1f} MiB")
        print(f"  Note: sliding_window stores one sorted-set entry per request in Redis;")
        print(f"        fixed_window and token_bucket store a single integer per key.")


# =============================================================================
# JWT token
# =============================================================================


def _make_token() -> str:
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
            "full_name": "Algorithm Comparison Load Test",
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
# Auto-detect
# =============================================================================


def _auto_detect(host: str) -> None:
    global _server_id, _tool_names, _detect_done  # pylint: disable=global-statement
    if _detect_done:
        return
    _detect_done = True

    import requests  # pylint: disable=import-outside-toplevel

    headers = {"Authorization": f"Bearer {_get_token()}", "Accept": "application/json, text/event-stream"}

    # Build list of server IDs to try: explicit env var first, then all servers
    server_ids_to_try: list[str] = []
    if MCP_SERVER_ID:
        server_ids_to_try = [MCP_SERVER_ID]
    else:
        try:
            resp = requests.get(f"{host}/servers", headers=headers, timeout=10)
            all_servers = resp.json() if resp.status_code == 200 else []
            server_ids_to_try = [s.get("id", "") for s in (all_servers if isinstance(all_servers, list) else []) if s.get("id")]
        except Exception as exc:
            logger.warning("Server list failed: %s", exc)

    for sid in server_ids_to_try:
        try:
            payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
            resp = requests.post(
                f"{host}/servers/{sid}/mcp",
                json=payload,
                headers={**headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json().get("result", {})
                tools = [t["name"] for t in result.get("tools", [])]
                if tools:
                    _server_id = sid
                    _tool_names = tools
                    break
        except Exception as exc:
            logger.warning("Tool auto-detect failed for server %s: %s", sid, exc)


# =============================================================================
# Algorithm-specific expectations
# =============================================================================

_ALGORITHM_NOTES = {
    "fixed_window": (
        "First 30 of every 60s window pass. "
        "At a window boundary up to 60 requests can pass (30 end of W1 + 30 start of W2). "
        "Expected blocked: ~40-48%. Window 0→1 boundary (t=60s) may show a dip in blocking."
    ),
    "sliding_window": (
        "No window boundary burst — blocks as soon as 30 timestamps exist in past 60s. "
        "Expected blocked: ~50% consistently. "
        "Uses more Redis memory: one sorted-set entry per request vs one integer for fixed_window."
    ),
    "token_bucket": (
        "Starts with a full bucket (30 tokens). First 30 requests drain it immediately. "
        "Tokens refill at 0.5/s (30/min). Sustained block rate converges to ~50%. "
        "Early buckets may show fewer blocks (bucket draining); later buckets are steady."
    ),
}

_ALGORITHM_EXPECTED_BLOCKED_PCT = {
    # fixed_window: 50% at a clean window start; higher if test starts mid-window
    # (first partial window allows fewer than 30 before blocking)
    "fixed_window": (40.0, 80.0),
    # sliding_window: consistently ~50% once window fills; may be higher if
    # prior test state is still in Redis (flush between runs for best results)
    "sliding_window": (45.0, 75.0),
    # token_bucket: starts low (full bucket drains slowly), converges to ~50%
    "token_bucket": (30.0, 60.0),
}


# =============================================================================
# Event handlers
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    parser.set_defaults(users=1, spawn_rate=1, run_time="120s")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global _test_start_time  # pylint: disable=global-statement
    _test_start_time = time.time()

    host = environment.host or "http://localhost:8080"
    _auto_detect(host)
    _start_resource_monitor()

    if isinstance(environment.runner, WorkerRunner):
        return

    reqs_per_min = int(_REQS_PER_SECOND * 60)
    note = _ALGORITHM_NOTES.get(RL_ALGORITHM, "Unknown algorithm.")

    logger.error("=" * 70)
    logger.error("RATE LIMITER ALGORITHM COMPARISON TEST")
    logger.error("=" * 70)
    logger.error("  Host:        %s", host)
    logger.error("  Algorithm:   %s  (set in plugins/config.yaml)", RL_ALGORITHM)
    logger.error("  Limit:       %d req/min per user", RL_LIMIT_PER_MIN)
    logger.error("  Test pace:   %d req/min  (2× the limit)", reqs_per_min)
    logger.error("  Backend:     redis  (required for multi-instance correctness)")
    logger.error("  Duration:    120s  (two full 60s windows)")
    logger.error("")
    logger.error("  Expected behaviour:")
    logger.error("  %s", note)
    logger.error("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    # Stop monitor first so all data is flushed before we print
    resource_data = _stop_resource_monitor()

    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.stats
    total = stats.total.num_requests
    infra_fails = stats.total.num_failures

    rl_entry = stats.entries.get(("MCP tools/call [rate-limited]", "POST"), None)
    rl_count = rl_entry.num_requests if rl_entry else 0
    allowed_entry = stats.entries.get(("MCP tools/call [allowed]", "POST"), None)
    allowed_count = allowed_entry.num_requests if allowed_entry else 0

    # Semantic allowed = main requests that were NOT rate-limited
    semantic_allowed = allowed_count - rl_count
    infra_pct = (infra_fails / total * 100) if total > 0 else 0
    rl_pct = (rl_count / allowed_count * 100) if allowed_count > 0 else 0
    reqs_per_min = int(_REQS_PER_SECOND * 60)

    lo, hi = _ALGORITHM_EXPECTED_BLOCKED_PCT.get(RL_ALGORITHM, (35.0, 55.0))
    if rl_pct >= lo and rl_pct <= hi:
        verdict = f"✅  PASS — {rl_pct:.0f}% blocked (expected {lo:.0f}-{hi:.0f}% for {RL_ALGORITHM})"
    elif allowed_count < 30:
        verdict = "⚠️   INCONCLUSIVE — not enough requests"
    else:
        verdict = f"⚠️   UNEXPECTED — {rl_pct:.0f}% blocked (expected {lo:.0f}-{hi:.0f}% for {RL_ALGORITHM})"

    print("\n" + "=" * 90)
    print(f"RATE LIMITER ALGORITHM COMPARISON — {RL_ALGORITHM.upper()}")
    print("=" * 90)
    print(f"\n  Algorithm:         {RL_ALGORITHM}")
    print(f"  Configured limit:  {RL_LIMIT_PER_MIN} req/min per user")
    print(f"  Test pace:         {reqs_per_min} req/min  (2× the limit)")
    print(f"\n  Tool call attempts:        {allowed_count:>8,}")
    print(f"  Allowed through:           {semantic_allowed:>8,}")
    print(f"  Rate-limited (blocked):    {rl_count:>8,}  ({rl_pct:.1f}%)")
    print(f"  Infrastructure failures:   {infra_fails:>8,}  ({infra_pct:.1f}%)")

    # Per-30s bucket breakdown
    if _bucket_stats:
        print(f"\n  {'30s WINDOW BREAKDOWN':^86}")
        print("  " + "-" * 86)
        print(f"  {'Window':<10} {'Start':>8} {'Allowed':>10} {'Blocked':>10} {'Block%':>8}  Note")
        print("  " + "-" * 86)
        for bucket_idx in sorted(_bucket_stats.keys()):
            b = _bucket_stats[bucket_idx]
            total_b = b["allowed"] + b["blocked"]
            bpct = (b["blocked"] / total_b * 100) if total_b > 0 else 0.0
            start_s = bucket_idx * 30
            note = ""
            if RL_ALGORITHM == "fixed_window" and bucket_idx == 2:
                note = "<-- window boundary (may show lower block %)"
            print(f"  t={start_s:>3}-{start_s+30:<4}s   {start_s:>5}s   {b['allowed']:>8,}   {b['blocked']:>8,}   {bpct:>6.1f}%  {note}")

    # Resource usage table
    _print_resource_table(resource_data)

    print(f"\n  Verdict:  {verdict}")

    note_text = _ALGORITHM_NOTES.get(RL_ALGORITHM, "")
    print(f"\n  Algorithm note:\n  {note_text}")

    if total > 0:
        print("\n  Response Times (ms):")
        print(f"    Average: {stats.total.avg_response_time:>8.1f}")
        print(f"    p50:     {stats.total.get_response_time_percentile(0.50):>8.1f}")
        print(f"    p90:     {stats.total.get_response_time_percentile(0.90):>8.1f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):>8.1f}")

    print("\n  To compare algorithms:")
    print("    1. Flush Redis:  docker exec mcp-context-forge-redis-1 redis-cli FLUSHDB")
    print("    2. Change `algorithm:` in plugins/config.yaml, restart gateways")
    print("    3. RL_ALGORITHM=<algo> make benchmark-rate-limiter-algorithms")

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
# AlgorithmComparisonUser
# =============================================================================


class AlgorithmComparisonUser(FastHttpUser):
    """Sends tool calls at a fixed pace of 1 req/s (2× the default 30/m limit).

    Records per-30s window stats so the results table shows whether blocking
    is uniform (sliding_window, token_bucket) or has boundary dips (fixed_window).
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
            "Accept": "application/json, text/event-stream",
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
                "clientInfo": {"name": "locust-algorithm-comparison", "version": "1.0.0"},
            },
            "MCP initialize",
        )
        if result is not None:
            self._initialized = True

    def on_start(self) -> None:
        self._ensure_initialized()

    @task
    @tag("rate-limit", "algorithm", "tools")
    def call_tool(self) -> None:
        """Call a tool and record allowed vs blocked in per-30s buckets."""
        if not _tool_names:
            return

        tool = _tool_names[0]
        name_lower = tool.lower()
        if "time" in name_lower or "timezone" in name_lower:
            args: dict[str, Any] = {"timezone": "UTC"}
        elif "convert" in name_lower:
            args = {"time": "2025-01-01T00:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"}
        elif "echo" in name_lower:
            args = {"message": "algorithm-test"}
        else:
            args = {}

        result = self._mcp_post("tools/call", {"name": tool, "arguments": args}, "MCP tools/call [allowed]")

        bucket = _current_bucket()

        if isinstance(result, dict) and result.get("isError"):
            _bucket_stats[bucket]["blocked"] += 1
            # Fire a named marker so it appears as a distinct row in Locust's stats table
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
        else:
            _bucket_stats[bucket]["allowed"] += 1
